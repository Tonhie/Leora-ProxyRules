#!/usr/bin/env python3
"""Merge the ordered routing overlay into a local Xray JSON subscription.
No network requests. Preserve node credentials, streamSettings and balancers.
This must run on each subscription response in a server-side integration.
"""
import argparse,copy,json,pathlib
from webrtc_guard import MODES, validate_xray_proxy, xray_rules

def merge_subscription(payload, overlay, proxy_tag='proxy', proxy_balancer=None, webrtc=None):
    if webrtc is not None and overlay.get('routing', {}).get('script'):
        raise ValueError('WebRTC guard cannot be combined with a custom routing script')
    result=copy.deepcopy(payload)
    configs=result if isinstance(result,list) else [result]
    if not configs:raise ValueError('Empty subscription')
    for config in configs:
        if not isinstance(config,dict) or not isinstance(config.get('outbounds'),list):
            raise ValueError('Expected complete Xray config object(s) with outbounds')
        tags={x.get('tag') for x in config['outbounds']}
        original_routing=config.get('routing',{})
        balancers=original_routing.get('balancers',[])
        if proxy_balancer:
            if proxy_balancer not in {x.get('tag') for x in balancers}:
                raise ValueError('Missing balancer '+proxy_balancer)
        elif proxy_tag not in tags:
            raise ValueError('Missing proxy outbound '+proxy_tag+'; use --proxy-tag or --proxy-balancer')
        for tag,protocol in [('direct','freedom'),('block','blackhole')]:
            if tag not in tags:
                config['outbounds'].append({'tag':tag,'protocol':protocol});tags.add(tag)
            else:
                out=next(x for x in config['outbounds'] if x.get('tag')==tag)
                if out.get('protocol')!=protocol:raise ValueError('Conflicting '+tag+' outbound protocol')
        if webrtc is not None:
            validate_xray_proxy(config, proxy_tag, proxy_balancer)
        routing=copy.deepcopy(overlay['routing'])
        if webrtc is not None:
            rejections=[r for r in routing['rules'] if r.get('outboundTag')=='block']
            remaining=[r for r in routing['rules'] if r.get('outboundTag')!='block']
            routing['rules']=rejections+xray_rules(webrtc)+remaining
        if balancers:routing['balancers']=copy.deepcopy(balancers)
        for r in routing['rules']:
            if r.get('outboundTag')=='proxy':
                if proxy_balancer:r.pop('outboundTag');r['balancerTag']=proxy_balancer
                else:r['outboundTag']=proxy_tag
        # Keep only the explicitly scoped internal API rule before public traffic.
        # These are narrowly scoped inbound rules; never retain old generic routing rules.
        scoped=[copy.deepcopy(r) for r in original_routing.get('rules',[]) if r.get('inboundTag') and set(r['inboundTag']) <= {'api'} and r.get('outboundTag')=='api']
        routing['rules']=scoped+routing['rules']
        config['routing']=routing
    return result

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input',required=True,type=pathlib.Path)
    p.add_argument('--routing',type=pathlib.Path,default=pathlib.Path(__file__).with_name('Leora-Xray-Routing.json'))
    p.add_argument('--output',required=True,type=pathlib.Path)
    g=p.add_mutually_exclusive_group();g.add_argument('--proxy-tag',default='proxy');g.add_argument('--proxy-balancer')
    p.add_argument('--webrtc', choices=MODES, help='udp: guard UDP and common STUN/TURN; strict: proxy all captured TCP/UDP')
    a=p.parse_args()
    if a.input.resolve()==a.output.resolve():p.error('Use a separate output file to keep the original configuration')
    out=merge_subscription(json.loads(a.input.read_text()),json.loads(a.routing.read_text()),a.proxy_tag,a.proxy_balancer,a.webrtc)
    a.output.write_text(json.dumps(out,ensure_ascii=False,separators=(',',':'))+'\n')
if __name__=='__main__':main()
