import copy
import ipaddress
import json
from pathlib import Path
import unittest
import yaml
from merge_mihomo import merge_config
from merge_xray import merge_subscription
from build_rules import provider_name, XRAY_SKIP_INLINE
from routing_policy import STEAM_DOWNLOADS, STEAM_PROXY, protected_mihomo, protected_xray, xray_dns

ROOT = Path(__file__).resolve().parents[1]


class ProviderNameTests(unittest.TestCase):
    def test_provider_names_depend_on_source_and_action_not_rule_order(self):
        source = 'https://example.com/rules/BanAD.list'
        first = provider_name(source, 'REJECT')
        self.assertEqual(first, provider_name(source, 'REJECT'))
        self.assertRegex(first, r'^leora-banad-[0-9a-f]{10}$')
        self.assertNotEqual(first, provider_name(source, 'PROXY'))
        self.assertNotEqual(first, provider_name('https://example.com/rules/Proxy.list', 'REJECT'))


class PolicyTests(unittest.TestCase):

    def test_conversion_report_timestamp_only_changes_with_content(self):
        from build_rules import stable_report
        previous = {'generated_utc': 't1', 'a': 1, 'providers': [{'id': 'x'}]}
        self.assertEqual(stable_report({'generated_utc': 't2', 'a': 1, 'providers': [{'id': 'x'}]}, previous)['generated_utc'], 't1')
        changed = stable_report({'generated_utc': 't2', 'a': 2, 'providers': [{'id': 'x'}]}, previous)
        self.assertEqual(changed['generated_utc'], 't2')
        self.assertEqual(stable_report({'generated_utc': 't3', 'a': 1}, None)['generated_utc'], 't3')
        # In-memory int ASN keys serialize to strings; they must not force a rebuild.
        self.assertEqual(stable_report({'generated_utc': 't2', 'asn_sources': {32934: 'u'}},
                                       {'generated_utc': 't1', 'asn_sources': {'32934': 'u'}})['generated_utc'], 't1')

    def setUp(self):
        self.m = {'proxies': [{'name': 'PROXY', 'type': 'socks5', 'server': '127.0.0.1', 'port': 9}]}
        self.mrules = {'rules': ['DOMAIN,ads.example,REJECT', 'DOMAIN,proxy.example,PROXY', 'DOMAIN-SUFFIX,example,DIRECT', 'MATCH,PROXY'], 'rule-providers': {}}
        self.x = {'outbounds': [{'tag': 'proxy', 'protocol': 'socks'}],
                  'routing': {'rules': [{'inboundTag': ['api'], 'outboundTag': 'api'}]}}
        self.xr = {'routing': {'rules': [
            {'type': 'field', 'domain': ['full:ads.example'], 'outboundTag': 'block'},
            {'type': 'field', 'domain': ['full:proxy.example'], 'outboundTag': 'proxy'},
            {'type': 'field', 'domain': ['domain:example'], 'outboundTag': 'direct'},
            {'type': 'field', 'network': 'tcp,udp', 'outboundTag': 'proxy'}]}}

    def test_mihomo_preserves_order_and_only_guards_proxy_matches(self):
        original = copy.deepcopy(self.m)
        result = merge_config(self.m, self.mrules)
        self.assertEqual(result['rules'][:2], [
            'DST-PORT,53,leora-dns-out', 'DST-PORT,853,REJECT'])
        self.assertEqual(result['rules'][2:], [
            'DOMAIN,ads.example,REJECT', 'DOMAIN,proxy.example,PROXY',
            'AND,((NETWORK,udp),(DOMAIN,proxy.example)),REJECT',
            'DOMAIN-SUFFIX,example,DIRECT', 'MATCH,PROXY', 'NETWORK,udp,REJECT'])
        self.assertTrue(result['tun']['enable'])
        self.assertEqual(original, self.m)
        self.assertEqual(protected_mihomo(result['rules']), result['rules'])

    def test_xray_preserves_all_rules_and_api(self):
        original = copy.deepcopy(self.x)
        result = merge_subscription([self.x], self.xr)[0]
        rules = result['routing']['rules']
        self.assertEqual(rules[0]['inboundTag'], ['api'])
        self.assertEqual(rules[-len(self.xr['routing']['rules']):], self.xr['routing']['rules'])
        self.assertEqual(self.x, original)
        self.assertEqual(result['dns'], xray_dns())

    def test_generated_sources_and_inline_rules_match_shadowrocket(self):
        import hashlib
        source = (ROOT / 'Leora-ProxyRules.conf').read_text(encoding='utf-8')
        entries = [l.strip() for l in source.split('[Rule]',1)[1].split('[Host]',1)[0].splitlines()
                   if l.strip() and not l.lstrip().startswith('#')]
        remote = [l.split(',') for l in entries if l.startswith(('RULE-SET,','DOMAIN-SET,'))]
        report = json.loads((ROOT/'conversion-report.json').read_text(encoding='utf-8'))
        self.assertEqual([(r['source'],r['action']) for r in report['providers']],
                         [(r[1],r[2]) for r in remote])
        self.assertGreater(len(remote), 40)
        self.assertEqual(report['source_sha256'], hashlib.sha256(source.encode()).hexdigest())
        m = yaml.safe_load((ROOT/'Leora-Clash-Routing.yaml').read_text(encoding='utf-8'))
        x = json.loads((ROOT/'Leora-Xray-Routing.json').read_text(encoding='utf-8'))['routing']['rules']
        last_m = -1
        last_x = -1
        for i, line in enumerate(entries):
            parts = line.split(',')
            if parts[0] in ('RULE-SET','DOMAIN-SET'):
                rid = provider_name(parts[1], parts[2])
                indexes = [j for j,r in enumerate(m['rules']) if r.startswith('RULE-SET,'+rid+',') or r.startswith('RULE-SET,'+rid+'-remote-')]
                xi = [j for j,r in enumerate(x) if r.get('ruleTag')==rid]
                self.assertTrue(indexes, line)
                self.assertTrue(xi, line)
            elif parts[0] == 'FINAL':
                indexes = [m['rules'].index('MATCH,'+parts[1])]
                xi = [j for j,r in enumerate(x) if r.get('ruleTag')=='final-proxy']
            else:
                indexes = [m['rules'].index(line, last_m + 1)]
                xi = [j for j,r in enumerate(x) if r.get('ruleTag')==f'inline-{i:02d}']
                if line in XRAY_SKIP_INLINE:
                    # Shadowrocket/Clash-only guard: Xray keeps domain proxy rules instead.
                    self.assertEqual(xi, [], line)
                    self.assertGreater(min(indexes), last_m, line)
                    last_m = max(indexes)
                    continue
            action = parts[1] if parts[0]=='FINAL' else parts[2]
            for j in xi:
                self.assertEqual(x[j]['outboundTag'], {'DIRECT':'direct','PROXY':'proxy','REJECT':'block'}[action])
            self.assertGreater(min(indexes), last_m, line)
            self.assertGreater(min(xi), last_x, line)
            last_m, last_x = max(indexes), max(xi)

    def test_domestic_geoip_fallback_stays_after_proxy_and_keeps_dot_guard_global(self):
        m = yaml.safe_load((ROOT / 'Leora-Clash-Routing.yaml').read_text(encoding='utf-8'))
        x = json.loads((ROOT / 'Leora-Xray-Routing.json').read_text(encoding='utf-8'))['routing']['rules']
        rules = m['rules']
        geo = rules.index('GEOIP,CN,DIRECT')
        self.assertEqual(rules[-3:], ['GEOIP,CN,DIRECT', 'MATCH,PROXY', 'NETWORK,udp,REJECT'])
        self.assertTrue(all(not rule.endswith(',PROXY') for rule in rules[geo + 1:-2]))
        china = rules.index('DOMAIN-SUFFIX,tonhie.online,DIRECT')
        self.assertLess(rules.index('DST-PORT,853,REJECT'), china)
        self.assertLess(rules.index('DST-PORT,853,REJECT'), geo)
        xray_geo = next(i for i, r in enumerate(x) if r.get('ip') == ['geoip:cn'])
        xray_final = next(i for i, r in enumerate(x) if r.get('ruleTag') == 'final-proxy')
        xray_dot = next(i for i, r in enumerate(x) if r.get('ruleTag') == 'external-dot-deny')
        self.assertLess(xray_dot, xray_geo)
        self.assertLess(xray_geo, xray_final)

    def test_shadowrocket_steam_overrides_precede_china_and_steam_proxy_list(self):
        text = (ROOT / 'Leora-ProxyRules.conf').read_text(encoding='utf-8')
        china = text.index('China/China.list,DIRECT')
        for domain in STEAM_DOWNLOADS:
            self.assertLess(text.index('DOMAIN,' + domain + ',DIRECT'), china)
        for domain in STEAM_PROXY:
            self.assertLess(text.index('DOMAIN-SUFFIX,' + domain + ',PROXY'), china)
        self.assertLess(text.index('DOMAIN-SUFFIX,steamcontent.com,DIRECT'), china)
        self.assertIn('Steam/Steam.list,PROXY', text)
        self.assertNotIn('Steam/Steam.list,DIRECT', text)
        self.assertNotIn('SteamCN/SteamCN.list,DIRECT', text)
        self.assertNotIn('stun-response-ip', text)
        self.assertIn('udp-policy-not-supported-behaviour = REJECT', text)

    def test_tongji_course_intranet_domain_is_direct_in_every_profile(self):
        # vesper-center.gardilily.com is a Tongji course-lab service on the campus
        # network (private 10.60.150.234). Proxied nodes cannot reach it, so it
        # must stay in the leading local/campus DIRECT block of all profiles.
        rule = 'DOMAIN-SUFFIX,gardilily.com,DIRECT'
        source = (ROOT / 'Leora-ProxyRules.conf').read_text(encoding='utf-8')
        self.assertIn(rule, source)
        self.assertLess(source.index('DOMAIN-SUFFIX,tongji.edu.cn,DIRECT'), source.index(rule))
        self.assertLess(source.index(rule), source.index('RULE-SET,'))
        self.assertLess(source.index(rule), source.index('FINAL,PROXY'))

        m = yaml.safe_load((ROOT / 'Leora-Clash-Routing.yaml').read_text(encoding='utf-8'))
        rules = m['rules']
        index = rules.index(rule)
        first_proxy = next(i for i, r in enumerate(rules) if r.endswith(',PROXY'))
        self.assertLess(index, first_proxy)
        # DIRECT rules carry no adjacent UDP reject; only PROXY matches get one.
        self.assertFalse(rules[index + 1].startswith('AND,((NETWORK,udp)'))

        x = json.loads((ROOT / 'Leora-Xray-Routing.json').read_text(encoding='utf-8'))['routing']['rules']
        direct = next(i for i, r in enumerate(x) if r.get('domain') == ['domain:gardilily.com'])
        self.assertEqual(x[direct]['outboundTag'], 'direct')
        first_xray_proxy = next(i for i, r in enumerate(x)
                                if r.get('outboundTag') == 'proxy'
                                and str(r.get('ruleTag', '')).startswith('inline-'))
        self.assertLess(direct, first_xray_proxy)

    def test_published_entries_are_already_protected(self):
        m = yaml.safe_load((ROOT / 'Leora-Clash-Routing.yaml').read_text(encoding='utf-8'))
        x = json.loads((ROOT / 'Leora-Xray-Routing.json').read_text(encoding='utf-8'))
        self.assertTrue(m['tun']['enable'])
        self.assertEqual(protected_mihomo(m['rules']), m['rules'])
        self.assertEqual(protected_xray(x['routing']['rules']), x['routing']['rules'])
        self.assertEqual(merge_config(self.m, m)['rules'], m['rules'])
        self.assertEqual(merge_subscription(self.x, x)['routing']['rules'][1:], x['routing']['rules'])

    def test_no_unprotected_entry_or_duplicate_template_is_published(self):
        for name in ('Leora-Mihomo-WebRTC.yaml', 'Leora-Xray-WebRTC.json',
                     'Leora-Clash-DNS.yaml', 'Leora-Shadowrocket-Rules.conf', 'source/Leora-ProxyRules.conf'):
            self.assertFalse((ROOT / name).exists(), name)

    def test_custom_proxy_names_and_balancer_are_remapped(self):
        self.m['proxies'][0]['name'] = 'NODE'
        result = merge_config(self.m, self.mrules, 'NODE')
        self.assertIn('DOMAIN,proxy.example,NODE', result['rules'])
        self.assertTrue(result['dns']['nameserver'][0].endswith('#NODE'))
        self.x['routing']['balancers'] = [{'tag': 'pool', 'selector': ['proxy']}]
        result = merge_subscription(self.x, self.xr, proxy_balancer='pool')
        self.assertEqual(next(r for r in result['routing']['rules'] if r.get('balancerTag'))['balancerTag'], 'pool')

    def test_direct_proxy_group_and_dynamic_members_are_rejected(self):
        for group in ({'proxies': ['DIRECT']}, {'use': ['sub']}, {'proxies': ['GROUP']}):
            with self.subTest(group=group):
                p = dict(self.m, **{'proxy-groups': [dict(name='GROUP', type='select', **group)]})
                with self.assertRaises(ValueError):merge_config(p, self.mrules, 'GROUP')

    def test_direct_outbound_or_balancer_fallback_is_rejected(self):
        self.x['outbounds'].append({'tag': 'direct-node', 'protocol': 'freedom'})
        with self.assertRaises(ValueError):merge_subscription(self.x, self.xr, 'direct-node')
        self.x['routing']['balancers'] = [{'tag': 'pool', 'selector': ['proxy'], 'fallbackTag': 'direct-node'}]
        with self.assertRaises(ValueError):merge_subscription(self.x, self.xr, proxy_balancer='pool')

    def test_all_general_settings_are_accounted_for(self):
        from unittest.mock import patch
        from routing_policy import general, basic_settings_audit, mihomo_settings, bypass_rules, static_hosts
        policy = general()
        self.assertEqual(set(basic_settings_audit()), set(policy))
        published = yaml.safe_load((ROOT / 'Leora-Clash-Routing.yaml').read_text(encoding='utf-8'))
        for key, value in mihomo_settings().items():
            self.assertEqual(published[key], value, key)
        report = json.loads((ROOT / 'conversion-report.json').read_text(encoding='utf-8'))
        self.assertEqual(report['general_settings'], basic_settings_audit())
        m = merge_config(dict(self.m, ipv6=False, hosts={'stale.example': '::1'}), self.mrules)
        self.assertTrue(m['ipv6'])
        self.assertTrue(m['dns']['ipv6'])
        self.assertIn('inet6-address', m['tun'])
        self.assertEqual(m['hosts'], static_hosts())
        self.assertEqual(m['tun']['route-exclude-address'], policy['tun-excluded-routes'].split(','))
        x = merge_subscription(self.x, self.xr)
        direct = next(o for o in x['outbounds'] if o['tag']=='direct')
        self.assertEqual(direct['settings']['domainStrategy'], 'UseIP')
        published_x = json.loads((ROOT / 'Leora-Xray-Routing.json').read_text(encoding='utf-8'))
        self.assertEqual(next(o for o in published_x['outbounds'] if o['tag']=='direct')['settings'], direct['settings'])
        with patch('routing_policy.general', return_value=dict(policy, ipv6='false')):
            self.assertFalse(mihomo_settings()['ipv6'])
            self.assertFalse(mihomo_settings()['dns']['ipv6'])
            self.assertNotIn('fake-ip-range6', mihomo_settings()['dns'])
            self.assertNotIn('inet6-address', mihomo_settings()['tun'])
        with patch('routing_policy.general', return_value=dict(policy, **{'skip-proxy':'new.example,*.test', 'tun-excluded-routes':'192.0.2.0/24'})):
            self.assertEqual(bypass_rules(), [('DOMAIN','new.example',False), ('DOMAIN-WILDCARD','*.test',False), ('IP-CIDR','192.0.2.0/24',True)])
        for change in ({'new-unknown-setting':'true'}, {'prefer-ipv6':'true'}, {'ipv6':'typo'}):
            with patch('routing_policy.general', return_value=dict(policy, **change)):
                with self.assertRaises(ValueError):
                    mihomo_settings()

    def test_dns_and_tailnet_are_synced_from_shadowrocket(self):
        from routing_policy import split_dns, TAILNET_RANGES, xray_dns
        policies = split_dns()
        m = merge_config(self.m, self.mrules)
        for domain, resolver in policies.items():
            self.assertEqual(m['dns']['nameserver-policy']['+.' + domain], 'udp://' + resolver + '#DIRECT')
            self.assertIn('+.' + domain, m['dns']['fake-ip-filter'])
        self.assertEqual(m['tun']['route-exclude-address'], __import__('routing_policy').excluded_routes())
        x = merge_subscription(self.x, self.xr)
        self.assertEqual(x['dns'], xray_dns())
        self.assertTrue(x['dns']['disableFallbackIfMatch'])
        for server in x['dns']['servers'][:-2]:
            self.assertTrue(server['skipFallback'])
            self.assertTrue(server['finalQuery'])
        tags = [r.get('ruleTag') for r in x['routing']['rules']]
        self.assertLess(tags.index('split-dns-direct'), tags.index('dns-intercept'))
        self.assertIn('100.64.0.0/10', TAILNET_RANGES)
        self.assertIn('fd7a:115c:a1e0::/48', TAILNET_RANGES)
        source=(ROOT/'Leora-ProxyRules.conf').read_text(encoding='utf-8')
        self.assertIn('100.64.0.0/10', source.split('tun-excluded-routes = ',1)[1].splitlines()[0])
        self.assertIn('IP-CIDR6,fd7a:115c:a1e0::/48,DIRECT,no-resolve', source)

    def test_proxy_hostname_bootstrap_is_specific_and_private_nodes_stay_private(self):
        self.x['outbounds'][0]['settings'] = {'servers': [
            {'address': 'node.example.com'}, {'address': 'NODE.TAIL.TS.NET.'}]}
        result = merge_subscription(self.x, self.xr)
        bootstrap = result['dns']['servers'][0]
        self.assertEqual(bootstrap['address'], 'https://223.5.5.5/dns-query')
        self.assertEqual(bootstrap['domains'], ['full:node.example.com'])
        self.assertTrue(bootstrap['skipFallback'])

    def test_reserved_dns_inbound_tag_cannot_be_user_traffic(self):
        self.x['inbounds'] = [{'tag': 'leora-dns', 'protocol': 'socks'}]
        with self.assertRaises(ValueError):merge_subscription(self.x, self.xr)

    def test_dns_is_encrypted_and_has_no_system_fallback(self):
        from routing_policy import public_dns, BOOTSTRAP_TAG
        m = merge_config(self.m, self.mrules)
        self.assertEqual(m['dns']['nameserver'], [u+'#PROXY' for u in public_dns()])
        self.assertEqual(m['dns']['default-nameserver'], ['https://223.5.5.5/dns-query'])
        self.assertTrue(m['dns']['direct-nameserver-follow-policy'])
        self.assertFalse(m['dns']['use-system-hosts'])
        self.assertTrue(m['dns']['ipv6'])
        self.assertEqual(m['dns']['fake-ip-range6'], 'fc00::/18')
        self.assertEqual(m['dns']['proxy-server-nameserver-policy'], m['dns']['nameserver-policy'])
        self.assertEqual(m['rules'][0], 'DST-PORT,53,leora-dns-out')
        self.assertIn({'name':'leora-dns-out','type':'dns'}, m['proxies'])
        x = merge_subscription(self.x, self.xr)
        rules = {r.get('ruleTag'):r for r in x['routing']['rules']}
        self.assertEqual(rules['public-dns-proxy']['outboundTag'],'proxy')
        self.assertEqual(rules['public-dns-proxy']['inboundTag'],['leora-dns'])
        self.assertEqual(set(rules['public-dns-proxy']['ip']), {'1.1.1.1','1.0.0.1'})
        self.assertEqual(rules['internal-dns-deny']['outboundTag'],'block')
        self.assertNotIn('223.5.5.5',rules['split-dns-direct']['ip'])
        self.assertEqual(x['dns']['queryStrategy'],'UseIP')
        self.x['inbounds'] = [{'tag': BOOTSTRAP_TAG}]
        with self.assertRaises(ValueError):merge_subscription(self.x,self.xr)

    def test_mainland_ipv6_prefixes_are_direct_in_every_generated_profile(self):
        source = (ROOT / 'Leora-ProxyRules.conf').read_text(encoding='utf-8')
        self.assertIn('ipv6 = true', source)
        self.assertIn('prefer-ipv6 = false', source)
        url = 'https://raw.githubusercontent.com/PaPerseller/chn-iplist/master/ruleset/ipv6-cidr6.list'
        self.assertIn('RULE-SET,' + url + ',DIRECT', source)
        self.assertLess(source.index('China/China_Domain.list,DIRECT'), source.index(url))
        self.assertLess(source.index(url), source.index('GEOIP,CN,DIRECT'))

        m = yaml.safe_load((ROOT / 'Leora-Clash-Routing.yaml').read_text(encoding='utf-8'))
        settings = __import__('routing_policy').mihomo_settings()
        self.assertTrue(m['ipv6'])
        self.assertTrue(m['dns']['ipv6'])
        self.assertIn('inet6-address', m['tun'])
        # Mihomo 1.19.32 fake-IP mode answers AAAA empty unless a v6 pool exists.
        self.assertEqual(m['dns']['fake-ip-range6'], 'fc00::/18')
        self.assertEqual(ipaddress.ip_network(m['dns']['fake-ip-range6']).version, 6)
        self.assertEqual(m['tun'], settings['tun'])
        rid, meta = next((name, provider) for name, provider in m['rule-providers'].items()
                         if provider['behavior'] == 'ipcidr')
        self.assertIn('ipv6', rid)
        self.assertEqual(meta['format'], 'yaml')
        rule = 'RULE-SET,' + rid + ',DIRECT'
        index = m['rules'].index(rule)
        self.assertLess(index, m['rules'].index('GEOIP,CN,DIRECT'))
        self.assertLess(m['rules'].index('RULE-SET,leora-china-domain-ea36d95cfc,DIRECT'), index)

        payload = yaml.safe_load((ROOT / 'providers' / (rid + '.yaml')).read_text(encoding='utf-8'))['payload']
        nets = [ipaddress.ip_network(value) for value in payload]
        self.assertGreater(len(nets), 1000)
        for net in nets:
            self.assertEqual(net.version, 6, net)
            self.assertFalse(net.is_private or net.is_loopback or net.is_link_local or
                             net.is_multicast or net.is_reserved or net.is_unspecified, net)
        self.assertNotIn(ipaddress.ip_network('::/0'), nets)

        x = json.loads((ROOT / 'Leora-Xray-Routing.json').read_text(encoding='utf-8'))
        xray = [r for r in x['routing']['rules'] if r.get('ruleTag') == rid]
        self.assertEqual(len(xray), 1)
        self.assertEqual(xray[0]['outboundTag'], 'direct')
        self.assertEqual(set(xray[0]['ip']), set(payload))
        geo = next(i for i, r in enumerate(x['routing']['rules']) if r.get('ip') == ['geoip:cn'])
        self.assertLess(x['routing']['rules'].index(xray[0]), geo)

    def test_foreign_ipv6_is_rejected_after_domestic_and_tailnet_ipv6(self):
        source = (ROOT / 'Leora-ProxyRules.conf').read_text(encoding='utf-8')
        guard = 'IP-CIDR6,2000::/3,REJECT,no-resolve'
        self.assertIn(guard, source)
        self.assertIn('fd7a:115c:a1e0::/48', source.split('tun-excluded-routes = ', 1)[1].splitlines()[0])

        m = yaml.safe_load((ROOT / 'Leora-Clash-Routing.yaml').read_text(encoding='utf-8'))
        rules = m['rules']
        index = rules.index(guard)
        self.assertLess(rules.index('RULE-SET,leora-ipv6-cidr6-79e2e3a54f,DIRECT'), index)
        self.assertLess(rules.index('IP-CIDR6,fd7a:115c:a1e0::/48,DIRECT,no-resolve'), index)
        self.assertLess(index, rules.index('GEOIP,CN,DIRECT'))
        self.assertIn('fd7a:115c:a1e0::/48', m['tun']['route-exclude-address'])

        x = json.loads((ROOT / 'Leora-Xray-Routing.json').read_text(encoding='utf-8'))
        self.assertFalse(any(guard.split(',')[1] in r.get('ip', []) for r in x['routing']['rules']))

    def test_direct_destinations_allow_stun_and_proxy_destinations_stay_closed(self):
        from routing_policy import split_dns
        m = yaml.safe_load((ROOT / 'Leora-Clash-Routing.yaml').read_text(encoding='utf-8'))
        x = json.loads((ROOT / 'Leora-Xray-Routing.json').read_text(encoding='utf-8'))['routing']['rules']
        rules = m['rules']
        self.assertNotIn('DST-PORT,3478/5349/19302-19309,REJECT', rules)
        self.assertFalse(any(rule.startswith('DOMAIN-REGEX,(^|[.-])(stun') for rule in rules))
        self.assertTrue(any(r.get('ruleTag') == 'external-dot-deny' for r in x))
        self.assertFalse(any(r.get('ruleTag') in ('stun-ports', 'stun-domain') for r in x))
        self.assertIn('DOMAIN-SUFFIX,tailscale.com,DIRECT', rules)
        self.assertIn('DOMAIN-SUFFIX,tailscale.io,DIRECT', rules)
        self.assertIn('IP-CIDR,111.187.0.0/16,DIRECT,no-resolve', rules)
        tailnet = rules.index('IP-CIDR,100.64.0.0/10,DIRECT,no-resolve')
        for domain in split_dns():
            self.assertLess(tailnet, rules.index('DOMAIN-SUFFIX,' + domain + ',DIRECT'))
        # Proxy destinations still get an adjacent UDP reject; direct domains do not.
        for index, rule in enumerate(rules):
            if rule.endswith(',PROXY'):
                self.assertTrue(rules[index + 1].startswith(('AND,((NETWORK,udp)', 'NETWORK,udp,REJECT')), rule)
        self.assertLess(rules.index('DST-PORT,853,REJECT'),
                        rules.index('DOMAIN-SUFFIX,tonhie.online,DIRECT'))

    def test_browser_templates_use_core_dns_and_restrict_webrtc(self):
        chrome=json.loads((ROOT/'browser/Chrome-policy.json').read_text(encoding='utf-8'))
        self.assertEqual(chrome['WebRtcIPHandling'],'disable_non_proxied_udp')
        self.assertEqual(chrome['DnsOverHttpsMode'],'off')
        firefox=(ROOT/'browser/Firefox-user.js').read_text(encoding='utf-8')
        self.assertIn('user_pref("media.peerconnection.enabled", false);',firefox)
        self.assertIn('user_pref("network.trr.mode", 5);',firefox)

    def test_custom_script_cannot_override_protection(self):
        self.xr['routing']['script'] = 'custom.lua'
        with self.assertRaises(ValueError):merge_subscription(self.x, self.xr)


if __name__ == '__main__':
    unittest.main()
