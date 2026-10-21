import copy
import json
from pathlib import Path
import unittest
import yaml
from merge_mihomo import merge_config
from merge_xray import merge_subscription
from routing_policy import STEAM_DOWNLOADS, STEAM_PROXY, protected_mihomo, protected_xray, xray_dns

ROOT = Path(__file__).resolve().parents[1]


class PolicyTests(unittest.TestCase):
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
        self.assertEqual(result['rules'][4:], [
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
        source = (ROOT / 'Leora-ProxyRules.conf').read_text()
        entries = [l.strip() for l in source.split('[Rule]',1)[1].split('[Host]',1)[0].splitlines()
                   if l.strip() and not l.lstrip().startswith('#')]
        remote = [l.split(',') for l in entries if l.startswith(('RULE-SET,','DOMAIN-SET,'))]
        report = json.loads((ROOT/'conversion-report.json').read_text())
        self.assertEqual([(r['source'],r['action']) for r in report['providers']],
                         [(r[1],r[2]) for r in remote])
        self.assertGreater(len(remote), 40)
        self.assertEqual(report['source_sha256'], hashlib.sha256(source.encode()).hexdigest())
        m = yaml.safe_load((ROOT/'Leora-Clash-Routing.yaml').read_text())
        x = json.loads((ROOT/'Leora-Xray-Routing.json').read_text())['routing']['rules']
        last_m = -1
        last_x = -1
        for i, line in enumerate(entries):
            parts = line.split(',')
            if parts[0] in ('RULE-SET','DOMAIN-SET'):
                rid = f'leora-{i:02d}'
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
            action = parts[1] if parts[0]=='FINAL' else parts[2]
            for j in xi:
                self.assertEqual(x[j]['outboundTag'], {'DIRECT':'direct','PROXY':'proxy','REJECT':'block'}[action])
            self.assertGreater(min(indexes), last_m, line)
            self.assertGreater(min(xi), last_x, line)
            last_m, last_x = max(indexes), max(xi)

    def test_domestic_geoip_fallback_stays_after_proxy_and_keeps_guards_global(self):
        m = yaml.safe_load((ROOT / 'Leora-Clash-Routing.yaml').read_text())
        x = json.loads((ROOT / 'Leora-Xray-Routing.json').read_text())['routing']['rules']
        rules = m['rules']
        geo = rules.index('GEOIP,CN,DIRECT')
        self.assertEqual(rules[-3:], ['GEOIP,CN,DIRECT', 'MATCH,PROXY', 'NETWORK,udp,REJECT'])
        self.assertTrue(all(not rule.endswith(',PROXY') for rule in rules[geo + 1:-2]))
        guards = [
            'DST-PORT,3478/5349/19302-19309,REJECT',
            'DOMAIN-REGEX,(^|[.-])(stun[0-9]*|turn[0-9]*|turns)([.-]|$),REJECT',
            'DST-PORT,853,REJECT',
        ]
        china = rules.index('RULE-SET,leora-33-remote-0,DIRECT')
        for guard in guards:
            self.assertLess(rules.index(guard), china)
            self.assertLess(rules.index(guard), geo)
        xray_geo = next(i for i, r in enumerate(x) if r.get('ip') == ['geoip:cn'])
        xray_guards = [i for i, r in enumerate(x)
                       if r.get('ruleTag') in ('stun-ports', 'stun-domain', 'external-dot-deny')]
        xray_final = next(i for i, r in enumerate(x) if r.get('ruleTag') == 'final-proxy')
        self.assertEqual(len(xray_guards), 3)
        self.assertTrue(all(index < xray_geo for index in xray_guards))
        self.assertLess(xray_geo, xray_final)

    def test_shadowrocket_steam_overrides_precede_china_and_steam_proxy_list(self):
        text = (ROOT / 'Leora-ProxyRules.conf').read_text()
        china = text.index('China/China.list,DIRECT')
        for domain in STEAM_DOWNLOADS:
            self.assertLess(text.index('DOMAIN,' + domain + ',DIRECT'), china)
        for domain in STEAM_PROXY:
            self.assertLess(text.index('DOMAIN-SUFFIX,' + domain + ',PROXY'), china)
        self.assertLess(text.index('DOMAIN-SUFFIX,steamcontent.com,DIRECT'), china)
        self.assertIn('Steam/Steam.list,PROXY', text)
        self.assertNotIn('Steam/Steam.list,DIRECT', text)
        self.assertNotIn('SteamCN/SteamCN.list,DIRECT', text)
        self.assertIn('stun-response-ip = 127.0.0.1', text)
        self.assertIn('udp-policy-not-supported-behaviour = REJECT', text)

    def test_published_entries_are_already_protected(self):
        m = yaml.safe_load((ROOT / 'Leora-Clash-Routing.yaml').read_text())
        x = json.loads((ROOT / 'Leora-Xray-Routing.json').read_text())
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
        published = yaml.safe_load((ROOT / 'Leora-Clash-Routing.yaml').read_text())
        for key, value in mihomo_settings().items():
            self.assertEqual(published[key], value, key)
        report = json.loads((ROOT / 'conversion-report.json').read_text())
        self.assertEqual(report['general_settings'], basic_settings_audit())
        m = merge_config(dict(self.m, ipv6=True, hosts={'stale.example': '::1'}), self.mrules)
        self.assertFalse(m['ipv6'])
        self.assertFalse(m['dns']['ipv6'])
        self.assertNotIn('inet6-address', m['tun'])
        self.assertEqual(m['hosts'], static_hosts())
        self.assertEqual(m['tun']['route-exclude-address'], policy['tun-excluded-routes'].split(','))
        x = merge_subscription(self.x, self.xr)
        direct = next(o for o in x['outbounds'] if o['tag']=='direct')
        self.assertEqual(direct['settings']['domainStrategy'], 'ForceIPv4')
        published_x = json.loads((ROOT / 'Leora-Xray-Routing.json').read_text())
        self.assertEqual(next(o for o in published_x['outbounds'] if o['tag']=='direct')['settings'], direct['settings'])
        with patch('routing_policy.general', return_value=dict(policy, ipv6='true')):
            self.assertTrue(mihomo_settings()['ipv6'])
            self.assertTrue(mihomo_settings()['dns']['ipv6'])
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
        source=(ROOT/'Leora-ProxyRules.conf').read_text()
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
        self.assertFalse(m['dns']['ipv6'])
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
        self.assertEqual(x['dns']['queryStrategy'],'UseIPv4')
        self.x['inbounds'] = [{'tag': BOOTSTRAP_TAG}]
        with self.assertRaises(ValueError):merge_subscription(self.x,self.xr)

    def test_stun_and_dot_guards_precede_public_direct_and_preserve_local(self):
        from routing_policy import split_dns, STUN_PORTS, STUN_DOMAIN
        m=yaml.safe_load((ROOT/'Leora-Clash-Routing.yaml').read_text())
        x=json.loads((ROOT/'Leora-Xray-Routing.json').read_text())['routing']['rules']
        mi=m['rules'].index('DST-PORT,3478/5349/19302-19309,REJECT')
        xi=next(i for i,r in enumerate(x) if r.get('ruleTag')=='stun-ports')
        for d in split_dns():
            self.assertLess(m['rules'].index('DOMAIN-SUFFIX,'+d+',DIRECT'),mi)
            self.assertTrue(any('domain:'+d in r.get('domain',[]) for r in x[:xi]))
        self.assertLess(mi,m['rules'].index('DOMAIN-SUFFIX,tonhie.online,DIRECT'))
        self.assertLess(xi,next(i for i,r in enumerate(x) if 'domain:tonhie.online' in r.get('domain',[])))
        rule=x[xi]
        self.assertEqual(rule['port'],','.join(STUN_PORTS))
        self.assertEqual(rule['outboundTag'],'block')
        self.assertTrue(any(r.get('domain')==['regexp:'+STUN_DOMAIN] and r['outboundTag']=='block' for r in x))
        self.assertIn('DST-PORT,853,REJECT',m['rules'])
        self.assertTrue(any(r.get('port')=='853' and r.get('outboundTag')=='block' for r in x))

    def test_browser_templates_use_core_dns_and_restrict_webrtc(self):
        chrome=json.loads((ROOT/'browser/Chrome-policy.json').read_text())
        self.assertEqual(chrome['WebRtcIPHandling'],'disable_non_proxied_udp')
        self.assertEqual(chrome['DnsOverHttpsMode'],'off')
        firefox=(ROOT/'browser/Firefox-user.js').read_text()
        self.assertIn('user_pref("media.peerconnection.enabled", false);',firefox)
        self.assertIn('user_pref("network.trr.mode", 5);',firefox)

    def test_custom_script_cannot_override_protection(self):
        self.xr['routing']['script'] = 'custom.lua'
        with self.assertRaises(ValueError):merge_subscription(self.x, self.xr)


if __name__ == '__main__':
    unittest.main()
