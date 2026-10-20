#!/usr/bin/env python3
"""Build protected Mihomo and Xray profiles from Shadowrocket blocking sources.
Python 3.10+, pip install PyYAML. No subscription credentials are needed.
"""
import argparse, concurrent.futures, datetime, hashlib, ipaddress, json, pathlib, re, urllib.request
import yaml
from routing_policy import mihomo_settings, protected_mihomo, protected_xray
SOURCE='https://raw.githubusercontent.com/Tonhie/Leora-ProxyRules/refs/heads/main/Leora-ProxyRules.conf'
DEFAULT_BASE='https://raw.githubusercontent.com/Tonhie/Leora-ProxyRules/refs/heads/main'
P=pathlib.Path(__file__).resolve().parent
CACHE=P/'.cache'; CACHE.mkdir(exist_ok=True)

def fetch(url):
    path=CACHE/hashlib.sha256(url.encode()).hexdigest()
    if ARGS.offline:
        return path.read_text(encoding='utf-8-sig')
    for attempt in range(3):
        try:
            req=urllib.request.Request(url,headers={'User-Agent':'Leora-Rule-Builder/1.0'})
            data=urllib.request.urlopen(req,timeout=35).read()
            text=data.decode('utf-8-sig');path.write_text(text);return text
        except Exception:
            if attempt==2: raise

def significant(text):
    return [x.strip() for x in text.splitlines() if x.strip() and not x.strip().startswith(('#',';','//','['))]

def parse(text,domain_set=False):
    out=[]; skipped=[]
    for line in significant(text):
        if domain_set:
            if ',' in line:raise ValueError('Unexpected DOMAIN-SET entry: '+line)
            if line.startswith('+.'):
                out.append(('DOMAIN-SUFFIX',line[2:],False))
            elif line.startswith('.'):
                out.append(('DOMAIN-SUFFIX',line[1:],False))
            elif '*' in line:
                out.append(('DOMAIN-WILDCARD',line,False))
            else:out.append(('DOMAIN',line,False))
            continue
        a=[x.strip() for x in line.split(',')]
        k={'HOST':'DOMAIN','HOST-SUFFIX':'DOMAIN-SUFFIX','HOST-KEYWORD':'DOMAIN-KEYWORD','HOST-WILDCARD':'DOMAIN-WILDCARD','IP6-CIDR':'IP-CIDR6'}.get(a[0],a[0])
        if k in ('USER-AGENT','URL-REGEX'):
            skipped.append(line);continue
        if k not in ('DOMAIN','DOMAIN-SUFFIX','DOMAIN-KEYWORD','DOMAIN-WILDCARD','DOMAIN-REGEX','IP-CIDR','IP-CIDR6','IP-ASN'):
            raise ValueError('Unsupported rule: '+line)
        if len(a)<2:raise ValueError(line)
        value=a[1]
        if k in ('IP-CIDR','IP-CIDR6'):value=str(ipaddress.ip_network(value,strict=False))
        if k=='IP-ASN':int(value)
        out.append((k,value,'no-resolve' in a[2:]))
    return list(dict.fromkeys(out)),skipped

def wildcard_regex(s):return '^'+re.escape(s).replace(r'\*','.*').replace(r'\?','.')+'$'
def classic(rule):
    k,v,n=rule
    if k=='DOMAIN-WILDCARD':k,v='DOMAIN-REGEX',wildcard_regex(v)
    return k+','+v+(',no-resolve' if n and k in ('IP-CIDR','IP-CIDR6','IP-ASN') else '')
def compare(rules):return {classic(r) for r in rules}

def alternative(u):
    if 'blackmatrix7/ios_rule_script/' not in u:return None
    return u.replace('/Shadowrocket/','/Clash/').replace('/QuantumultX/','/Clash/').replace('.list','.yaml')

def dump(name,obj):
    (P/name).parent.mkdir(parents=True,exist_ok=True)
    (P/name).write_text(yaml.safe_dump(obj,allow_unicode=True,sort_keys=False,width=110) if name.endswith('.yaml') else json.dumps(obj,ensure_ascii=False,separators=(',',':'))+'\n')

def run():
    conf=(P/'Leora-ProxyRules.conf').read_text()
    entries=[];in_rules=False
    for line in conf.splitlines():
        line=line.strip()
        if line.startswith('['):in_rules=line=='[Rule]';continue
        if in_rules and line and not line.startswith('#'):entries.append(line)
    entries=[l for l in entries if l.startswith(('RULE-SET,','DOMAIN-SET,')) and l.split(',')[2]=='REJECT']
    sources=list(dict.fromkeys(l.split(',')[1] for l in entries if l.startswith(('RULE-SET,','DOMAIN-SET,'))))
    alts=list(dict.fromkeys(filter(None,map(alternative,sources))))
    alts += [u.removesuffix('.yaml')+'_Domain.yaml' for u in list(alts) if any('/'+x+'/'+x+'.yaml' in u for x in ('China','Global','Apple'))]
    required=sources
    data={}
    with concurrent.futures.ThreadPoolExecutor(max_workers=12) as ex:
        for u,t in zip(required,ex.map(fetch,required)):data[u]=t
    # Alternatives are optional; never silently substitute a non-equivalent list.
    def optional(u):
        try:return u,fetch(u)
        except Exception:return u,None
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as ex:
        for u,t in ex.map(optional,alts):
            if t is not None:data[u]=t
    providers={};clash=[];xr=[]
    conversions=[]
    def xray_rules(rules,target,label):
        tag={'DIRECT':'direct','PROXY':'proxy','REJECT':'block'}[target]
        # Only coalesce adjacent same-condition rules. Never reorder domains vs IPs.
        for k,v,nr in rules:
            if k=='IP-ASN':raise ValueError('ASN matches in blocking sources require an explicit converter')
            elif k in ('IP-CIDR','IP-CIDR6'):key,vals='ip',[v]
            else:
                key='domain'
                vals=[{'DOMAIN':'full:','DOMAIN-SUFFIX':'domain:','DOMAIN-KEYWORD':'','DOMAIN-REGEX':'regexp:','DOMAIN-WILDCARD':'regexp:'}[k]+(wildcard_regex(v) if k=='DOMAIN-WILDCARD' else v)]
            if not vals:continue
            if xr and xr[-1]['outboundTag']==tag and key in xr[-1] and xr[-1].get('ruleTag')==label:
                xr[-1][key].extend(vals)
            else:xr.append({'type':'field',key:vals,'outboundTag':tag,'ruleTag':label})
    for i,line in enumerate(entries):
        a=line.split(',');typ=a[0]
        u,target=a[1:3];rid=f'leora-{i:02d}'
        rules,skipped=parse(data[u],typ=='DOMAIN-SET')
        normalized=[classic(r) for r in rules]
        choice=None;reason='';behavior='classical'
        alt=alternative(u)
        if alt in data:
            candidate=yaml.safe_load(data[alt])
            if isinstance(candidate,dict) and isinstance(candidate.get('payload'),list):
                try:
                    pr,ps=parse('\n'.join(candidate['payload']))
                    if not ps and compare(pr)==set(normalized):choice=(alt,'yaml');reason='Exact equivalent upstream Clash payload (after removing unsupported UA/URL matchers)'
                except Exception:
                    try:
                        pr,ps=parse('\n'.join(candidate['payload']),True)
                        if not ps and compare(pr)==set(normalized):choice=(alt,'yaml');reason='Exact equivalent upstream domain provider';behavior='domain'
                    except Exception:pass
        # Keep the original remote URL only if it is already legal classical text.
        original_lines=significant(data[u])
        if choice is None and not skipped and typ=='RULE-SET' and original_lines==normalized:
            choice=(u,'text');reason='Original URL retained without conversion'
        linked_parts=[]
        if choice is None and alt:
            # Reuse exact SUBSETS too. Consecutive providers with the same action
            # are a union, preserving precedence relative to every other source.
            remaining=set(normalized)
            for v in [alt,alt.removesuffix('.yaml')+'_Domain.yaml']:
                if v not in data:continue
                candidate=yaml.safe_load(data[v])
                if not isinstance(candidate,dict) or not isinstance(candidate.get('payload'),list):continue
                try:
                    pr,ps=parse('\n'.join(candidate['payload']));mode='classical'
                except Exception:
                    try:pr,ps=parse('\n'.join(candidate['payload']),True);mode='domain'
                    except Exception:continue
                subset=compare(pr)
                if ps or not subset or not subset <= set(normalized) or not subset & remaining:continue
                part=rid+'-remote-'+str(len(linked_parts))
                providers[part]={'type':'http','behavior':mode,'format':'yaml','url':v,'path':f'./ruleset/{part}.yaml','interval':86400}
                clash.append(f'RULE-SET,{part},{target}')
                linked_parts.append(v);remaining-=subset
            normalized=[r for r in normalized if r in remaining]
        if choice is None and not normalized:
            xray_rules(rules,target,rid)
            conversions.append({'id':rid,'source':u,'action':target,'clash_urls':linked_parts,'reason':'Union of verified equivalent upstream providers','source_sha256':hashlib.sha256(data[u].encode()).hexdigest(),'converted_rules':len(rules),'unsupported':skipped})
            continue
        if choice is None:
            name=f'providers/{rid}.yaml';dump(name,{'payload':normalized})
            choice=(ARGS.base.rstrip('/')+'/'+name,'yaml');reason='No verified equivalent upstream payload; converted provider hosted in your repository'
        providers[rid]={'type':'http','behavior':behavior,'format':choice[1],'url':choice[0],'path':f'./ruleset/{rid}.{choice[1]}','interval':86400}
        clash.append(f'RULE-SET,{rid},{target}')
        xray_rules(rules,target,rid)
        conversions.append({'id':rid,'source':u,'action':target,'clash_url':choice[0],'clash_urls':linked_parts+[choice[0]],'reason':reason,'source_sha256':hashlib.sha256(data[u].encode()).hexdigest(),'converted_rules':len(rules),'unsupported':skipped})
    for r in xr:
        for k in ('domain','ip'):
            if k in r:r[k]=list(dict.fromkeys(r[k]))
    clash=protected_mihomo(clash)
    xr=protected_xray(xr)
    dump('Leora-Clash-Routing.yaml',dict(mihomo_settings(),**{'rule-providers':providers,'rules':clash}))
    dump('Leora-Xray-Routing.json',{'routing':{'domainStrategy':'IPOnDemand','rules':xr}})
    used={v['url'].split('/providers/')[-1] for v in providers.values() if '/providers/' in v['url']}
    for stale in (P/'providers').glob('leora-*.yaml'):
        if stale.name not in used:stale.unlink()
    dump('conversion-report.json',{'generated_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'source':SOURCE,'base':ARGS.base,'providers':conversions,'source_sha256':hashlib.sha256(conf.encode()).hexdigest(),'policy':'ads-first; UDP proxy-or-reject; trusted mainland Steam HTTP(S) direct; remaining traffic proxy','xray_rules':len(xr),'upstream_provider_count':sum(not r['url'].startswith(ARGS.base.rstrip('/')+'/providers/') for r in providers.values())})
    print(json.dumps({'providers':len(providers),'upstream_links':sum(not r['url'].startswith(ARGS.base.rstrip('/')+'/providers/') for r in providers.values()),'converted_providers':sum(r['url'].startswith(ARGS.base.rstrip('/')+'/providers/') for r in providers.values()),'xray_rules':len(xr),'unsupported_count':sum(len(r['unsupported']) for r in conversions)}))

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--base',default=DEFAULT_BASE,help='GitHub raw URL for the directory containing this script');parser.add_argument('--offline',action='store_true');ARGS=parser.parse_args();run()
