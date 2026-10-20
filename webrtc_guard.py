"""Opt-in transport guards; these do not spoof STUN or install a packet tunnel."""

MODES = ('udp', 'strict')
STUN_PORTS = '3478,5349,19302-19309'
STUN_DOMAIN = r'(^|\.)(stun|turn|turns)[0-9]*([.-]|$)'


def check_mode(mode):
    if mode not in MODES:
        raise ValueError('WebRTC mode must be udp or strict')


def mihomo_rules(mode, proxy_name='PROXY'):
    check_mode(mode)
    if not proxy_name or any(c in proxy_name for c in ',\r\n#&'):
        raise ValueError('Proxy name cannot contain commas, newlines, # or &')
    # Mihomo skips a matching proxy rule when that proxy cannot carry UDP.
    # The immediate REJECT prevents falling through into a later DIRECT rule.
    rules = [f'NETWORK,udp,{proxy_name}', 'NETWORK,udp,REJECT']
    if mode == 'strict':
        return rules + [f'MATCH,{proxy_name}']
    return rules + [
        f'AND,((NETWORK,tcp),(DST-PORT,3478/5349/19302-19309)),{proxy_name}',
        f'DOMAIN-REGEX,{STUN_DOMAIN},{proxy_name}',
    ]


def xray_rules(mode):
    check_mode(mode)
    if mode == 'strict':
        return [{'type': 'field', 'network': 'tcp,udp',
                 'outboundTag': 'proxy', 'ruleTag': 'webrtc-strict'}]
    # Xray selects the outbound once; a failed UDP outbound does not re-run
    # the routing table to find a DIRECT rule.
    return [
        {'type': 'field', 'network': 'udp', 'outboundTag': 'proxy', 'ruleTag': 'webrtc-udp'},
        {'type': 'field', 'network': 'tcp', 'port': STUN_PORTS,
         'outboundTag': 'proxy', 'ruleTag': 'webrtc-stun-tcp'},
        {'type': 'field', 'domain': ['regexp:' + STUN_DOMAIN],
         'outboundTag': 'proxy', 'ruleTag': 'webrtc-stun-domain'},
    ]


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
