#!/usr/bin/env python3
"""Local packet tests. No TUN activation, external destinations or real proxy credentials."""
import argparse
import json
import pathlib
import socket
import socketserver
import struct
import subprocess
import sys
import tempfile
import threading
import time
import yaml

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from merge_mihomo import merge_config
from merge_xray import merge_subscription

STUN = bytes.fromhex('000100002112a442') + b'leora-test12'


def readn(sock, size):
    data = b''
    while len(data) < size:
        part = sock.recv(size - len(data))
        if not part:
            raise EOFError('Unexpected closed socket')
        data += part
    return data


def address(sock):
    kind = readn(sock, 1)[0]
    size = {1: 4, 4: 16}.get(kind)
    raw = readn(sock, size) if size else readn(sock, readn(sock, 1)[0])
    return kind, raw, struct.unpack('!H', readn(sock, 2))[0]


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


class Echo(socketserver.BaseRequestHandler):
    def handle(self):
        self.server.hits += 1
        self.request.sendall(self.request.recv(4096))


class Socks(socketserver.BaseRequestHandler):
    def handle(self):
        sock = self.request
        sock.settimeout(5)
        try:
            version, methods = readn(sock, 2)
            assert version == 5
            readn(sock, methods)
            sock.sendall(b'\x05\x00')
            _, command, _ = readn(sock, 3)
            address(sock)
            if command == 1:
                self.server.hits += 1
                sock.sendall(b'\x05\x00\x00\x01\x7f\x00\x00\x01\x00\x00')
                sock.sendall(sock.recv(4096))
            elif command == 3:
                port = self.server.udp.getsockname()[1]
                sock.sendall(b'\x05\x00\x00\x01\x7f\x00\x00\x01' + struct.pack('!H', port))
                while sock.recv(1):
                    pass
        except (OSError, EOFError):
            pass


def serve(server):
    server.hits = 0
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def udp_echo(sock, counter):
    while True:
        try:
            data, sender = sock.recvfrom(65535)
            counter[0] += 1
            sock.sendto(data, sender)
        except OSError:
            return


def connect_socks(port, command, target_port, host=None):
    sock = socket.create_connection(('127.0.0.1', port), timeout=2)
    sock.sendall(b'\x05\x01\x00')
    assert readn(sock, 2) == b'\x05\x00'
    destination = bytes([1, 127, 0, 0, 1]) if host is None else bytes([3, len(host)]) + host.encode()
    sock.sendall(bytes([5, command, 0]) + destination + struct.pack('!H', target_port))
    status = readn(sock, 3)
    assert status[1] == 0, status
    _, _, bound_port = address(sock)
    return sock, bound_port


def send_udp(port, target_port):
    control, relay_port = connect_socks(port, 3, 0)
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.settimeout(.6)
            packet = b'\x00\x00\x00\x01\x7f\x00\x00\x01' + struct.pack('!H', target_port) + STUN
            sock.sendto(packet, ('127.0.0.1', relay_port))
            try:
                return sock.recvfrom(65535)[0].endswith(STUN)
            except socket.timeout:
                return False
    finally:
        control.close()


def send_tcp(port, target_port, host=None):
    sock = None
    try:
        sock, _ = connect_socks(port, 1, target_port, host)
        sock.sendall(STUN)
        return sock.recv(4096) == STUN
    except (OSError, EOFError, AssertionError):
        return False
    finally:
        if sock:
            sock.close()


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def run_case(binary, core, mode, supported, work, proxy, direct_tcp, direct_udp, direct_hits, proxy_hits):
    port = free_port()
    target_tcp = direct_tcp.server_address[1]
    target_udp = direct_udp.getsockname()[1]
    proxy_port = proxy.server_address[1] if supported else free_port()
    overlay = {'routing': {'rules': [{'type': 'field', 'network': 'tcp,udp', 'outboundTag': 'direct'}]}}
    if core == 'mihomo':
        node = {'name': 'PROXY', 'type': 'socks5' if supported else 'http',
                'server': '127.0.0.1', 'port': proxy_port, 'udp': supported}
        base = {'socks-port': port, 'bind-address': '127.0.0.1', 'proxies': [node]}
        routing = {'rules': ['MATCH,DIRECT']}
        config = merge_config(base, routing, mode=mode) if mode else dict(base, rules=routing['rules'])
        # Exercise real routing without changing the machine's tunnel/DNS settings.
        config['tun'] = {'enable': False}
        config['dns'] = {'enable': False}
        config['log-level'] = 'debug'
        config['external-controller'] = ''
        path = work / 'config.yaml'
        path.write_text(yaml.safe_dump(config))
        command = [binary, '-d', str(work), '-f', str(path)]
    else:
        node = {'tag': 'proxy', 'protocol': 'socks' if supported else 'http',
                'settings': {'servers': [{'address': '127.0.0.1', 'port': proxy_port}]}}
        base = {'log': {'loglevel': 'debug'}, 'outbounds': [node], 'inbounds': [
            {'listen': '127.0.0.1', 'port': port, 'protocol': 'socks',
             'settings': {'udp': True, 'auth': 'noauth'}}]}
        config = merge_subscription(base, overlay, webrtc=mode)
        path = work / 'config.json'
        path.write_text(json.dumps(config))
        command = [binary, 'run', '-c', str(path)]
    logpath = work / 'runtime.log'
    with logpath.open('w') as log:
        proc = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT)
        try:
            for _ in range(100):
                if proc.poll() is not None:
                    raise AssertionError(logpath.read_text())
                try:
                    with socket.create_connection(('127.0.0.1', port), timeout=.1):
                        break
                except OSError:
                    time.sleep(.03)
            else:
                raise AssertionError('Core listener did not start')
            before_direct_udp, before_proxy_udp = direct_hits[0], proxy_hits[0]
            received = send_udp(port, target_udp)
            if mode:
                assert direct_hits[0] == before_direct_udp, 'UDP leaked to DIRECT'
                assert received == supported, 'UDP proxy/drop behaviour incorrect'
                if supported:
                    assert proxy_hits[0] > before_proxy_udp, 'UDP did not reach the proxy'
            else:
                assert received and direct_hits[0] > before_direct_udp, 'Negative control failed'
            before_tcp = direct_tcp.hits
            before_proxy_tcp = proxy.hits
            received = send_tcp(port, target_tcp)
            if mode == 'strict':
                assert direct_tcp.hits == before_tcp, 'Unknown-port TCP leaked to DIRECT'
                assert received == supported
                if supported:
                    assert proxy.hits > before_proxy_tcp
            else:
                assert received and direct_tcp.hits > before_tcp
            if mode == 'udp' and supported:
                before_proxy_tcp = proxy.hits
                assert send_tcp(port, 3478), 'Common STUN TCP port was not proxied'
                assert proxy.hits > before_proxy_tcp
                before_proxy_tcp = proxy.hits
                assert send_tcp(port, target_tcp, 'stun1.localhost'), 'STUN domain was not proxied'
                assert proxy.hits > before_proxy_tcp
            print(f'PASS {core} mode={mode or "off"} proxy={"UDP-capable" if supported else "UDP-unsupported/down"}', flush=True)
        except Exception:
            print(logpath.read_text(), file=sys.stderr)
            raise
        finally:
            proc.terminate()
            proc.wait(timeout=10)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mihomo', required=True)
    parser.add_argument('--xray', required=True)
    args = parser.parse_args()
    direct_udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    direct_udp.bind(('127.0.0.1', 0))
    proxy_udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    proxy_udp.bind(('127.0.0.1', 0))
    direct_hits, proxy_hits = [0], [0]
    for sock, hits in [(direct_udp, direct_hits), (proxy_udp, proxy_hits)]:
        threading.Thread(target=udp_echo, args=(sock, hits), daemon=True).start()
    direct_tcp = serve(Server(('127.0.0.1', 0), Echo))
    proxy = serve(Server(('127.0.0.1', 0), Socks))
    proxy.udp = proxy_udp
    try:
        with tempfile.TemporaryDirectory(prefix='leora-packets-') as temp:
            for core, binary in [('mihomo', args.mihomo), ('xray', args.xray)]:
                for mode, supported in [(None, True), ('udp', True), ('udp', False),
                                        ('strict', True), ('strict', False)]:
                    work = pathlib.Path(temp) / (core + '-' + str(mode) + '-' + str(supported))
                    work.mkdir()
                    run_case(str(pathlib.Path(binary).resolve()), core, mode, supported,
                             work, proxy, direct_tcp, direct_udp, direct_hits, proxy_hits)
    finally:
        direct_tcp.shutdown()
        proxy.shutdown()
        direct_tcp.server_close()
        proxy.server_close()
        direct_udp.close()
        proxy_udp.close()


if __name__ == '__main__':
    main()
