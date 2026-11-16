import os
import pathlib
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
TOOL = ROOT / 'tools' / 'check_extend_script.py'
ENV = {**os.environ, 'PYTHONUTF8': '1'}


def run(*args):
    return subprocess.run(
        [sys.executable, str(TOOL), *map(str, args)],
        cwd=ROOT, capture_output=True, text=True, encoding='utf-8',
        env=ENV, timeout=60,
    )


class CheckExtendScriptTests(unittest.TestCase):
    def test_generated_scripts_are_importable(self):
        for name, mode in (('Leora-Clash-Extend.js', 'leora'),
                           ('Umbra-Clash-Extend.js', 'umbra')):
            completed = run(ROOT / name)
            output = completed.stdout + completed.stderr
            self.assertEqual(completed.returncode, 0, output)
            self.assertIn('是 Clash/FlClash 扩展脚本', output)
            self.assertIn(mode, output)
            self.assertIn('扩展模式选「脚本」', output)

    def test_shadowrocket_conf_is_rejected_with_the_quickjs_error(self):
        completed = run(ROOT / 'Umbra-ProxyRules.conf')
        output = completed.stdout + completed.stderr
        self.assertEqual(completed.returncode, 1, output)
        self.assertIn('Shadowrocket', output)
        self.assertIn('invalid first character of private name at eval_script:1:1',
                      output)
        self.assertIn('Umbra-Clash-Extend.js', output)

    def test_mihomo_yaml_is_rejected(self):
        completed = run(ROOT / 'Umbra-Clash-Routing.yaml')
        output = completed.stdout + completed.stderr
        self.assertEqual(completed.returncode, 1, output)
        self.assertIn('不是扩展脚本', output)
        self.assertIn('Umbra-Clash-Extend.js', output)

    def test_plain_javascript_without_main_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            path = pathlib.Path(temp) / 'fragment.js'
            path.write_text('const value = 1;\n', encoding='utf-8')
            completed = run(path)
        output = completed.stdout + completed.stderr
        self.assertEqual(completed.returncode, 1, output)
        self.assertIn('main(config)', output)

    def test_expect_mode_rejects_the_other_profiles_script(self):
        completed = run('--expect-mode', 'umbra', ROOT / 'Leora-Clash-Extend.js')
        output = completed.stdout + completed.stderr
        self.assertEqual(completed.returncode, 1, output)
        self.assertIn('模式不符', output)
        # The matching script must pass.
        completed = run('--expect-mode', 'umbra', ROOT / 'Umbra-Clash-Extend.js')
        self.assertEqual(completed.returncode, 0,
                         completed.stdout + completed.stderr)

    def test_bom_script_is_importable_with_a_warning(self):
        with tempfile.TemporaryDirectory() as temp:
            path = pathlib.Path(temp) / 'bom.js'
            source = (ROOT / 'Leora-Clash-Extend.js').read_bytes()
            path.write_bytes(b'\xef\xbb\xbf' + source)
            completed = run(path)
        output = completed.stdout + completed.stderr
        self.assertEqual(completed.returncode, 0, output)
        self.assertIn('BOM', output)

    def test_missing_file_is_an_input_error(self):
        completed = run(ROOT / 'does-not-exist.js')
        self.assertEqual(completed.returncode, 2)


if __name__ == '__main__':
    unittest.main()
