#!/usr/bin/env python3
"""Verify split DNS with local authoritative stubs; never contact campus/Tailscale DNS."""
import argparse
import json
import pathlib
import socket
import socketserver
import struct
import subprocess
import tempfile
import threading
import time
import yaml
from verify_cores import free_port, connect_socks, readn
from routing_policy import split_dns, DNS_TAG
from merge_mihomo import merge_config
from merge_xray import merge_subscription


class Stub(socketserver.BaseRequestHandler):
    def handle(self):
        data, sock = self.request
        self.server.hits += 1
        noanswer = b'noanswer' in data or b'servfail' in data
        flags = b'\x81\x82' if b'servfail' in data else (b'\x81\x83' if noanswer else b'\x81\x80')
        header = data[:2] + flags + struct.pack('!HHHH', 1, 0 if noanswer else 1, 0, 0)
        answer = b'' if noanswer else b'\xc0\x0c' + struct.pack('!HHIH', 1, 1, 60, 4) + self.server.answer
        sock.sendto(header + data[12:] + answer, self.client_address)


def question(domain):
    return b'\x12\x34\x01\x00\x00\x01\x00\x00\x00\x00\x00\x00' + b''.join(bytes([len(x)])+x.encode() for x in domain.split('.')) + b'\x00\x00\x01\x00\x01'


def exchange(core, port, domain):
    query = question(domain)
    if core == 'mihomo':
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.settimeout(3);s.sendto(query, ('127.0.0.1', port));return s.recvfrom(4096)[0]
    s, _ = connect_socks(port, 1, 53, '8.8.8.8')
    try:
        s.sendall(struct.pack('!H',len(query))+query)
        return readn(s, struct.unpack('!H', readn(s,2))[0])
    finally:s.close()


def main():
    a=argparse.ArgumentParser(description=__doc__)
    a.add_argument('--mihomo',required=True);a.add_argument('--xray',required=True);args=a.parse_args()
    domains=list(split_dns());servers=[]
    for i in range(len(domains)+1):
        srv=socketserver.ThreadingUDPServer(('127.0.0.1',0),Stub)
        srv.hits=0;srv.answer=socket.inet_aton('192.0.2.'+str(i+1))
        threading.Thread(target=srv.serve_forever,daemon=True).start();servers.append(srv)
    try:
        with tempfile.TemporaryDirectory(prefix='leora-dns-') as tmp:
            p=pathlib.Path(tmp)
            for core,binary in [('mihomo',args.mihomo),('xray',args.xray)]:
                port=free_port()
                if core=='mihomo':
                    config=merge_config({'proxies':[{'name':'PROXY','type':'socks5','server':'127.0.0.1','port':9}]},{'rules':[]})
                    config['tun']={'enable':False};config['dns']['listen']=f'127.0.0.1:{port}'
                    config['dns']['nameserver']=[f'udp://127.0.0.1:{servers[-1].server_address[1]}#DIRECT']
                    config['dns']['nameserver-policy']={'+.'+d:f'udp://127.0.0.1:{srv.server_address[1]}#DIRECT' for d,srv in zip(domains,servers)}
                    path=p/'dns.yaml';path.write_text(yaml.safe_dump(config))
                    cmd=[binary,'-d',str(p),'-f',str(path)]
                else:
                    config=merge_subscription({'outbounds':[{'tag':'proxy','protocol':'socks','settings':{'servers':[{'address':'127.0.0.1','port':9}]}}],
                        'inbounds':[{'listen':'127.0.0.1','port':port,'protocol':'socks','settings':{'auth':'noauth','udp':True}}]}, {'routing':{'domainStrategy':'AsIs','rules':[]}})
                    for server,stub in zip(config['dns']['servers'],servers):
                        if isinstance(server,dict):server.update(address='127.0.0.1',port=stub.server_address[1])
                    config['dns']['servers']=config['dns']['servers'][:-2]+[{'address':'127.0.0.1','port':servers[-1].server_address[1]}]
                    internal=config['routing']['rules'][0]
                    internal['ip']=['127.0.0.1'];internal['port']=','.join(str(s.server_address[1]) for s in servers)
                    path=p/'dns.json';path.write_text(json.dumps(config))
                    cmd=[binary,'run','-c',str(path)]
                logpath=p/(core+'.log')
                with logpath.open('w') as log:
                    proc=subprocess.Popen(cmd,stdout=log,stderr=subprocess.STDOUT)
                    try:
                        for _ in range(60):
                            if proc.poll() is not None:raise AssertionError(logpath.read_text())
                            try:
                                with socket.create_connection(('127.0.0.1',port),timeout=.1):break
                            except OSError:time.sleep(.05)
                        else:raise AssertionError('DNS listener did not start')
                        before=servers[-1].hits
                        for domain,stub in zip(domains,servers):
                            for name in (domain,'sub.'+domain):
                                answer=exchange(core,port,name)
                                assert answer[-4:]==stub.answer,(core,name,answer.hex())
                        counts=[s.hits for s in servers]
                        for name in ('noanswer.tail.ts.net','servfail.tail.ts.net'):
                            answer=exchange(core,port,name)
                            assert struct.unpack('!H',answer[6:8])[0]==0,'Unexpected fallback answer'
                        assert servers[-1].hits==before,'Private query fell back to public/default DNS'
                        assert all(s.hits==n for s,n in zip(servers[1:],counts[1:])), 'Private query tried a different resolver'
                        print(f'PASS {core}: 7 resolver policies, apex/subdomains, private NXDOMAIN/SERVFAIL has no fallback',flush=True)
                    except Exception:
                        print(logpath.read_text());raise
                    finally:proc.terminate();proc.wait(timeout=10)
    finally:
        for s in servers:s.shutdown();s.server_close()


if __name__=='__main__':main()
