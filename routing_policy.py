"""Mandatory transport policy; these do not spoof STUN or install a packet tunnel."""

import ipaddress
import re
from urllib.parse import urlsplit
from pathlib import Path

TAILNET_RANGES = ('100.64.0.0/10', 'fd7a:115c:a1e0::/48')
DNS_TAG = 'leora-dns'
DNS_OUT = 'leora-dns-out'


def split_dns():
    """Read the canonical server: mappings from the Shadowrocket Host section."""
    text = (Path(__file__).resolve().parent / 'Leora-ProxyRules.conf').read_text()
    section = text.split('[Host]', 1)[1].split('[', 1)[0]
    result = {}
    for line in section.splitlines():
        if '=' not in line or line.lstrip().startswith('#'):
            continue
        domain, value = (x.strip() for x in line.split('=', 1))
        if not value.startswith('server:'):
            continue
        domain = domain.removeprefix('*.')
        resolver = str(ipaddress.ip_address(value.removeprefix('server:')))
        if domain in result and result[domain] != resolver:
            raise ValueError('Conflicting split DNS mapping: ' + domain)
        result[domain] = resolver
    if result.get('ts.net') != '100.100.100.100':
        raise ValueError('Expected Tailscale Quad100 mapping in canonical Host section')
    return result


# These transport guards cannot identify STUN on arbitrary ports. Browser WebRTC
# restrictions remain necessary when preserving public DIRECT routing.
STUN_PORTS = ('3478', '5349', '19302-19309')
STUN_DOMAIN = r'(^|[.-])(stun[0-9]*|turn[0-9]*|turns)([.-]|$)'
BOOTSTRAP_TAG = 'leora-bootstrap'
BOOTSTRAP_DOH = 'https://223.5.5.5/dns-query'


def general():
    text = (Path(__file__).resolve().parent / 'Leora-ProxyRules.conf').read_text()
    section = text.split('[General]', 1)[1].split('[', 1)[0]
    return dict(tuple(v.strip() for v in line.split('=', 1))
                for line in section.splitlines() if '=' in line and not line.lstrip().startswith('#'))


# Every canonical General option must have an explicit mapping or limitation.
# Fixed-value options fail closed if changed, instead of silently keeping old behavior.
GENERAL_MAPPING = {
    'dns-server': 'Mihomo nameserver; Xray routed DoH',
    'fallback-dns-server': 'Mihomo nameserver; Xray additional DoH (selection differs)',
    'direct-dns-server': 'Mihomo direct-nameserver; Xray has no per-outbound DNS selector (uses public proxy DNS)',
    'dns-direct-system': 'No system DNS fallback',
    'dns-direct-fallback-proxy': 'Mihomo direct resolver only; Xray per-outbound DNS distinction unavailable',
    'use-local-host-item-for-proxy': 'No system hosts; static Host entries shared by both engines, no per-proxy Host toggle',
    'ipv6': 'Mihomo global/DNS IPv6; Xray IPv4 DNS and ForceIPv4 direct dialing; client must prevent uncaptured IPv6',
    'prefer-ipv6': 'IPv4 only while IPv6 disabled; IPv6 preference mode unsupported',
    'udp-policy-not-supported-behaviour': 'Mihomo adjacent UDP REJECT guards; Xray proxy errors without DIRECT fallback',
    'stun-response-ip': 'No native spoofing; scoped STUN block plus browser restriction required',
    'stun-response-ipv6': 'No native spoofing; scoped STUN block plus browser restriction required',
    'private-ip-answer': 'Private split DNS answers accepted',
    'bypass-system': 'No generated system-service bypass; external client capture must be verified',
    'skip-proxy': 'Canonical DIRECT rules; external system proxy bypass needs client setup',
    'tun-excluded-routes': 'Mihomo route-exclude-address; Xray DIRECT rules plus external client route exclusions',
}
FIXED_GENERAL = {
    'dns-direct-system': 'false', 'dns-direct-fallback-proxy': 'false',
    'use-local-host-item-for-proxy': 'false', 'prefer-ipv6': 'false',
    'udp-policy-not-supported-behaviour': 'REJECT',
    'stun-response-ip': '127.0.0.1', 'stun-response-ipv6': '::1',
    'private-ip-answer': 'true', 'bypass-system': 'false',
}


def basic_settings_audit():
    policy = general()
    if set(policy) != set(GENERAL_MAPPING):
        raise ValueError('Unmapped or missing General options: ' + str(set(policy) ^ set(GENERAL_MAPPING)))
    for key, expected in FIXED_GENERAL.items():
        if policy[key] != expected:
            raise ValueError('General option requires a new conversion implementation: ' + key)
    if policy['ipv6'] not in ('true', 'false'):
        raise ValueError('Invalid ipv6 boolean')
    return {k: {'source': v, 'implementation': GENERAL_MAPPING[k]} for k, v in policy.items()}


def ipv6_enabled():
    basic_settings_audit()
    return general()['ipv6'] == 'true'


def excluded_routes():
    return list(dict.fromkeys(str(ipaddress.ip_network(v.strip()))
                             for v in general()['tun-excluded-routes'].split(',')))


def bypass_rules():
    rules = []
    for value in general()['skip-proxy'].split(','):
        value = value.strip()
        try:
            net = ipaddress.ip_network(value)
            rule = ('IP-CIDR6' if net.version == 6 else 'IP-CIDR', str(net), True)
        except ValueError:
            if value.startswith('*.'):
                rule = ('DOMAIN-WILDCARD', value, False)
            elif '*' in value or '?' in value:
                raise ValueError('Unsupported skip-proxy pattern: ' + value)
            else:
                rule = ('DOMAIN', value, False)
        if rule not in rules:
            rules.append(rule)
    for value in excluded_routes():
        rule = ('IP-CIDR6' if ':' in value else 'IP-CIDR', value, True)
        if rule not in rules:
            rules.append(rule)
    return rules


def static_hosts():
    text = (Path(__file__).resolve().parent / 'Leora-ProxyRules.conf').read_text()
    section = text.split('[Host]', 1)[1].split('[', 1)[0]
    hosts = {}
    for line in section.splitlines():
        if '=' not in line or line.lstrip().startswith('#'):
            continue
        domain, value = (v.strip() for v in line.split('=', 1))
        if not value.startswith('server:'):
            if '*' in domain:
                raise ValueError('Static wildcard Host requires explicit conversion: ' + domain)
            hosts[domain] = str(ipaddress.ip_address(value))
    return hosts


def public_dns():
    policy = general()
    result = []
    for key in ('dns-server', 'fallback-dns-server'):
        value = policy[key]
        parsed = urlsplit(value)
        if parsed.scheme != 'https' or parsed.fragment != 'proxy':
            raise ValueError('Public DNS must use HTTPS through proxy: ' + key)
        ipaddress.ip_address(parsed.hostname)  # Avoid system DNS bootstrap.
        result.append(value.rsplit('#', 1)[0])
    if policy['dns-direct-system'] != 'false':
        raise ValueError('System DNS fallback is incompatible with leak protection')
    return result


def mihomo_dns_outbound():
    return {'name': DNS_OUT, 'type': 'dns'}


def xray_dns_routes():
    return [
        {'type': 'field', 'inboundTag': [DNS_TAG], 'network': 'tcp,udp', 'port': '53',
         'ip': list(dict.fromkeys(split_dns().values())),
         'outboundTag': 'direct', 'ruleTag': 'split-dns-direct'},
        {'type': 'field', 'inboundTag': [BOOTSTRAP_TAG], 'network': 'tcp', 'port': '443',
         'ip': [urlsplit(BOOTSTRAP_DOH).hostname],
         'outboundTag': 'direct', 'ruleTag': 'bootstrap-dns-direct'},
        {'type': 'field', 'inboundTag': [DNS_TAG], 'network': 'tcp', 'port': '443',
         'ip': list(dict.fromkeys(urlsplit(u).hostname for u in public_dns())),
         'outboundTag': 'proxy', 'ruleTag': 'public-dns-proxy'},
        {'type': 'field', 'inboundTag': [DNS_TAG, BOOTSTRAP_TAG],
         'outboundTag': 'block', 'ruleTag': 'internal-dns-deny'},
        {'type': 'field', 'network': 'tcp,udp', 'port': '53',
         'outboundTag': DNS_OUT, 'ruleTag': 'dns-intercept'},
    ]


def xray_dns():
    return {'tag': DNS_TAG, 'hosts': static_hosts(),
            'queryStrategy': 'UseIP' if ipv6_enabled() else 'UseIPv4',
            'disableFallbackIfMatch': True,
            'servers': [
                {'address': ip, 'domains': ['domain:' + d], 'skipFallback': True, 'finalQuery': True}
                for d, ip in split_dns().items()
            ] + public_dns()}


def mihomo_transport_guards():
    return ['DST-PORT,' + '/'.join(STUN_PORTS) + ',REJECT',
            'DOMAIN-REGEX,' + STUN_DOMAIN + ',REJECT',
            'DST-PORT,853,REJECT']


def xray_transport_guards():
    return [
        {'type': 'field', 'network': 'tcp,udp', 'port': ','.join(STUN_PORTS),
         'outboundTag': 'block', 'ruleTag': 'stun-ports'},
        {'type': 'field', 'domain': ['regexp:' + STUN_DOMAIN],
         'outboundTag': 'block', 'ruleTag': 'stun-domain'},
        {'type': 'field', 'network': 'tcp,udp', 'port': '853',
         'outboundTag': 'block', 'ruleTag': 'external-dot-deny'},
    ]


def local_conditions():
    domains = {v.removeprefix('*.') for k, v, _ in bypass_rules() if k.startswith('DOMAIN')} | set(split_dns())
    nets = {v for k, v, _ in bypass_rules() if k.startswith('IP-')} | set(TAILNET_RANGES)
    return domains, nets


def is_local_mihomo(rule):
    parts = rule.split(',')
    domains, nets = local_conditions()
    return (len(parts)>=3 and parts[2]=='DIRECT' and
            ((parts[0]=='DOMAIN-REGEX' and parts[1] in {'^'+re.escape(v).replace(r'\*','.*').replace(r'\?','.')+'$' for k,v,_ in bypass_rules() if k=='DOMAIN-WILDCARD'}) or
             (parts[0] in ('DOMAIN','DOMAIN-SUFFIX','DOMAIN-WILDCARD') and parts[1].removeprefix('*.') in domains) or
             (parts[0] in ('IP-CIDR','IP-CIDR6') and parts[1] in nets)))


def is_local_xray(rule):
    domains, nets = local_conditions()
    return (rule.get('outboundTag')=='direct' and
            ((bool(rule.get('domain')) and set(rule['domain']) <=
              {'domain:'+d for d in domains} | {'full:'+d for d in domains} |
              {'regexp:^' + re.escape(v).replace(r'\*', '.*').replace(r'\?', '.') + '$' for k,v,_ in bypass_rules() if k=='DOMAIN-WILDCARD'}) or
             (bool(rule.get('ip')) and set(rule['ip']) <= nets)))


def xray_dns_for_config(config):
    dns = xray_dns()
    domains = set()
    private = tuple(split_dns())
    for outbound in config['outbounds']:
        settings = outbound.get('settings', {})
        for server in settings.get('servers', []) + settings.get('vnext', []):
            host = server.get('address', '')
            if not isinstance(host, str) or not host:
                continue
            host = host.lower().rstrip('.')
            try:
                ipaddress.ip_address(host)
                continue
            except ValueError:
                pass
            if not any(host == d or host.endswith('.' + d) for d in private):
                domains.add('full:' + host)
    if domains:
        dns['servers'].insert(0, {'address': BOOTSTRAP_DOH, 'tag': BOOTSTRAP_TAG, 'domains': sorted(domains),
                                  'skipFallback': True, 'finalQuery': True})
    return dns


def xray_direct_settings():
    return {'domainStrategy': 'UseIP' if ipv6_enabled() else 'ForceIPv4'}


def dns_outbound():
    return {'tag': DNS_OUT, 'protocol': 'dns', 'settings': {'nonIPQuery': 'reject'}}


# Curated mainland CDN endpoints; avoid broad SteamCN entries that include the store.
STEAM_DOWNLOADS = (
    'dl.steam.clngaa.com', 'dl.steam.ksyna.com', 'st.dl.bscstorage.net',
    'st.dl.eccdnx.com', 'st.dl.pinyuncloud.com',
    'steampipe.steamcontent.tnkjmec.com', 'steampowered.com.8686c.com',
    'steamstatic.com.8686c.com', 'xz.pphimalayanrt.com',
    'cdn-ali.content.steamchina.com', 'cdn-qc.content.steamchina.com',
    'cdn-ws.content.steamchina.com',
)
STEAM_DOWNLOAD_SUFFIXES = ('steamcontent.com',)
STEAM_PROXY = ('steampowered.com', 'steamcommunity.com', 'steamstatic.com',
               'steamchina.com', 'steamstore-a.akamaihd.net')


def mihomo_settings():
    return {
        'mode': 'rule', 'ipv6': ipv6_enabled(), 'hosts': static_hosts(),
        'tun': {'enable': True, 'stack': 'mixed', 'auto-route': True,
                'auto-detect-interface': True, 'strict-route': True,
                **({'inet6-address': ['fdfe:dcba:9876::1/126']} if ipv6_enabled() else {}),
                'dns-hijack': ['any:53', 'tcp://any:53'],
                'route-exclude-address': excluded_routes()},
        'dns': {'enable': True, 'ipv6': ipv6_enabled(), 'respect-rules': True,
                'use-system-hosts': False, 'direct-nameserver-follow-policy': True,
                'enhanced-mode': 'fake-ip', 'fake-ip-range': '198.18.0.1/16',
                'fake-ip-filter': ['+.' + d for d in split_dns()],
                'nameserver-policy': {'+.' + d: 'udp://' + ip + '#DIRECT' for d, ip in split_dns().items()},
                'default-nameserver': [BOOTSTRAP_DOH],
                'proxy-server-nameserver': [BOOTSTRAP_DOH + '#DIRECT'],
                'proxy-server-nameserver-policy': {'+.' + d: 'udp://' + ip + '#DIRECT' for d, ip in split_dns().items()},
                'direct-nameserver': [general()['direct-dns-server'] + '#DIRECT'],
                'nameserver': [u+'#PROXY' for u in public_dns()]}}


def protected_mihomo(rules, proxy_name='PROXY'):
    """Preserve source order; fail closed only after a matching proxy rule.

    Mihomo skips a proxy without UDP support and continues matching rules.
    An adjacent UDP reject for that same condition prevents falling into a
    later DIRECT rule. Applying this twice must not duplicate the guards.
    """
    if not proxy_name or any(c in proxy_name for c in ',\r\n#&'):
        raise ValueError('Invalid proxy name')
    # Put privacy overrides after only the canonical local bypass. Keep all
    # other source rules as an ordered subsequence, without promoting DIRECT.
    guards = mihomo_transport_guards()
    dns_rule = 'DST-PORT,53,' + DNS_OUT
    rules = [r for r in rules if r not in guards and r != dns_rule]
    offset = 0
    while offset < len(rules) and is_local_mihomo(rules[offset]):
        offset += 1
    rules = [dns_rule] + rules[:offset] + guards + rules[offset:]
    result = []
    for index, rule in enumerate(rules):
        parts = rule.split(',')
        pos = -2 if parts[-1] == 'no-resolve' else -1
        if parts[pos] == 'PROXY':
            parts[pos] = proxy_name
        mapped = ','.join(parts)
        result.append(mapped)
        if parts[pos] != proxy_name:
            continue
        condition = ','.join(parts[:pos])
        guard = ('NETWORK,udp,REJECT' if condition == 'MATCH' else
                 'AND,((NETWORK,udp),(' + condition + ')),REJECT' +
                 (',no-resolve' if pos == -2 else ''))
        if index + 1 == len(rules) or rules[index + 1] != guard:
            result.append(guard)
    return result


def protected_xray(rules):
    internal = xray_dns_routes()
    guards = xray_transport_guards()
    tags = {r['ruleTag'] for r in internal + guards}
    rules = [r for r in rules if r.get('ruleTag') not in tags]
    offset = 0
    while offset < len(rules) and is_local_xray(rules[offset]):
        offset += 1
    return internal + rules[:offset] + guards + rules[offset:]


def validate_xray_proxy(config, proxy_tag, proxy_balancer):
    outbounds = {o.get('tag'): o for o in config['outbounds']}
    targets = [proxy_tag]
    if proxy_balancer:
        balancer = next(b for b in config.get('routing', {}).get('balancers', [])
                        if b.get('tag') == proxy_balancer)
        selectors = balancer.get('selector', [])
        if not selectors or any(not isinstance(s, str) or not s for s in selectors):
            raise ValueError('WebRTC balancer needs explicit nonempty selectors')
        targets = [tag for tag in outbounds if isinstance(tag, str)
                   and any(tag.startswith(s) for s in selectors)]
        if balancer.get('fallbackTag'):
            targets.append(balancer['fallbackTag'])
        if not targets:
            raise ValueError('WebRTC balancer selects no outbounds')
    for target in targets:
        outbound = outbounds.get(target)
        if not outbound or outbound.get('protocol') in ('freedom', 'blackhole', 'dns', 'loopback', None):
            raise ValueError('WebRTC target must be a real proxy outbound: ' + str(target))


def validate_mihomo_proxy(config, proxy_name, visiting=None):
    visiting = set() if visiting is None else visiting
    if proxy_name in visiting:
        raise ValueError('Proxy group cycle: ' + proxy_name)
    nodes = {p['name']: p for p in config.get('proxies', [])}
    groups = {g['name']: g for g in config.get('proxy-groups', [])}
    if proxy_name in ('DIRECT', 'GLOBAL', 'COMPATIBLE', 'PASS', 'REJECT', 'REJECT-DROP'):
        raise ValueError('WebRTC target cannot be a built-in policy: ' + proxy_name)
    if proxy_name in nodes:
        if nodes[proxy_name].get('type') in ('direct', 'dns', 'reject', 'pass', None):
            raise ValueError('WebRTC target must be a real proxy node: ' + proxy_name)
        return
    group = groups.get(proxy_name)
    if not group or group.get('type') not in ('select', 'url-test', 'fallback', 'load-balance', 'relay'):
        raise ValueError('Missing or unsupported WebRTC proxy/group: ' + proxy_name)
    if any(group.get(k) for k in ('use', 'include-all', 'include-all-proxies', 'include-all-groups',
                                            'filter', 'exclude-filter', 'exclude-type')):
        raise ValueError('Cannot verify dynamic proxy groups; use a concrete node or static group')
    members = group.get('proxies', [])
    if not members:
        raise ValueError('Empty WebRTC proxy group: ' + proxy_name)
    for member in members:
        validate_mihomo_proxy(config, member, visiting | {proxy_name})
