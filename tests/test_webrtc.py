import copy
import unittest
import json
from pathlib import Path
import yaml

from merge_xray import merge_subscription
from merge_mihomo import merge_config
from webrtc_guard import mihomo_rules, xray_rules


class GuardTests(unittest.TestCase):
    def test_mihomo_udp_has_immediate_reject_before_direct_rules(self):
        guard = mihomo_rules('udp', 'NODE')
        self.assertEqual(guard[:2], ['NETWORK,udp,NODE', 'NETWORK,udp,REJECT'])
        self.assertNotIn('DIRECT', '\n'.join(guard))

    def test_strict_covers_unknown_tcp_and_udp_ports(self):
        self.assertEqual(mihomo_rules('strict', 'NODE'),
                         ['NETWORK,udp,NODE', 'NETWORK,udp,REJECT', 'MATCH,NODE'])
        self.assertEqual(xray_rules('strict')[0]['network'], 'tcp,udp')

    def test_shipped_strict_presets_match_the_cli_policy(self):
        root = Path(__file__).resolve().parents[1]
        self.assertEqual(yaml.safe_load((root / 'Leora-Mihomo-WebRTC.yaml').read_text())['rules'],
                         mihomo_rules('strict'))
        self.assertEqual(json.loads((root / 'Leora-Xray-WebRTC.json').read_text())['routing']['rules'],
                         xray_rules('strict'))

    def test_proxy_name_cannot_inject_dns_parameters(self):
        with self.assertRaises(ValueError):
            mihomo_rules('udp', 'node&ecs=1.2.3.4/24')

    def test_invalid_mode_fails(self):
        with self.assertRaises(ValueError):
            mihomo_rules('typo', 'NODE')


class XrayTests(unittest.TestCase):
    def setUp(self):
        self.payload = {'outbounds': [{'tag': 'node', 'protocol': 'socks',
                                      'settings': {'servers': [{'address': '127.0.0.1', 'port': 9}]}}],
                        'dns': {'servers': ['localhost']},
                        'routing': {'rules': [
                            {'inboundTag': ['api'], 'outboundTag': 'api'},
                            {'network': 'tcp,udp', 'outboundTag': 'old'}]}}
        self.overlay = {'routing': {'domainStrategy': 'IPOnDemand', 'rules': [
            {'type': 'field', 'ip': ['1.0.0.0/8'], 'outboundTag': 'direct'},
            {'type': 'field', 'network': 'tcp,udp', 'outboundTag': 'proxy'}]}}

    def test_guard_precedes_direct_preserves_api_dns_input_and_array(self):
        before = copy.deepcopy(self.payload)
        out = merge_subscription([self.payload], self.overlay, 'node', webrtc='strict')[0]
        self.assertEqual(self.payload, before)
        rules = out['routing']['rules']
        self.assertEqual(rules[0]['inboundTag'], ['api'])
        self.assertEqual(rules[1]['network'], 'tcp,udp')
        self.assertEqual(rules[1]['outboundTag'], 'node')
        self.assertEqual(out['dns'], before['dns'])
        self.assertFalse(any(r.get('outboundTag') == 'old' for r in rules))

    def test_udp_guard_covers_arbitrary_ports_without_sniffing(self):
        out = merge_subscription(self.payload, self.overlay, 'node', webrtc='udp')
        rule = out['routing']['rules'][1]
        self.assertEqual(rule['network'], 'udp')
        self.assertNotIn('port', rule)
        self.assertNotIn('protocol', rule)

    def test_direct_proxy_target_and_balancer_fallback_are_rejected(self):
        self.payload['outbounds'][0]['protocol'] = 'freedom'
        with self.assertRaises(ValueError):
            merge_subscription(self.payload, self.overlay, 'node', webrtc='strict')
        self.payload['outbounds'].append({'tag': 'real', 'protocol': 'socks'})
        self.payload['routing']['balancers'] = [
            {'tag': 'pool', 'selector': ['real'], 'fallbackTag': 'node'}]
        with self.assertRaises(ValueError):
            merge_subscription(self.payload, self.overlay, proxy_balancer='pool', webrtc='udp')

    def test_balancer_prefix_cannot_include_direct_outbound(self):
        self.payload['outbounds'].append({'tag': 'node-direct', 'protocol': 'freedom'})
        self.payload['routing']['balancers'] = [{'tag': 'pool', 'selector': ['node']}]
        with self.assertRaises(ValueError):
            merge_subscription(self.payload, self.overlay, proxy_balancer='pool', webrtc='strict')

    def test_safe_balancer_is_remapped(self):
        self.payload['routing']['balancers'] = [{'tag': 'pool', 'selector': ['node']}]
        out = merge_subscription(self.payload, self.overlay, proxy_balancer='pool', webrtc='udp')
        rule = out['routing']['rules'][1]
        self.assertEqual(rule['balancerTag'], 'pool')
        self.assertNotIn('outboundTag', rule)

    def test_custom_routing_script_cannot_override_the_guard(self):
        self.overlay['routing']['script'] = 'custom-routing.lua'
        with self.assertRaises(ValueError):
            merge_subscription(self.payload, self.overlay, 'node', webrtc='strict')

    def test_default_keeps_original_overlay_behaviour(self):
        out = merge_subscription(self.payload, self.overlay, 'node')
        self.assertEqual(len(out['routing']['rules']), 3)


class MihomoTests(unittest.TestCase):
    def setUp(self):
        self.payload = {'proxies': [{'name': 'node', 'type': 'socks5',
                                    'server': '127.0.0.1', 'port': 9}],
                        'proxy-groups': [{'name': 'PROXY', 'type': 'select', 'proxies': ['node']}],
                        'rules': ['MATCH,DIRECT'],
                        'tun': {'route-exclude-address': ['0.0.0.0/0']}}
        self.routing = {'rule-providers': {}, 'rules': ['DOMAIN,example.com,DIRECT', 'MATCH,PROXY']}

    def test_merge_replaces_tun_exclusions_and_protects_before_direct(self):
        before = copy.deepcopy(self.payload)
        out = merge_config(self.payload, self.routing, mode='strict')
        self.assertEqual(self.payload, before)
        self.assertEqual(out['rules'][:3], mihomo_rules('strict', 'PROXY'))
        self.assertNotIn('route-exclude-address', out['tun'])
        self.assertTrue(out['tun']['enable'])
        self.assertTrue(out['ipv6'])
        self.assertTrue(out['tun']['inet6-address'])
        self.assertEqual(out['dns']['nameserver'][0], 'https://1.1.1.1/dns-query#PROXY')
        self.assertEqual(merge_config(out, self.routing, mode='strict'), out)

    def test_direct_group_member_and_provider_group_fail(self):
        for override in [{'proxies': ['node', 'DIRECT']}, {'use': ['subscription']},
                         {'filter': '^missing$'}]:
            with self.subTest(override=override):
                payload = copy.deepcopy(self.payload)
                payload['proxy-groups'][0].update(override)
                with self.assertRaises(ValueError):
                    merge_config(payload, self.routing)

    def test_custom_proxy_name_rewrites_routing_and_dns(self):
        out = merge_config(self.payload, self.routing, proxy_name='node', mode='udp')
        self.assertEqual(out['rules'][0], 'NETWORK,udp,node')
        self.assertEqual(out['rules'][-1], 'MATCH,node')
        self.assertTrue(out['dns']['nameserver'][0].endswith('#node'))

    def test_group_cycle_fails(self):
        self.payload['proxy-groups'][0]['proxies'] = ['PROXY']
        with self.assertRaises(ValueError):
            merge_config(self.payload, self.routing)


if __name__ == '__main__':
    unittest.main()
