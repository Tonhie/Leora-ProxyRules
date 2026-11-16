import hashlib
import json
import pathlib
import unittest

import yaml

from merge_mihomo import merge_config
from merge_xray import merge_subscription
from routing_policy import (FINAL_TARGET, FOREIGN_IPV6_GUARD_TAG, MODES, MODE_NAME,
                            conf_file, mode_file, report_file, routing_file,
                            script_file, xray_file, umbra_conf, validate_mode,
                            xray_ipv6_guard, protected_mihomo, protected_xray)

ROOT = pathlib.Path(__file__).resolve().parents[1]
IPV6_FAIL_CLOSED = 'IP-CIDR6,2000::/3,REJECT,no-resolve'


def read(name):
    return (ROOT / name).read_text(encoding='utf-8')


def load(mode):
    validate_mode(mode)
    return {
        'conf': read(conf_file(mode)),
        'routing': yaml.safe_load(read(routing_file(mode))),
        'xray': json.loads(read(xray_file(mode))),
        'report': json.loads(read(report_file(mode))),
    }


def conf_entries(text):
    return [line.strip() for line in
            text.split('[Rule]', 1)[1].split('[Host]', 1)[0].splitlines()
            if line.strip() and not line.lstrip().startswith('#')]


def section(text, name):
    return text.split('[' + name + ']', 1)[1].split('[', 1)[0].strip()


def xray_rules(mode):
    return load(mode)['xray']['routing']['rules']


class ModeFileTests(unittest.TestCase):
    def test_modes_have_distinct_names_and_profile_files_exist(self):
        self.assertEqual(MODES, ('leora', 'umbra'))
        self.assertEqual(MODE_NAME, {'leora': 'whitelist', 'umbra': 'blacklist'})
        for mode in MODES:
            for name in (conf_file(mode), routing_file(mode), script_file(mode),
                         xray_file(mode), report_file(mode)):
                self.assertTrue((ROOT / name).exists(), name)
        self.assertEqual(report_file('leora'), 'conversion-report.json')
        self.assertEqual(report_file('umbra'), 'Umbra-conversion-report.json')
        self.assertEqual(mode_file('umbra', 'X'), 'Umbra-X')

    def test_unknown_modes_are_rejected(self):
        for call in (lambda: validate_mode('night'), lambda: xray_ipv6_guard('night'),
                     lambda: mode_file('night', 'X')):
            with self.assertRaises(ValueError):
                call()


class OriginTests(unittest.TestCase):
    def test_umbra_conf_is_generated_from_the_canonical_leora_conf(self):
        self.assertEqual(read(conf_file('umbra')), umbra_conf(read(conf_file('leora'))))

    def test_umbra_conf_requires_exactly_one_canonical_final(self):
        with self.assertRaises(ValueError):
            umbra_conf('[General]\ndns-server = https://1.1.1.1/dns-query#proxy\n[Rule]\nMATCH,DIRECT\n')
        with self.assertRaises(ValueError):
            umbra_conf('[General]\ndns-server = https://1.1.1.1/dns-query#proxy\n[Rule]\nFINAL,PROXY\nFINAL,PROXY\n[Host]\n')

    def test_profiles_only_differ_in_the_final_default(self):
        leora = conf_entries(read(conf_file('leora')))
        umbra = conf_entries(read(conf_file('umbra')))
        self.assertEqual(leora[:-1], umbra[:-1])
        self.assertEqual(leora[-1], 'FINAL,PROXY')
        self.assertEqual(umbra[-1], 'FINAL,DIRECT')
        for entries in (leora, umbra):
            self.assertEqual(sum(line.startswith('FINAL,') for line in entries), 1)

    def test_general_and_host_sections_are_shared(self):
        leora, umbra = read(conf_file('leora')), read(conf_file('umbra'))
        for name in ('General', 'Host'):
            self.assertEqual(section(leora, name), section(umbra, name), name)


class ClashProfileTests(unittest.TestCase):
    def test_leora_is_the_original_whitelist_profile(self):
        routing = load('leora')['routing']
        self.assertEqual(routing['rules'][-2:], ['MATCH,PROXY', 'NETWORK,udp,REJECT'])
        self.assertIn(IPV6_FAIL_CLOSED, routing['rules'])
        x = xray_rules('leora')
        self.assertEqual(x[-1]['ruleTag'], 'final-proxy')
        self.assertEqual(x[-1]['outboundTag'], 'proxy')
        self.assertFalse(any(r.get('ruleTag') == FOREIGN_IPV6_GUARD_TAG for r in x))

    def test_umbra_is_the_blacklist_complement(self):
        routing = load('umbra')['routing']
        self.assertEqual(routing['rules'][-1], 'MATCH,DIRECT')
        self.assertNotIn('MATCH,PROXY', routing['rules'])
        # Unmatched UDP follows the DIRECT default instead of a blanket reject.
        self.assertNotIn('NETWORK,udp,REJECT', routing['rules'])
        self.assertIn(IPV6_FAIL_CLOSED, routing['rules'])

    def test_umbra_keeps_every_proxy_udp_guard(self):
        rules = load('umbra')['routing']['rules']
        for index, rule in enumerate(rules):
            parts = rule.split(',')
            position = -2 if parts[-1] == 'no-resolve' else -1
            if parts[position] != 'PROXY':
                continue
            condition = ','.join(parts[:position])
            guard = ('AND,((NETWORK,udp),(' + condition + ')),REJECT' +
                     (',no-resolve' if position == -2 else ''))
            self.assertEqual(rules[index + 1], guard, rule)

    def test_explicit_rules_are_identical_between_profiles(self):
        leora = load('leora')['routing']['rules']
        umbra = load('umbra')['routing']['rules']
        leora_middle = [r for r in leora if r not in ('MATCH,PROXY', 'NETWORK,udp,REJECT')]
        umbra_middle = [r for r in umbra if r != 'MATCH,DIRECT']
        self.assertEqual(leora_middle, umbra_middle)

    def test_umbra_xray_blocks_unknown_real_ipv6_before_the_direct_final(self):
        rules = xray_rules('umbra')
        guard = next(r for r in rules if r.get('ruleTag') == FOREIGN_IPV6_GUARD_TAG)
        self.assertEqual(guard['ip'], ['2000::/3'])
        self.assertEqual(guard['outboundTag'], 'block')
        self.assertEqual(guard['network'], 'tcp,udp')
        self.assertEqual(rules[-2], guard)
        self.assertEqual(rules[-1]['ruleTag'], 'final-direct')
        self.assertEqual(rules[-1]['outboundTag'], 'direct')
        # The guard must come after the explicit proxy rules so known proxy
        # destinations still proxy, and before the catch-all so nothing leaks.
        last_proxy = max(i for i, r in enumerate(rules) if r.get('outboundTag') == 'proxy')
        self.assertLess(last_proxy, rules.index(guard))

    def test_xray_ipv6_guard_is_mode_specific(self):
        self.assertEqual(xray_ipv6_guard('leora'), [])
        self.assertEqual(xray_ipv6_guard('umbra')[0]['ruleTag'], FOREIGN_IPV6_GUARD_TAG)
        self.assertFalse(any(r.get('ip') == ['2000::/3'] for r in xray_rules('leora')))

    def test_profiles_keep_dns_tun_and_ipv6_settings(self):
        leora = load('leora')['routing']
        umbra = load('umbra')['routing']
        for key in ('mode', 'ipv6', 'hosts', 'tun', 'dns'):
            self.assertEqual(leora[key], umbra[key], key)
        self.assertTrue(umbra['ipv6'])
        self.assertTrue(umbra['dns']['ipv6'])
        self.assertIn('inet6-address', umbra['tun'])

    def test_profiles_are_already_protected_and_idempotent(self):
        for mode in MODES:
            routing = load(mode)['routing']
            x = xray_rules(mode)
            self.assertEqual(protected_mihomo(routing['rules']), routing['rules'], mode)
            self.assertEqual(protected_xray(x, mode), x, mode)

    def test_rule_providers_are_shared_between_profiles(self):
        leora = load('leora')['routing']
        umbra = load('umbra')['routing']
        self.assertEqual(leora['rule-providers'], umbra['rule-providers'])
        for provider in umbra['rule-providers'].values():
            if '/providers/' in provider['url']:
                name = provider['url'].rsplit('/', 1)[1]
                self.assertTrue((ROOT / 'providers' / name).exists(), name)

    def test_reports_bind_to_their_own_config(self):
        reports = {mode: load(mode)['report'] for mode in MODES}
        for mode, report in reports.items():
            self.assertEqual(report['source_sha256'],
                             hashlib.sha256(read(conf_file(mode)).encode()).hexdigest(), mode)
            self.assertTrue(report['privacy']['browser_webrtc_restriction_required'])
        self.assertEqual(reports['leora']['base'], reports['umbra']['base'])
        self.assertEqual(reports['leora']['providers'], reports['umbra']['providers'])
        self.assertEqual(reports['leora']['general_settings'], reports['umbra']['general_settings'])
        self.assertNotIn('mode', reports['leora'])
        self.assertEqual(reports['umbra']['mode'], 'umbra')
        self.assertEqual(reports['umbra']['mode_name'], 'blacklist')
        self.assertEqual(reports['umbra']['final'], 'DIRECT')

    def test_merge_tools_accept_each_mode(self):
        proxy = {'proxies': [{'name': 'PROXY', 'type': 'socks5',
                              'server': '127.0.0.1', 'port': 9}]}
        for mode in MODES:
            routing = load(mode)['routing']
            self.assertEqual(merge_config(proxy, routing)['rules'], routing['rules'], mode)
            overlay = load(mode)['xray']
            result = merge_subscription(
                {'outbounds': [{'tag': 'proxy', 'protocol': 'socks',
                                'settings': {'servers': [{'address': '127.0.0.1', 'port': 9}]}}]},
                overlay, mode=mode)
            self.assertEqual(result['routing']['rules'], overlay['routing']['rules'], mode)
            if mode == 'umbra':
                self.assertEqual(result['routing']['rules'][-1]['outboundTag'], 'direct')
            else:
                self.assertEqual(result['routing']['rules'][-1]['outboundTag'], 'proxy')

    def test_umbra_xray_requires_a_direct_catch_all(self):
        overlay = [{'type': 'field', 'network': 'tcp,udp',
                    'outboundTag': 'proxy', 'ruleTag': 'final-proxy'}]
        with self.assertRaises(ValueError):
            protected_xray(overlay, 'umbra')


if __name__ == '__main__':
    unittest.main()
