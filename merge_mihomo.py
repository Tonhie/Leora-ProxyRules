#!/usr/bin/env python3
"""Merge Leora (whitelist) or Umbra (blacklist) routing into a complete Mihomo YAML."""
import argparse
import copy
import pathlib
import yaml
from routing_policy import (MODES, routing_file, mihomo_settings, protected_mihomo,
                            validate_mihomo_proxy, mihomo_dns_outbound, DNS_OUT)

ROOT = pathlib.Path(__file__).resolve().parent
DEFAULT_ROUTING = {mode: ROOT / routing_file(mode) for mode in MODES}


def merge_config(payload, routing, proxy_name='PROXY'):
    if not isinstance(payload, dict) or not isinstance(routing, dict):
        raise ValueError('Expected Mihomo YAML objects')
    validate_mihomo_proxy(payload, proxy_name)
    result = copy.deepcopy(payload)
    if any(p.get('name')==DNS_OUT and p.get('type')!='dns' for p in result.get('proxies', [])):
        raise ValueError('Conflicting DNS proxy name: ' + DNS_OUT)
    result['proxies'] = [p for p in result.get('proxies', []) if p.get('name')!=DNS_OUT] + [mihomo_dns_outbound()]
    # Replace TUN settings: inherited include/exclude filters could silently
    # bypass capture. Client-managed VPN/TUN still needs its own verification.
    preset = mihomo_settings()
    for key in ('tun', 'dns', 'ipv6', 'mode', 'hosts'):
        result[key] = copy.deepcopy(preset[key])
    result['dns']['nameserver'] = [u.replace('#PROXY', '#' + proxy_name)
                                     for u in result['dns']['nameserver']]
    providers = result.setdefault('rule-providers', {})
    providers.update(copy.deepcopy(routing.get('rule-providers', {})))
    result['rules'] = protected_mihomo(routing['rules'], proxy_name)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', required=True, type=pathlib.Path)
    parser.add_argument('--output', required=True, type=pathlib.Path)
    parser.add_argument('--mode', choices=MODES, default='leora',
                        help='leora=whitelist (default proxy), umbra=blacklist (default direct)')
    parser.add_argument('--routing', type=pathlib.Path,
                        help='routing YAML override; defaults to the selected mode profile')
    parser.add_argument('--proxy-name', default='PROXY')
    args = parser.parse_args()
    routing_path = args.routing or DEFAULT_ROUTING[args.mode]
    result = merge_config(yaml.safe_load(args.input.read_text()),
                          yaml.safe_load(routing_path.read_text()), args.proxy_name)
    if args.input.resolve() == args.output.resolve():
        parser.error('Use a separate output file to keep the original configuration')
    args.output.write_text(yaml.safe_dump(result, allow_unicode=True, sort_keys=False))


if __name__ == '__main__':
    main()
