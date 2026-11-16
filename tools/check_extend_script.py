#!/usr/bin/env python3
"""Check that a file can be imported as a Clash/FlClash Extend script.

FlClash evaluates the content of Extend -> Script with QuickJS. Importing the
wrong artifact fails inside the client with a message that does not name the
real problem: a Shadowrocket *.conf starts with '#' and QuickJS reports
"invalid first character of private name at eval_script:1:1"; a Mihomo
*-Clash-Routing.yaml report a YAML/token parse error. Run this tool on the
downloaded file before importing it to see what it actually is and what to use
instead.

    python3 tools/check_extend_script.py PATH [PATH ...]
    python3 tools/check_extend_script.py --expect-mode umbra Umbra-Clash-Extend.js

Exit codes: 0 = importable script, 1 = not importable, 2 = unreadable input.
"""
import argparse
import pathlib
import re
import sys

SCRIPT_NAMES = {'leora': 'Leora-Clash-Extend.js', 'umbra': 'Umbra-Clash-Extend.js'}
FORBIDDEN = ('require(', 'fetch(', 'XMLHttpRequest', 'setTimeout(',
             'process.', 'node:')
MAIN_RE = re.compile(r'\bfunction\s+main\s*\(|\b(?:const|let|var)\s+main\s*=')
MODE_RE = re.compile(r'(Leora|Umbra) Proxy Rules - Clash Extend script')
YAML_KEYS = (
    'mode', 'mixed-port', 'socks-port', 'port', 'redir-port', 'tproxy-port',
    'ipv6', 'dns', 'rules', 'proxies', 'proxy-groups', 'proxy-providers',
    'rule-providers', 'tun', 'hosts', 'log-level', 'allow-lan', 'listeners',
)


def read_file(path):
    try:
        return pathlib.Path(path).read_bytes()
    except OSError as error:
        print('ERROR 无法读取 %s: %s' % (path, error), file=sys.stderr)
        raise SystemExit(2)


def looks_like_yaml(text):
    for line in text.splitlines()[:60]:
        match = re.match(r'^([A-Za-z][A-Za-z0-9-]*):(?:\s|$)', line)
        if match and match.group(1) in YAML_KEYS:
            return True
    return False


def classify(data):
    """Return (kind, text) for the artifact bytes."""
    if not data.strip():
        return 'empty', ''
    bom = data.startswith(b'\xef\xbb\xbf')
    raw = data[3:] if bom else data
    try:
        text = raw.decode('utf-8')
    except UnicodeDecodeError:
        try:
            raw.decode('gbk')
            return 'not-utf8', ''
        except UnicodeDecodeError:
            return 'binary', ''
    stripped = text.lstrip()
    if stripped.startswith('#') or ('[General]' in text and '[Rule]' in text):
        return 'shadowrocket-conf', text
    if stripped.startswith('{') and '"outbounds"' in text:
        return 'xray-json', text
    if looks_like_yaml(text):
        return 'mihomo-yaml', text
    if MAIN_RE.search(text):
        return 'clash-script', text
    if stripped.startswith(('/*', '//')) or 'function ' in text or '=>' in text:
        return 'javascript-no-main', text
    return 'unknown', text


def mode_of(text):
    match = MODE_RE.search(text)
    return match.group(1).lower() if match else None


def suggest(mode, filename):
    if mode:
        return SCRIPT_NAMES[mode]
    lowered = filename.lower()
    if 'umbra' in lowered:
        return SCRIPT_NAMES['umbra']
    if 'leora' in lowered:
        return SCRIPT_NAMES['leora']
    return 'Umbra-Clash-Extend.js（黑名单）或 Leora-Clash-Extend.js（白名单）'


def inspect(path, expect_mode=None):
    """Return (importable, lines) for one file."""
    name = pathlib.Path(path).name
    data = read_file(path)
    kind, text = classify(data)
    lines = []
    if kind == 'clash-script':
        mode = mode_of(text)
        problems = [item for item in FORBIDDEN if item in text]
        lines.append('OK    %s 是 Clash/FlClash 扩展脚本%s。'
                     % (name, '（%s）' % mode if mode else ''))
        lines.append('      导入方式：FlClash 的脚本库「从 URL/文件导入」→ 目标配置的'
                     ' 扩展 → 扩展模式选「脚本」→ 选中该脚本。不要导入到「配置」或「规则集」。')
        if data.startswith(b'\xef\xbb\xbf'):
            lines.append('注意  %s 带 UTF-8 BOM；浏览器里另存后如报语法错误请先去掉 BOM。' % name)
        if problems:
            lines.append('ERROR %s 使用了 FlClash/QuickJS 脚本槽不允许的平台 API：%s'
                         % (name, ', '.join(problems)))
            return False, lines
        if expect_mode and mode and mode != expect_mode:
            lines.append('ERROR 模式不符：期望 %s，实际 %s。Umbra 配置必须选 '
                         'Umbra-Clash-Extend.js，Leora 配置必须选 Leora-Clash-Extend.js。'
                         % (expect_mode, mode))
            return False, lines
        return True, lines
    if kind == 'shadowrocket-conf':
        lines.append('ERROR %s 是 Shadowrocket 远程配置（*.conf），不是 Clash/FlClash '
                     '扩展脚本。' % name)
        lines.append('      FlClash 的 QuickJS 会报 invalid first character of private '
                     'name at eval_script:1:1，因为 .conf 以 # 注释开头。')
        lines.append('      改用：%s（Shadowrocket 仍在「配置 → 远程配置」里使用原来的 .conf）。'
                     % suggest(None, name))
        lines.append('      脚本库只放 .js；绑定时不要选错模式：Umbra 配置选 Umbra 脚本，'
                     'Leora 配置选 Leora 脚本。')
        return False, lines
    if kind == 'mihomo-yaml':
        lines.append('ERROR %s 是 Mihomo/Clash 完整配置 YAML，不是扩展脚本。' % name)
        lines.append('      FlClash 脚本槽会解析失败（unexpected token / YAML 错误）；'
                     'YAML 应作为配置加载或与订阅合并，'
                     '要叠加 Leora/Umbra 路由请用 %s。' % suggest(None, name))
        return False, lines
    if kind == 'xray-json':
        lines.append('ERROR %s 是 Xray 路由 JSON，不是 Clash 扩展脚本；'
                     '它要合并进 Xray 配置。' % name)
        return False, lines
    if kind == 'javascript-no-main':
        lines.append('ERROR %s 是 JavaScript，但没有 main(config) 入口；'
                     'FlClash 会报 script does not define main()。' % name)
        return False, lines
    if kind == 'not-utf8':
        lines.append('ERROR %s 不是 UTF-8 文本；FlClash 按 UTF-8 读取脚本会失败。' % name)
        return False, lines
    if kind == 'binary':
        lines.append('ERROR %s 像是二进制文件，不是文本脚本。' % name)
        return False, lines
    if kind == 'empty':
        lines.append('ERROR %s 是空文件。' % name)
        return False, lines
    lines.append('ERROR 无法识别 %s 的格式；扩展脚本必须是 UTF-8 JavaScript，'
                 '并定义 function main(config)。' % name)
    return False, lines


def main(argv=None):
    parser = argparse.ArgumentParser(
        description='Import 前检查文件是否是 Clash/FlClash 扩展脚本')
    parser.add_argument('paths', nargs='+', metavar='PATH',
                        help='要检查的文件（.js / .conf / .yaml / .json）')
    parser.add_argument('--expect-mode', choices=('leora', 'umbra'),
                        help='要求脚本属于该模式，用于抓出选错模式的脚本')
    args = parser.parse_args(argv)
    importable = True
    for path in args.paths:
        ok, lines = inspect(path, args.expect_mode)
        for line in lines:
            print(line)
        importable = importable and ok
    return 0 if importable else 1


if __name__ == '__main__':
    sys.exit(main())
