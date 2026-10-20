import copy
import json
from pathlib import Path
import unittest
import yaml
from merge_mihomo import merge_config
from merge_xray import merge_subscription
from routing_policy import STEAM_DOWNLOADS, STEAM_DOWNLOAD_SUFFIXES, STEAM_PROXY, mihomo_rules, xray_rules, mihomo_local_rules, xray_dns

ROOT = Path(__file__).resolve().parents[1]


class PolicyTests(unittest.TestCase):
    def setUp(self):
        self.m = {'proxies': [{'name': 'PROXY', 'type': 'socks5', 'server': '127.0.0.1', 'port': 9}]}
        self.mrules = {'rules': ['MATCH,DIRECT', 'DOMAIN,ads.example,REJECT'], 'rule-providers': {}}
        self.x = {'outbounds': [{'tag': 'proxy', 'protocol': 'socks'}],
                  'routing': {'rules': [{'inboundTag': ['api'], 'outboundTag': 'api'}]}}
        self.xr = {'routing': {'rules': [
            {'type': 'field', 'network': 'tcp,udp', 'outboundTag': 'direct'},
            {'type': 'field', 'domain': ['full:ads.example'], 'outboundTag': 'block'}]}}

    def test_mihomo_default_is_ads_then_protection_and_steam_then_proxy(self):
        original = copy.deepcopy(self.m)
        result = merge_config(self.m, self.mrules)
        offset = len(mihomo_local_rules())
        self.assertEqual(result['rules'][offset], 'DOMAIN,ads.example,REJECT')
        self.assertEqual(result['rules'][offset+1:offset+3], ['NETWORK,udp,PROXY', 'NETWORK,udp,REJECT'])
        self.assertEqual(result['rules'][-1], 'MATCH,PROXY')
        self.assertNotIn('MATCH,DIRECT', result['rules'])
        self.assertTrue(result['tun']['enable'])
        self.assertTrue(result['ipv6'])
        self.assertEqual(original, self.m)
        self.assertEqual(merge_config(result, self.mrules), result)

    def test_xray_protects_arrays_preserving_api_and_syncing_dns(self):
        self.x['dns'] = {'servers': ['localhost']}
        original = copy.deepcopy(self.x)
        result = merge_subscription([self.x], self.xr)[0]
        rules = result['routing']['rules']
        self.assertEqual(rules[0]['inboundTag'], ['api'])
        block = next(i for i,r in enumerate(rules) if r.get('outboundTag')=='block')
        udp = next(i for i,r in enumerate(rules) if r.get('ruleTag')=='udp-proxy')
        self.assertLess(block, udp)
        self.assertEqual(rules[-1]['outboundTag'], 'proxy')
        self.assertEqual(self.x, original)
        self.assertEqual(result['dns'], xray_dns())

    def test_steam_download_exception_has_transport_and_port_limits(self):
        rules = mihomo_rules()
        for domain in STEAM_DOWNLOADS:
            rule = f'AND,((NETWORK,tcp),(DST-PORT,80/443),(DOMAIN,{domain})),DIRECT'
            self.assertIn(rule, rules)
            self.assertGreater(rules.index(rule), rules.index('NETWORK,udp,REJECT'))
        direct = [r for r in xray_rules() if r.get('outboundTag') == 'direct']
        self.assertEqual(len(direct), 1)
        self.assertEqual(direct[0]['network'], 'tcp')
        self.assertEqual(direct[0]['port'], '80,443')
        self.assertEqual(set(direct[0]['domain']), {'full:' + d for d in STEAM_DOWNLOADS} | {'domain:' + d for d in STEAM_DOWNLOAD_SUFFIXES})
        self.assertIn('AND,((NETWORK,tcp),(DST-PORT,80/443),(DOMAIN-SUFFIX,steamcontent.com)),DIRECT', rules)
        self.assertNotIn('store.steampowered.com', STEAM_DOWNLOADS)
        self.assertNotIn('steamcontent.com', STEAM_DOWNLOADS)

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
        self.assertEqual(m['rules'][-len(mihomo_rules()):], mihomo_rules())
        self.assertEqual(x['routing']['rules'][-len(xray_rules()):], xray_rules())
        self.assertEqual(merge_config(self.m, m)['rules'], m['rules'])
        self.assertEqual(merge_subscription(self.x, x)['routing']['rules'][1:], x['routing']['rules'])

    def test_no_unprotected_entry_or_duplicate_template_is_published(self):
        for name in ('Leora-Mihomo-WebRTC.yaml', 'Leora-Xray-WebRTC.json',
                     'Leora-Clash-DNS.yaml', 'Leora-Shadowrocket-Rules.conf', 'source/Leora-ProxyRules.conf'):
            self.assertFalse((ROOT / name).exists(), name)

    def test_custom_proxy_names_and_balancer_are_remapped(self):
        self.m['proxies'][0]['name'] = 'NODE'
        result = merge_config(self.m, self.mrules, 'NODE')
        self.assertIn('NETWORK,udp,NODE', result['rules'])
        self.assertTrue(result['dns']['nameserver'][0].endswith('#NODE'))
        self.x['routing']['balancers'] = [{'tag': 'pool', 'selector': ['proxy']}]
        result = merge_subscription(self.x, self.xr, proxy_balancer='pool')
        self.assertEqual(next(r for r in result['routing']['rules'] if r.get('ruleTag')=='udp-proxy')['balancerTag'], 'pool')

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

    def test_dns_and_tailnet_are_synced_from_shadowrocket(self):
        from routing_policy import split_dns, TAILNET_RANGES, xray_dns
        policies = split_dns()
        m = merge_config(self.m, self.mrules)
        for domain, resolver in policies.items():
            self.assertEqual(m['dns']['nameserver-policy']['+.' + domain], 'udp://' + resolver + '#DIRECT')
            self.assertIn('+.' + domain, m['dns']['fake-ip-filter'])
        self.assertEqual(m['tun']['route-exclude-address'], list(TAILNET_RANGES))
        x = merge_subscription(self.x, self.xr)
        self.assertEqual(x['dns'], xray_dns())
        self.assertTrue(x['dns']['disableFallbackIfMatch'])
        for server in x['dns']['servers'][:-2]:
            self.assertTrue(server['skipFallback'])
            self.assertTrue(server['finalQuery'])
        tags = [r.get('ruleTag') for r in x['routing']['rules']]
        self.assertLess(tags.index('split-domain-direct'), tags.index('udp-proxy'))
        self.assertLess(tags.index('split-dns-direct'), tags.index('dns-intercept'))
        self.assertIn('100.64.0.0/10', TAILNET_RANGES)
        self.assertIn('fd7a:115c:a1e0::/48', TAILNET_RANGES)
        source=(ROOT/'Leora-ProxyRules.conf').read_text()
        self.assertIn('100.64.0.0/10', source.split('tun-excluded-routes = ',1)[1].splitlines()[0])
        self.assertIn('IP-CIDR6,fd7a:115c:a1e0::/48,DIRECT,no-resolve', source)
        self.assertLess(tags.index('tailnet-ip'), tags.index('dns-intercept'))

    def test_proxy_hostname_bootstrap_is_specific_and_private_nodes_stay_private(self):
        self.x['outbounds'][0]['settings'] = {'servers': [
            {'address': 'node.example.com'}, {'address': 'NODE.TAIL.TS.NET.'}]}
        result = merge_subscription(self.x, self.xr)
        bootstrap = result['dns']['servers'][0]
        self.assertEqual(bootstrap['address'], '223.5.5.5')
        self.assertEqual(bootstrap['domains'], ['full:node.example.com'])
        self.assertTrue(bootstrap['skipFallback'])

    def test_reserved_dns_inbound_tag_cannot_be_user_traffic(self):
        self.x['inbounds'] = [{'tag': 'leora-dns', 'protocol': 'socks'}]
        with self.assertRaises(ValueError):merge_subscription(self.x, self.xr)

    def test_custom_script_cannot_override_protection(self):
        self.xr['routing']['script'] = 'custom.lua'
        with self.assertRaises(ValueError):merge_subscription(self.x, self.xr)


if __name__ == '__main__':
    unittest.main()
