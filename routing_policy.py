"""Mandatory transport policy; these do not spoof STUN or install a packet tunnel."""

# Curated mainland CDN endpoints; avoid broad SteamCN entries that include the store.
STEAM_DOWNLOADS = (
    'dl.steam.clngaa.com', 'dl.steam.ksyna.com', 'st.dl.bscstorage.net',
    'st.dl.eccdnx.com', 'st.dl.pinyuncloud.com',
    'steampipe.steamcontent.tnkjmec.com', 'steampowered.com.8686c.com',
    'steamstatic.com.8686c.com', 'xz.pphimalayanrt.com',
    'cdn-ali.content.steamchina.com', 'cdn-qc.content.steamchina.com',
    'cdn-ws.content.steamchina.com',
)
STEAM_PROXY = ('steampowered.com', 'steamcommunity.com', 'steamstatic.com',
               'steamchina.com', 'steamstore-a.akamaihd.net')


def mihomo_rules(proxy_name='PROXY'):
    if not proxy_name or any(c in proxy_name for c in ',\r\n#&'):
        raise ValueError('Proxy name cannot contain commas, newlines, # or &')
    # Unsupported UDP must hit REJECT before any direct exception.
    return ([f'NETWORK,udp,{proxy_name}', 'NETWORK,udp,REJECT'] +
            [f'DOMAIN-SUFFIX,{d},{proxy_name}' for d in STEAM_PROXY] +
            [f'AND,((NETWORK,tcp),(DST-PORT,80/443),(DOMAIN,{d})),DIRECT'
             for d in STEAM_DOWNLOADS] + [f'MATCH,{proxy_name}'])


def xray_rules():
    return [
        {'type': 'field', 'network': 'udp', 'outboundTag': 'proxy', 'ruleTag': 'udp-proxy'},
        {'type': 'field', 'domain': ['domain:' + d for d in STEAM_PROXY],
         'outboundTag': 'proxy', 'ruleTag': 'steam-store'},
        {'type': 'field', 'network': 'tcp', 'port': '80,443',
         'domain': ['full:' + d for d in STEAM_DOWNLOADS],
         'outboundTag': 'direct', 'ruleTag': 'steam-download'},
        {'type': 'field', 'network': 'tcp,udp', 'outboundTag': 'proxy', 'ruleTag': 'final-proxy'},
    ]


def mihomo_settings():
    return {
        'mode': 'rule', 'ipv6': True,
        'tun': {'enable': True, 'stack': 'mixed', 'auto-route': True,
                'auto-detect-interface': True, 'strict-route': True,
                'inet6-address': ['fdfe:dcba:9876::1/126'],
                'dns-hijack': ['any:53', 'tcp://any:53']},
        'dns': {'enable': True, 'ipv6': True, 'respect-rules': True,
                'enhanced-mode': 'fake-ip', 'fake-ip-range': '198.18.0.1/16',
                'default-nameserver': ['223.5.5.5'],
                'proxy-server-nameserver': ['https://dns.alidns.com/dns-query'],
                'nameserver': ['https://1.1.1.1/dns-query#PROXY',
                               'https://1.0.0.1/dns-query#PROXY']}}


def protected_mihomo(rules, proxy_name='PROXY'):
    # Do not promote our own UDP fallback when re-merging a published profile.
    rejects = [r for r in rules if r != 'NETWORK,udp,REJECT' and
               (r.split(',')[-1] in ('REJECT', 'REJECT-DROP') or
                (r.endswith(',no-resolve') and r.split(',')[-2] in ('REJECT', 'REJECT-DROP')))]
    return rejects + mihomo_rules(proxy_name)


def protected_xray(rules):
    return [r for r in rules if r.get('outboundTag') == 'block'] + xray_rules()


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
