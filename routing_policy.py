"""Mandatory transport policy; these do not spoof STUN or install a packet tunnel."""

import ipaddress
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


def mihomo_local_rules():
    return ([f'DOMAIN-SUFFIX,{domain},DIRECT' for domain in split_dns()] +
            [f'IP-CIDR{6 if ":" in cidr else ""},{cidr},DIRECT,no-resolve' for cidr in TAILNET_RANGES])


def xray_local_rules():
    resolvers = list(dict.fromkeys(list(split_dns().values()) + ['223.5.5.5']))
    return [
        {'type': 'field', 'inboundTag': [DNS_TAG], 'network': 'tcp,udp', 'port': '53',
         'ip': resolvers, 'outboundTag': 'direct', 'ruleTag': 'split-dns-direct'},
        {'type': 'field', 'domain': ['domain:' + d for d in split_dns()],
         'outboundTag': 'direct', 'ruleTag': 'split-domain-direct'},
        {'type': 'field', 'ip': list(TAILNET_RANGES),
         'outboundTag': 'direct', 'ruleTag': 'tailnet-ip'},
        {'type': 'field', 'network': 'tcp,udp', 'port': '53',
         'outboundTag': DNS_OUT, 'ruleTag': 'dns-intercept'},
    ]


def xray_dns():
    return {'tag': DNS_TAG, 'hosts': {'localhost': '127.0.0.1'},
            'disableFallbackIfMatch': True,
            'servers': [
                {'address': ip, 'domains': ['domain:' + d], 'skipFallback': True, 'finalQuery': True}
                for d, ip in split_dns().items()
            ] + ['https://1.1.1.1/dns-query', 'https://1.0.0.1/dns-query']}


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
        dns['servers'].insert(0, {'address': '223.5.5.5', 'domains': sorted(domains),
                                  'skipFallback': True, 'finalQuery': True})
    return dns


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
        'mode': 'rule', 'ipv6': True,
        'tun': {'enable': True, 'stack': 'mixed', 'auto-route': True,
                'auto-detect-interface': True, 'strict-route': True,
                'inet6-address': ['fdfe:dcba:9876::1/126'],
                'dns-hijack': ['any:53', 'tcp://any:53'],
                'route-exclude-address': list(TAILNET_RANGES)},
        'dns': {'enable': True, 'ipv6': True, 'respect-rules': True,
                'enhanced-mode': 'fake-ip', 'fake-ip-range': '198.18.0.1/16',
                'fake-ip-filter': ['+.' + d for d in split_dns()],
                'nameserver-policy': {'+.' + d: 'udp://' + ip + '#DIRECT' for d, ip in split_dns().items()},
                'default-nameserver': ['223.5.5.5'],
                'proxy-server-nameserver': ['https://dns.alidns.com/dns-query'],
                'direct-nameserver': ['https://dns.alidns.com/dns-query'],
                'nameserver': ['https://1.1.1.1/dns-query#PROXY',
                               'https://1.0.0.1/dns-query#PROXY']}}


def protected_mihomo(rules, proxy_name='PROXY'):
    """Preserve source order; fail closed only after a matching proxy rule.

    Mihomo skips a proxy without UDP support and continues matching rules.
    An adjacent UDP reject for that same condition prevents falling into a
    later DIRECT rule. Applying this twice must not duplicate the guards.
    """
    if not proxy_name or any(c in proxy_name for c in ',\r\n#&'):
        raise ValueError('Invalid proxy name')
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
    # DNS plumbing precedes user traffic rules. Never discard DIRECT or PROXY
    # entries, and never promote a later rule ahead of its source position.
    internal = [r for r in xray_local_rules()
                if r['ruleTag'] in ('split-dns-direct', 'dns-intercept')]
    tags = {r['ruleTag'] for r in internal}
    return internal + [r for r in rules if r.get('ruleTag') not in tags]


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
