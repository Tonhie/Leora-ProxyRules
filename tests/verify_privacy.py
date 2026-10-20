#!/usr/bin/env python3
"""Local DNS transport tests: proxy-only public lookup, failure and interception.
Replace HTTPS with local DNS-over-TCP stubs to test routing without external
services or changing system trust. Unit tests separately require HTTPS URLs.
"""
import argparse
import json
import pathlib
import socket
import socketserver
import struct
import subprocess
import tempfile
import time
import yaml
from verify_cores import Server, serve, readn, address, free_port, connect_socks
from verify_dns import question
from merge_mihomo import merge_config
from merge_xray import merge_subscription


class DNS(socketserver.BaseRequestHandler):
    def handle(self):
        try:
            self.server.hits += 1
            q = readn(self.request, struct.unpack('!H', readn(self.request, 2))[0])
            response = q[:2] + b'\x81\x80' + struct.pack('!HHHH', 1, 1, 0, 0) + q[12:]
            response += b'\xc0\x0c' + struct.pack('!HHIH', 1, 1, 60, 4) + socket.inet_aton('192.0.2.123')
            self.request.sendall(struct.pack('!H', len(response)) + response)
        except (OSError, EOFError):
            pass


class Proxy(socketserver.BaseRequestHandler):
    def handle(self):
        try:
            sock = self.request
            sock.settimeout(4)
            _, methods = readn(sock, 2)
            readn(sock, methods)
            sock.sendall(b'\x05\x00')
            _, command, _ = readn(sock, 3)
            assert command == 1
            address(sock)
            self.server.hits += 1
            sock.sendall(b'\x05\x00\x00\x01\x7f\x00\x00\x01\x00\x00')
            # Always use the local stub, never forward an arbitrary destination.
            with socket.create_connection(self.server.target, timeout=4) as upstream:
                q = readn(sock, struct.unpack('!H', readn(sock, 2))[0])
                upstream.sendall(struct.pack('!H', len(q)) + q)
                response = readn(upstream, struct.unpack('!H', readn(upstream, 2))[0])
                sock.sendall(struct.pack('!H', len(response)) + response)
        except (OSError, EOFError, AssertionError):
            pass


def lookup(port, name):
    sock, _ = connect_socks(port, 1, 53, '8.8.8.8')
    with sock:
        sock.settimeout(12)
        q = question(name)
        sock.sendall(struct.pack('!H', len(q)) + q)
        return readn(sock, struct.unpack('!H', readn(sock, 2))[0])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mihomo', required=True)
    parser.add_argument('--xray', required=True)
    args = parser.parse_args()
    dns = serve(Server(('127.0.0.1', 0), DNS))
    proxy = serve(Server(('127.0.0.1', 0), Proxy))
    proxy.target = dns.server_address
    try:
        with tempfile.TemporaryDirectory(prefix='leora-privacy-') as tmp:
            work = pathlib.Path(tmp)
            for core, binary in [('mihomo', args.mihomo), ('xray', args.xray)]:
                for working in (True, False):
                    port = free_port()
                    upstream = proxy.server_address[1] if working else free_port()
                    endpoint = f'tcp://127.0.0.1:{dns.server_address[1]}'
                    if core == 'mihomo':
                        config = merge_config({'socks-port': port, 'proxies': [{'name':'PROXY', 'type':'socks5',
                            'server':'127.0.0.1', 'port':upstream, 'udp':True}]}, {'rules':['MATCH,DIRECT']})
                        config['tun'] = {'enable':False}
                        config['external-controller'] = ''
                        config['dns']['enhanced-mode'] = 'redir-host'
                        config['dns']['nameserver'] = [endpoint+'#PROXY']
                        path = work/'mihomo.yaml'
                        path.write_text(yaml.safe_dump(config))
                        command = [binary, '-d', str(work), '-f', str(path)]
                    else:
                        config = merge_subscription({'outbounds':[{'tag':'proxy','protocol':'socks',
                            'settings':{'servers':[{'address':'127.0.0.1','port':upstream}]}}],
                            'inbounds':[{'listen':'127.0.0.1','port':port,'protocol':'socks'}]},
                            {'routing':{'domainStrategy':'AsIs','rules':[{'type':'field','network':'tcp,udp','outboundTag':'direct'}]}})
                        config['dns']['servers'] = [endpoint]
                        public = next(r for r in config['routing']['rules'] if r.get('ruleTag')=='public-dns-proxy')
                        public.update(ip=['127.0.0.1'], port=str(dns.server_address[1]))
                        path = work/'xray.json'
                        path.write_text(json.dumps(config))
                        command = [binary, 'run', '-c', str(path)]
                    logpath = work/(core+'.log')
                    before = (dns.hits, proxy.hits)
                    with logpath.open('w') as log:
                        process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT)
                        try:
                            for _ in range(100):
                                if process.poll() is not None:raise AssertionError(logpath.read_text())
                                try:
                                    with socket.create_connection(('127.0.0.1',port),timeout=.1):break
                                except OSError:time.sleep(.03)
                            else:raise AssertionError('Core failed to start')
                            try:
                                answer = lookup(port,'public.leora.test')
                            except (OSError, EOFError):
                                answer = b''
                            if working:
                                assert answer[-4:]==socket.inet_aton('192.0.2.123'), (core,answer.hex(),logpath.read_text())
                                assert proxy.hits>before[1], 'Public DNS bypassed proxy'
                                assert dns.hits-before[0] == proxy.hits-before[1], 'Unexpected direct DNS query'
                            else:
                                assert not answer or struct.unpack('!H',answer[6:8])[0]==0, 'Failed proxy returned an answer'
                                assert dns.hits==before[0], 'Failed proxy fell back to DIRECT DNS'
                            print(f'PASS {core}: captured TCP/53 public DNS proxy={"working" if working else "down, no direct fallback"}',flush=True)
                        except Exception:
                            print(logpath.read_text());raise
                        finally:
                            process.terminate();process.wait(timeout=10)
    finally:
        proxy.shutdown();proxy.server_close();dns.shutdown();dns.server_close()


if __name__=='__main__':main()
