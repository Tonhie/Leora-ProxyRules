import copy
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest

import yaml

import build_clash
from merge_mihomo import merge_config
from routing_policy import mihomo_settings, protected_mihomo

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'Leora-Clash-Extend.js'
NODE = shutil.which('node')


def node(name):
    return {
        'name': name,
        'type': 'ss',
        'server': 'edge.example',
        'port': 443,
        'cipher': 'aes-128-gcm',
        'password': 'secret',
        'udp': True,
    }


def subscription():
    return {
        'proxies': [node('🇭🇰 香港 01'), node('🇯🇵 日本 01')],
        'proxy-groups': [
            {'name': '🚀 节点选择', 'type': 'select',
             'proxies': ['♻️ 自动选择', '🇭🇰 香港 01', '🇯🇵 日本 01']},
            {'name': '♻️ 自动选择', 'type': 'url-test',
             'proxies': ['🇭🇰 香港 01', '🇯🇵 日本 01'],
             'url': 'http://www.gstatic.com/generate_204', 'interval': 300},
        ],
        'rules': ['MATCH,🚀 节点选择'],
        'rule-providers': {
            'airport': {'type': 'http', 'behavior': 'domain',
                        'url': 'https://example.com/rules.yaml',
                        'path': './ruleset/airport.yaml', 'interval': 86400},
        },
        'proxy-providers': {
            'airport': {'type': 'http', 'url': 'https://example.com/proxies.yaml',
                        'path': './proxy_providers/airport.yaml', 'interval': 86400},
        },
    }


def remap_rule(rule, target):
    parts = rule.split(',')
    index = -2 if parts[-1] == 'no-resolve' else -1
    if parts[index] == 'PROXY':
        parts[index] = target
    return ','.join(parts)


def run_script(config):
    if NODE is None:
        raise unittest.SkipTest('node is required to execute the Clash script')
    with tempfile.TemporaryDirectory() as temp:
        temp = pathlib.Path(temp)
        config_file = temp / 'config.json'
        config_file.write_text(json.dumps(config, ensure_ascii=False), encoding='utf-8')
        output_file = temp / 'result.json'
        harness = temp / 'run.js'
        harness.write_text(
            "const fs = require('fs');\n"
            "const source = fs.readFileSync(process.argv[2], 'utf8');\n"
            "const main = new Function(source + '\\nreturn main;')();\n"
            "const config = JSON.parse(fs.readFileSync(process.argv[3], 'utf8'));\n"
            "fs.writeFileSync(process.argv[4], JSON.stringify(main(config)));\n",
            encoding='utf-8',
        )
        completed = subprocess.run(
            [NODE, str(harness), str(SCRIPT), str(config_file), str(output_file)],
            capture_output=True, text=True, encoding='utf-8', timeout=60,
        )
        if completed.returncode != 0:
            raise AssertionError(completed.stderr or completed.stdout)
        return json.loads(output_file.read_text(encoding='utf-8'))


def eval_artifact(expression):
    if NODE is None:
        raise unittest.SkipTest('node is required to evaluate the Clash script')
    with tempfile.TemporaryDirectory() as temp:
        temp = pathlib.Path(temp)
        output_file = temp / 'value.json'
        harness = temp / 'eval.js'
        harness.write_text(
            "const fs = require('fs');\n"
            "const source = fs.readFileSync(process.argv[2], 'utf8');\n"
            "const value = new Function(source + '\\nreturn (' + process.argv[3] + ');')();\n"
            "fs.writeFileSync(process.argv[4], JSON.stringify(value));\n",
            encoding='utf-8',
        )
        completed = subprocess.run(
            [NODE, str(harness), str(SCRIPT), expression, str(output_file)],
            capture_output=True, text=True, encoding='utf-8', timeout=60,
        )
        if completed.returncode != 0:
            raise AssertionError(completed.stderr or completed.stdout)
        return json.loads(output_file.read_text(encoding='utf-8'))


class ArtifactTests(unittest.TestCase):
    def test_checked_in_script_is_generated_from_current_routing(self):
        routing = yaml.safe_load(
            (ROOT / 'Leora-Clash-Routing.yaml').read_text(encoding='utf-8'))
        self.assertEqual(build_clash.build_script(routing),
                         SCRIPT.read_text(encoding='utf-8'))

    def test_embedded_routing_equals_canonical_sources(self):
        routing = yaml.safe_load(
            (ROOT / 'Leora-Clash-Routing.yaml').read_text(encoding='utf-8'))
        embedded = eval_artifact('ROUTING')
        settings = mihomo_settings()
        self.assertEqual(embedded['mode'], settings['mode'])
        self.assertEqual(embedded['ipv6'], settings['ipv6'])
        self.assertEqual(embedded['hosts'], settings['hosts'])
        self.assertEqual(embedded['tun'], settings['tun'])
        self.assertEqual(embedded['dns'], settings['dns'])
        self.assertEqual(embedded['rule-providers'], routing['rule-providers'])
        self.assertEqual(embedded['rules'], protected_mihomo(routing['rules']))
        self.assertEqual(embedded['dns-proxy'],
                         {'name': 'leora-dns-out', 'type': 'dns'})

    def test_script_has_the_quickjs_entry_point_and_no_platform_apis(self):
        source = SCRIPT.read_text(encoding='utf-8')
        self.assertIn('function main(config)', source)
        for forbidden in ('require(', 'fetch(', 'XMLHttpRequest',
                          'setTimeout(', 'process.', 'node:'):
            self.assertNotIn(forbidden, source)
        self.assertNotRegex(source, r'(?m)^\s*import\s')


class CliTests(unittest.TestCase):
    def test_check_accepts_the_current_artifact(self):
        completed = subprocess.run(
            [sys.executable, str(ROOT / 'build_clash.py'), '--check'],
            cwd=ROOT, capture_output=True, text=True, encoding='utf-8',
            env={**os.environ, 'PYTHONUTF8': '1'}, timeout=60,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_check_rejects_a_missing_or_stale_output(self):
        with tempfile.TemporaryDirectory() as temp:
            temp = pathlib.Path(temp)
            missing = temp / 'missing.js'
            completed = subprocess.run(
                [sys.executable, str(ROOT / 'build_clash.py'), '--check',
                 '--output', str(missing)],
                cwd=ROOT, capture_output=True, text=True, encoding='utf-8',
                env={**os.environ, 'PYTHONUTF8': '1'}, timeout=60,
            )
            self.assertEqual(completed.returncode, 1)
            stale = temp / 'stale.js'
            stale.write_text(SCRIPT.read_text(encoding='utf-8') + '\n',
                             encoding='utf-8')
            completed = subprocess.run(
                [sys.executable, str(ROOT / 'build_clash.py'), '--check',
                 '--output', str(stale)],
                cwd=ROOT, capture_output=True, text=True, encoding='utf-8',
                env={**os.environ, 'PYTHONUTF8': '1'}, timeout=60,
            )
            self.assertEqual(completed.returncode, 1)


class ClashScriptTests(unittest.TestCase):
    def setUp(self):
        self.routing = yaml.safe_load(
            (ROOT / 'Leora-Clash-Routing.yaml').read_text(encoding='utf-8'))

    def test_output_equals_documented_merge_mihomo_result(self):
        payload = subscription()
        expected = merge_config(copy.deepcopy(payload), self.routing, '🚀 节点选择')
        actual = run_script(copy.deepcopy(payload))
        self.assertEqual(actual, expected)

    def test_rules_keep_order_udp_guards_and_exact_provider_entries(self):
        actual = run_script(subscription())
        rules = actual['rules']
        self.assertEqual(rules[0], 'DST-PORT,53,leora-dns-out')
        self.assertEqual(rules[-1], 'NETWORK,udp,REJECT')
        self.assertEqual(rules[-2], 'MATCH,🚀 节点选择')
        self.assertIn('AND,((NETWORK,udp),(DOMAIN-SUFFIX,browserleaks.com)),REJECT',
                      rules)
        self.assertNotIn(',PROXY', ','.join(rules))
        expected_providers = self.routing['rule-providers']
        for name, provider in expected_providers.items():
            self.assertEqual(actual['rule-providers'][name], provider, name)
        self.assertIn('airport', actual['rule-providers'])
        for server in actual['dns']['nameserver']:
            self.assertTrue(server.endswith('#🚀 节点选择'), server)
        self.assertNotIn('#PROXY', ''.join(actual['dns']['nameserver']))

    def test_target_prefers_named_proxy_group_and_keeps_subscription(self):
        payload = subscription()
        payload['proxy-groups'].insert(0, {
            'name': 'PROXY', 'type': 'select',
            'proxies': ['🇭🇰 香港 01', '🇯🇵 日本 01'],
        })
        actual = run_script(payload)
        self.assertEqual(actual['rules'][-2], 'MATCH,PROXY')
        self.assertEqual(actual['dns']['nameserver'][0],
                         'https://1.1.1.1/dns-query#PROXY')
        self.assertEqual(actual['proxies'][-1], {'name': 'leora-dns-out', 'type': 'dns'})
        self.assertEqual(actual['proxy-providers'],
                         subscription()['proxy-providers'])

    def test_group_containing_direct_is_never_a_target(self):
        payload = subscription()
        payload['proxy-groups'] = [
            {'name': '直连组', 'type': 'select', 'proxies': ['DIRECT']},
            {'name': '安全组', 'type': 'select', 'proxies': ['🇭🇰 香港 01']},
        ]
        actual = run_script(payload)
        self.assertEqual(actual['rules'][-2], 'MATCH,安全组')

    def test_node_only_profile_gets_a_selector_group(self):
        payload = {'proxies': [node('节点 A'), node('节点 B')], 'rules': ['MATCH,DIRECT']}
        actual = run_script(payload)
        group = next(g for g in actual['proxy-groups'] if g['name'] == 'Leora-Proxy')
        self.assertEqual(group['type'], 'select')
        self.assertEqual(group['proxies'], ['节点 A', '节点 B'])
        self.assertEqual(actual['rules'][-2], 'MATCH,Leora-Proxy')
        self.assertEqual(actual['dns']['nameserver'][0],
                         'https://1.1.1.1/dns-query#Leora-Proxy')
        self.assertEqual(run_script(copy.deepcopy(actual)), actual)

    def test_provider_only_profile_uses_provider_group(self):
        payload = {
            'proxies': [],
            'proxy-groups': [{'name': '机场节点', 'type': 'select', 'use': ['airport']}],
            'proxy-providers': subscription()['proxy-providers'],
        }
        actual = run_script(payload)
        self.assertEqual(actual['rules'][-2], 'MATCH,机场节点')
        self.assertEqual(actual['proxy-groups'],
                         [{'name': '机场节点', 'type': 'select', 'use': ['airport']}])

    def test_include_all_group_cannot_pick_up_a_direct_type_proxy(self):
        payload = {
            'proxies': [node('节点 A'),
                        {'name': '伪直连', 'type': 'direct'}],
            'proxy-groups': [{'name': '全部节点', 'type': 'select',
                              'include-all-proxies': True}],
            'rules': [],
        }
        actual = run_script(payload)
        self.assertEqual(actual['rules'][-2], 'MATCH,Leora-Proxy')
        group = next(g for g in actual['proxy-groups'] if g['name'] == 'Leora-Proxy')
        self.assertEqual(group['proxies'], ['节点 A'])

    def test_empty_profile_raises_an_explicit_error(self):
        with self.assertRaises(AssertionError) as caught:
            run_script({'proxies': [], 'proxy-groups': [], 'rules': []})
        self.assertIn('没有可用代理节点', str(caught.exception))

    def test_dns_proxy_name_collision_is_rejected(self):
        payload = subscription()
        payload['proxies'].append({'name': 'leora-dns-out', 'type': 'ss',
                                   'server': 'x.example', 'port': 1})
        with self.assertRaises(AssertionError) as caught:
            run_script(payload)
        self.assertIn('leora-dns-out', str(caught.exception))

    def test_applying_twice_is_idempotent(self):
        once = run_script(subscription())
        twice = run_script(copy.deepcopy(once))
        self.assertEqual(twice, once)

    def test_provider_only_without_a_group_creates_a_provider_group(self):
        payload = {
            'proxies': [],
            'proxy-providers': {
                'a': {'type': 'http', 'url': 'https://example.com/a.yaml'},
                'b': {'type': 'http', 'url': 'https://example.com/b.yaml'},
            },
        }
        actual = run_script(payload)
        group = next(g for g in actual['proxy-groups'] if g['name'] == 'Leora-Proxy')
        self.assertEqual(group, {'name': 'Leora-Proxy', 'type': 'select',
                                 'use': ['a', 'b']})
        self.assertEqual(actual['rules'][-2], 'MATCH,Leora-Proxy')
        self.assertEqual(run_script(copy.deepcopy(actual)), actual)

    def test_same_name_rule_provider_is_replaced_by_the_canonical_one(self):
        payload = subscription()
        payload['rule-providers']['leora-09'] = {
            'type': 'http', 'behavior': 'domain', 'url': 'https://evil.example/x.yaml',
            'path': './x.yaml', 'interval': 60,
        }
        actual = run_script(payload)
        self.assertEqual(actual['rule-providers']['leora-09'],
                         self.routing['rule-providers']['leora-09'])
        self.assertIn('airport', actual['rule-providers'])

    def test_existing_dns_typed_leora_out_is_deduplicated(self):
        payload = subscription()
        payload['proxies'].append({'name': 'leora-dns-out', 'type': 'dns'})
        actual = run_script(payload)
        dns_out = [p for p in actual['proxies'] if p['name'] == 'leora-dns-out']
        self.assertEqual(dns_out, [{'name': 'leora-dns-out', 'type': 'dns'}])
        self.assertEqual(actual['proxies'][-1], dns_out[0])

    def test_unknown_top_level_keys_are_preserved(self):
        payload = subscription()
        payload['port'] = 1234
        payload['allow-lan'] = True
        payload['custom-key'] = {'keep': [1, 2, 3]}
        actual = run_script(payload)
        self.assertEqual(actual['port'], 1234)
        self.assertTrue(actual['allow-lan'])
        self.assertEqual(actual['custom-key'], {'keep': [1, 2, 3]})

    def test_rules_are_the_complete_protected_sequence_with_all_udp_guards(self):
        target = '🚀 节点选择'
        payload = subscription()
        actual = run_script(payload)
        rules = actual['rules']
        expected = [remap_rule(rule, target) for rule in self.routing['rules']]
        self.assertEqual(rules, expected)
        self.assertEqual(rules.count('DST-PORT,53,leora-dns-out'), 1)
        for guard in ('DST-PORT,3478/5349/19302-19309,REJECT',
                      'DOMAIN-REGEX,(^|[.-])(stun[0-9]*|turn[0-9]*|turns)([.-]|$),REJECT',
                      'DST-PORT,853,REJECT'):
            self.assertEqual(rules.count(guard), 1)
        for index, rule in enumerate(rules):
            parts = rule.split(',')
            position = -2 if parts[-1] == 'no-resolve' else -1
            if parts[position] != target:
                continue
            condition = ','.join(parts[:position])
            guard = ('NETWORK,udp,REJECT' if condition == 'MATCH' else
                     'AND,((NETWORK,udp),(' + condition + ')),REJECT' +
                     (',no-resolve' if position == -2 else ''))
            self.assertEqual(rules[index + 1], guard, rule)

    def test_node_named_proxy_matches_merge_mihomo(self):
        payload = {'proxies': [node('PROXY')], 'rules': ['MATCH,DIRECT']}
        expected = merge_config(copy.deepcopy(payload), self.routing, 'PROXY')
        actual = run_script(copy.deepcopy(payload))
        self.assertEqual(actual, expected)

    def test_documented_clash_settings_keep_canonical_fields(self):
        target = '🚀 节点选择'
        actual = run_script(subscription())
        # Clash overwrites these after the script; a user matching the
        # documented settings (rule mode, IPv6 off, TUN mixed, bypass private
        # off) gets the canonical rules, DNS and hosts. Clash's real default
        # bypassPrivateRoute=true would append private ranges, which is why the
        # checklist requires turning it off.
        final = copy.deepcopy(actual)
        final['mode'] = 'rule'
        final['ipv6'] = False
        final['tun'].update({
            'enable': True,
            'device': 'Clash',
            'stack': 'mixed',
            'auto-route': True,
            'dns-hijack': ['any:53'],
            'auto-detect-interface': True,
        })
        settings = mihomo_settings()
        expected_dns = copy.deepcopy(settings['dns'])
        expected_dns['nameserver'] = [
            server.rsplit('#', 1)[0] + '#' + target
            for server in expected_dns['nameserver']
        ]
        expected_providers = copy.deepcopy(subscription()['rule-providers'])
        expected_providers.update(self.routing['rule-providers'])
        self.assertEqual(final['rules'],
                         [remap_rule(rule, target) for rule in self.routing['rules']])
        self.assertEqual(final['dns'], expected_dns)
        self.assertEqual(final['hosts'], settings['hosts'])
        self.assertEqual(final['rule-providers'], expected_providers)
        self.assertTrue(final['tun']['strict-route'])
        self.assertEqual(final['tun']['route-exclude-address'],
                         self.routing['tun']['route-exclude-address'])
        self.assertEqual(final['mode'], 'rule')
        self.assertFalse(final['ipv6'])


if __name__ == '__main__':
    unittest.main()
