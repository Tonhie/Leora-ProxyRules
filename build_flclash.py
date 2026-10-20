#!/usr/bin/env python3
"""Generate the FlClash Extend script from the canonical Clash routing."""
import argparse
import hashlib
import json
import pathlib

import yaml

from routing_policy import mihomo_dns_outbound, mihomo_settings, protected_mihomo

ROOT = pathlib.Path(__file__).resolve().parent
DEFAULT_ROUTING = ROOT / 'Leora-Clash-Routing.yaml'
DEFAULT_SCRIPT = ROOT / 'Leora-FlClash-Extend.js'

TEMPLATE = r"""/*
 * Leora Proxy Rules - FlClash Extend script.
 *
 * FlClash: Tools -> Advanced configuration -> Scripts -> import this file
 * (from URL or file), then Profile -> ... -> Extend -> Extend mode: Script.
 * The subscription's proxies, proxy groups and proxy-providers are kept; mode,
 * IPv6, hosts, DNS, TUN, rule-providers and rules are replaced by the canonical
 * Leora set. The rule target is the subscription's own proxy policy group.
 */

const ROUTING = @@ROUTING@@;

// Set to a concrete proxy or static proxy-group name to force the rule target.
// Leave empty to pick a valid policy group from the subscription automatically.
const OVERRIDE_TARGET = '';

const PREFERRED_TARGETS = [
  'PROXY',
  'Proxy',
  'proxy',
  '节点选择',
  '选择节点',
  '手动选择',
  '代理',
  '🚀 节点选择',
  '🌍 节点选择',
  '🚀 代理',
];

const SAFE_GROUP_TYPES = [
  'select',
  'url-test',
  'fallback',
  'load-balance',
  'relay',
];
const BUILT_IN_POLICIES = [
  'DIRECT',
  'REJECT',
  'REJECT-DROP',
  'PASS',
  'COMPATIBLE',
  'GLOBAL',
];
const DYNAMIC_KEYS = [
  'use',
  'include-all',
  'include-all-proxies',
  'include-all-groups',
  'filter',
  'exclude-filter',
  'exclude-type',
];

function clone(value) {
  return JSON.parse(JSON.stringify(value));
}

function validTarget(name) {
  return (
    typeof name === 'string' &&
    name.length > 0 &&
    name.indexOf(',') === -1 &&
    name.indexOf('#') === -1 &&
    name.indexOf('&') === -1 &&
    name.indexOf('\r') === -1 &&
    name.indexOf('\n') === -1
  );
}

function collect(config) {
  const proxies = Array.isArray(config.proxies) ? config.proxies : [];
  const groups = Array.isArray(config['proxy-groups'])
    ? config['proxy-groups']
    : [];
  const nodeNames = new Set();
  const blockedNames = new Set();
  const realProxies = [];
  for (const proxy of proxies) {
    if (!proxy || typeof proxy.name !== 'string' || !proxy.name) continue;
    const type = typeof proxy.type === 'string' ? proxy.type.toLowerCase() : '';
    if (
      type === 'direct' ||
      type === 'reject' ||
      type === 'dns' ||
      type === 'pass'
    ) {
      blockedNames.add(proxy.name);
      continue;
    }
    nodeNames.add(proxy.name);
    realProxies.push(proxy.name);
  }
  const groupMap = new Map();
  for (const group of groups) {
    if (group && typeof group.name === 'string' && group.name) {
      groupMap.set(group.name, group);
    }
  }
  return {nodeNames, blockedNames, realProxies, groupMap, groups};
}

// 'static' is a group that can be resolved to real proxy nodes through static
// members only. 'dynamic' additionally draws nodes from providers or filters,
// which never contain built-in policies, but cannot be checked statically.
function classifyGroup(name, state, visiting) {
  if (visiting.has(name)) return '';
  const group = state.groupMap.get(name);
  if (!group || SAFE_GROUP_TYPES.indexOf(String(group.type)) === -1) {
    return '';
  }
  const members = Array.isArray(group.proxies) ? group.proxies : [];
  let dynamic = false;
  for (const key of DYNAMIC_KEYS) {
    if (group[key]) dynamic = true;
  }
  if (dynamic) {
    if (group['include-all-groups']) return '';
    if (state.blockedNames.size > 0 &&
        (group['include-all'] || group['include-all-proxies'])) {
      return '';
    }
    const providerSource =
      group.use || group['include-all'] || group['include-all-proxies'];
    if (!providerSource) return '';
    for (const member of members) {
      if (!state.nodeNames.has(member)) return '';
    }
    return 'dynamic';
  }
  if (members.length === 0) return '';
  const next = new Set(visiting);
  next.add(name);
  for (const member of members) {
    if (BUILT_IN_POLICIES.indexOf(member) !== -1) return '';
    if (state.nodeNames.has(member)) continue;
    if (classifyGroup(member, state, next) !== 'static') return '';
  }
  return 'static';
}

function uniqueName(config, base) {
  const taken = new Set();
  for (const proxy of Array.isArray(config.proxies) ? config.proxies : []) {
    if (proxy && proxy.name) taken.add(proxy.name);
  }
  for (const group of Array.isArray(config['proxy-groups'])
    ? config['proxy-groups']
    : []) {
    if (group && group.name) taken.add(group.name);
  }
  let name = base;
  let index = 2;
  while (taken.has(name)) {
    name = base + ' ' + index;
    index += 1;
  }
  return name;
}

function resolveTarget(config) {
  const state = collect(config);
  if (OVERRIDE_TARGET) {
    if (!validTarget(OVERRIDE_TARGET)) {
      throw new Error('OVERRIDE_TARGET 含有规则目标不允许的字符');
    }
    if (
      state.nodeNames.has(OVERRIDE_TARGET) ||
      state.groupMap.has(OVERRIDE_TARGET)
    ) {
      return OVERRIDE_TARGET;
    }
    throw new Error('OVERRIDE_TARGET 不存在: ' + OVERRIDE_TARGET);
  }
  for (const candidate of PREFERRED_TARGETS) {
    if (!validTarget(candidate)) continue;
    if (state.nodeNames.has(candidate)) return candidate;
    if (classifyGroup(candidate, state, new Set()) === 'static') {
      return candidate;
    }
  }
  for (const group of state.groups) {
    if (
      validTarget(group.name) &&
      classifyGroup(group.name, state, new Set()) === 'static'
    ) {
      return group.name;
    }
  }
  for (const group of state.groups) {
    if (
      validTarget(group.name) &&
      classifyGroup(group.name, state, new Set()) === 'dynamic'
    ) {
      return group.name;
    }
  }
  if (state.realProxies.length > 0) {
    const name = uniqueName(config, 'Leora-Proxy');
    state.groups.push({name: name, type: 'select', proxies: state.realProxies.slice()});
    config['proxy-groups'] = state.groups;
    return name;
  }
  const providers = config['proxy-providers'];
  if (
    providers &&
    typeof providers === 'object' &&
    !Array.isArray(providers) &&
    Object.keys(providers).length > 0
  ) {
    const name = uniqueName(config, 'Leora-Proxy');
    state.groups.push({name: name, type: 'select', use: Object.keys(providers)});
    config['proxy-groups'] = state.groups;
    return name;
  }
  throw new Error('当前订阅没有可用代理节点，无法应用 Leora 规则');
}

function remapRule(rule, target) {
  const parts = String(rule).split(',');
  let index = parts.length - 1;
  if (parts[index] === 'no-resolve') index -= 1;
  if (parts[index] === 'PROXY') parts[index] = target;
  return parts.join(',');
}

function main(config) {
  if (!config || typeof config !== 'object' || Array.isArray(config)) {
    throw new Error('FlClash 扩展脚本需要配置对象');
  }
  const target = resolveTarget(config);
  const dnsProxy = ROUTING['dns-proxy'];
  const proxies = Array.isArray(config.proxies) ? config.proxies : [];
  for (const proxy of proxies) {
    if (proxy && proxy.name === dnsProxy.name && proxy.type !== 'dns') {
      throw new Error('与 Leora DNS 出站重名的代理: ' + dnsProxy.name);
    }
  }
  config.proxies = proxies
    .filter((proxy) => !proxy || proxy.name !== dnsProxy.name)
    .concat([clone(dnsProxy)]);

  const existingProviders =
    config['rule-providers'] &&
    typeof config['rule-providers'] === 'object' &&
    !Array.isArray(config['rule-providers'])
      ? config['rule-providers']
      : {};
  config['rule-providers'] = Object.assign(
    {},
    existingProviders,
    clone(ROUTING['rule-providers'])
  );
  config.rules = ROUTING.rules.map((rule) => remapRule(rule, target));
  config.mode = ROUTING.mode;
  config.ipv6 = ROUTING.ipv6;
  config.hosts = clone(ROUTING.hosts);
  config.tun = clone(ROUTING.tun);
  config.dns = clone(ROUTING.dns);
  if (Array.isArray(config.dns.nameserver)) {
    config.dns.nameserver = config.dns.nameserver.map((server) =>
      typeof server === 'string' && server.endsWith('#PROXY')
        ? server.slice(0, -'#PROXY'.length) + '#' + target
        : server
    );
  }
  console.log('[Leora] 规则代理目标: ' + target);
  return config;
}
"""


def build_script(routing):
    if not isinstance(routing, dict):
        raise ValueError('Expected a Mihomo routing object')
    rules = protected_mihomo(routing['rules'])
    settings = mihomo_settings()
    payload = {
        'mode': settings['mode'],
        'ipv6': settings['ipv6'],
        'hosts': settings['hosts'],
        'tun': settings['tun'],
        'dns': settings['dns'],
        'rule-providers': routing['rule-providers'],
        'rules': rules,
        'dns-proxy': mihomo_dns_outbound(),
    }
    digest = hashlib.sha256(
        yaml.safe_dump(routing, allow_unicode=True, sort_keys=False).encode()
    ).hexdigest()
    header = (
        ' * Generated by build_flclash.py from Leora-Clash-Routing.yaml; do not edit.\n'
        ' * Source: Leora-Clash-Routing.yaml (sha256 ' + digest + ').\n'
        ' * Regenerate with: python3 build_flclash.py\n'
    )
    script = TEMPLATE.replace('@@ROUTING@@', json.dumps(
        payload, ensure_ascii=False, indent=2))
    return script.replace(
        ' * Leora Proxy Rules - FlClash Extend script.\n',
        ' * Leora Proxy Rules - FlClash Extend script.\n' + header,
        1,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--routing', type=pathlib.Path, default=DEFAULT_ROUTING)
    parser.add_argument('--output', type=pathlib.Path, default=DEFAULT_SCRIPT)
    parser.add_argument('--check', action='store_true',
                        help='fail if the checked-in script differs from the canonical routing')
    args = parser.parse_args()
    routing = yaml.safe_load(args.routing.read_text(encoding='utf-8'))
    script = build_script(routing)
    if args.check:
        current = args.output.read_text(encoding='utf-8') if args.output.exists() else ''
        if current != script:
            parser.exit(1, f'{args.output} is stale; run python3 build_flclash.py\n')
        print(f'{args.output} is current')
        return
    args.output.write_text(script, encoding='utf-8')
    print(f'Wrote {args.output}')


if __name__ == '__main__':
    main()
