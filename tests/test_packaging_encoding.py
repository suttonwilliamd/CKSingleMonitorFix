"""Source encoding analogue and static packaging contract, not EXE acceptance."""
import ast
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class PackagingEncodingTests(unittest.TestCase):
    def test_spec_passes_documented_utf8_option_to_exe(self):
        # Inspect syntax without executing a spec or faking PyInstaller modules.
        tree = ast.parse((ROOT / 'CKSingleMonitorFix.spec').read_text(encoding='utf-8'))
        options = next(node.value for node in tree.body if isinstance(node, ast.Assign)
                       and any(isinstance(t, ast.Name) and t.id == 'options' for t in node.targets))
        self.assertEqual(ast.literal_eval(options), [('X utf8=1', None, 'OPTION')])
        exe = next(node for node in ast.walk(tree) if isinstance(node, ast.Call)
                   and isinstance(node.func, ast.Name) and node.func.id == 'EXE')
        self.assertIsInstance(exe.args[4], ast.Name)
        self.assertEqual(exe.args[4].id, 'options')

    def test_source_pipe_encoding_boundary(self):
        # A deliberately forced cp1252 pipe models the diagnostic boundary,
        # not the locale or bootloader of the actual hosted Windows process.
        for mode in ('cp1252', 'utf8'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / 'chosen space Ω.ini'
                original = b'[Windows]\ncell view x=9999\n'
                path.write_bytes(original)
                env = {k: os.environ[k] for k in ('SystemRoot', 'WINDIR') if k in os.environ}
                env.update({'LC_ALL': 'C', 'PYTHONCOERCECLOCALE': '0'})
                if mode == 'cp1252':
                    env['PYTHONIOENCODING'] = 'cp1252:strict'
                child = subprocess.run(
                    [sys.executable, '-X', 'utf8=' + ('1' if mode == 'utf8' else '0'),
                     str(ROOT / 'CKSingleMonitorFix.py'), str(path)],
                    cwd=directory, env=env, capture_output=True, timeout=10)
                self.assertEqual(child.returncode, 1 if mode == 'cp1252' else 0)
                self.assertEqual(b'UnicodeEncodeError' in child.stderr, mode == 'cp1252')
                self.assertEqual(path.read_bytes(), b'[Windows]\ncell view x=0\n')
                backups = list(Path(directory).glob('*.bak'))
                self.assertEqual(len(backups), 1)
                self.assertEqual(backups[0].read_bytes(), original)


if __name__ == '__main__':
    unittest.main()
