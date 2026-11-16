#!/usr/bin/env python3
"""Validate both generated profiles (Leora and Umbra) with official cores and cached providers."""
import argparse
import hashlib
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import yaml
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from merge_mihomo import merge_config
from merge_xray import merge_subscription
from routing_policy import MODES, routing_file, xray_file, report_file

ROOT=pathlib.Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mihomo',required=True);parser.add_argument('--xray',required=True)
    args=parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='leora-profiles-') as tmp:
        work=pathlib.Path(tmp)
        geoip=pathlib.Path(args.xray).resolve().parent/'geoip.dat'
        if geoip.exists():
            shutil.copyfile(geoip, work/'geoip.dat')
        for mode in MODES:
            report=json.loads((ROOT/report_file(mode)).read_text())
            base=report['base'].rstrip('/')+'/'
            m=yaml.safe_load((ROOT/routing_file(mode)).read_text())
            c=merge_config({'proxies':[{'name':'PROXY','type':'socks5','server':'127.0.0.1','port':9,'udp':True}]},m)
            # Config-only validation never activates system TUN or contacts endpoints.
            for name,provider in c['rule-providers'].items():
                url=provider['url']
                source=(ROOT/'providers'/url.rsplit('/',1)[1] if url.startswith(base+'providers/') else
                        ROOT/'.cache'/hashlib.sha256(url.encode()).hexdigest())
                path=work/(mode+'-'+name+'.'+provider['format']);path.write_text(source.read_text())
                provider.update(type='file',path=str(path))
                provider.pop('url',None)
            path=work/(mode+'-full.yaml');path.write_text(yaml.safe_dump(c))
            subprocess.run([args.mihomo,'-t','-d',str(work),'-f',str(path)],check=True)
            x=merge_subscription({'outbounds':[{'tag':'proxy','protocol':'socks',
                'settings':{'servers':[{'address':'127.0.0.1','port':9}]}}]},
                json.loads((ROOT/xray_file(mode)).read_text()),mode=mode)
            path=work/(mode+'-full.json');path.write_text(json.dumps(x))
            env=dict(os.environ)
            if geoip.exists():
                env['XRAY_LOCATION_ASSET']=str(geoip.parent)
            subprocess.run([args.xray,'run','-test','-c',str(path)],check=True,env=env)
        print('PASS complete generated Mihomo and Xray profiles for leora and umbra')


if __name__=='__main__':main()
