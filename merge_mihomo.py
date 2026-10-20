#!/usr/bin/env python3
"""Merge Leora routing with an opt-in WebRTC guard into a complete Mihomo YAML."""
import argparse
import copy
import pathlib
import yaml
from webrtc_guard import MODES, mihomo_rules, validate_mihomo_proxy

ROOT = pathlib.Path(__file__).resolve().parent


def merge_config(payload, routing, proxy_name='PROXY', mode='udp'):
    if not isinstance(payload, dict) or not isinstance(routing, dict):
        raise ValueError('Expected Mihomo YAML objects')
    validate_mihomo_proxy(payload, proxy_name)
    guard = mihomo_rules(mode, proxy_name)
    result = copy.deepcopy(payload)
    # Replace TUN settings: inherited include/exclude filters could silently
    # bypass capture. Client-managed VPN/TUN still needs its own verification.
    preset = yaml.safe_load((ROOT / 'Leora-Mihomo-WebRTC.yaml').read_text())
    for key in ('tun', 'dns', 'ipv6', 'mode'):
        result[key] = copy.deepcopy(preset[key])
    result['dns']['nameserver'] = [u.replace('#PROXY', '#' + proxy_name)
                                     for u in result['dns']['nameserver']]
    providers = result.setdefault('rule-providers', {})
    providers.update(copy.deepcopy(routing.get('rule-providers', {})))
    # Leora uses PROXY as its public proxy policy. Preserve DIRECT and REJECT.
    rules = []
    rejections = []
    for rule in routing['rules']:
        parts = rule.split(',')
        policy_index = -2 if parts[-1] == 'no-resolve' else -1
        if parts[policy_index] == 'PROXY':
            parts[policy_index] = proxy_name
        destination = rejections if parts[policy_index] in ('REJECT', 'REJECT-DROP') else rules
        destination.append(','.join(parts))
    result['rules'] = rejections + guard + rules
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', required=True, type=pathlib.Path)
    parser.add_argument('--output', required=True, type=pathlib.Path)
    parser.add_argument('--routing', type=pathlib.Path, default=ROOT / 'Leora-Clash-Routing.yaml')
    parser.add_argument('--proxy-name', default='PROXY')
    parser.add_argument('--webrtc', choices=MODES, default='udp')
    args = parser.parse_args()
    result = merge_config(yaml.safe_load(args.input.read_text()),
                          yaml.safe_load(args.routing.read_text()), args.proxy_name, args.webrtc)
    if args.input.resolve() == args.output.resolve():
        parser.error('Use a separate output file to keep the original configuration')
    args.output.write_text(yaml.safe_dump(result, allow_unicode=True, sort_keys=False))


if __name__ == '__main__':
    main()
