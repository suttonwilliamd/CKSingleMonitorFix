"""Fake children qualify helper failure handling, NEVER frozen acceptance."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import time
import unittest
from types import SimpleNamespace
from unittest import mock

SPEC = importlib.util.spec_from_file_location('frozen_helper', Path(__file__).resolve().parents[1] / 'tools/frozen_cli_smoke.py')
helper = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(helper)


class HelperTests(unittest.TestCase):
    def run_fake(self, code, timeout=2):
        with tempfile.TemporaryDirectory() as directory:
            return helper.run_child([sys.executable, '-c', code], Path(directory), {}, timeout)

    def test_exit_distinction_and_null_stdin(self):
        rc, out, err, ok = self.run_fake('import sys; assert sys.stdin.read()==""; print("ok"); sys.exit(2)')
        self.assertEqual((rc, out.strip(), err, ok), (2, b'ok', b'', True))

    def test_timeout(self):
        start = time.monotonic()
        rc, out, err, ok = self.run_fake('import time; time.sleep(30)', .15)
        self.assertFalse(ok)
        self.assertLess(time.monotonic() - start, 8)

    def test_stdout_and_stderr_floods(self):
        for stream in ('stdout', 'stderr'):
            with self.subTest(stream=stream):
                rc, out, err, ok = self.run_fake(
                    'import sys; sys.' + stream + '.write("SENSITIVE"*1000000)', 2)
                self.assertFalse(ok)
                self.assertLessEqual(len(out), helper.LIMIT)
                self.assertLessEqual(len(err), helper.LIMIT)

    def test_launch_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(OSError):
                helper.run_child([str(Path(directory) / 'nonexistent')], Path(directory), {}, 1)

    def test_descendant_cannot_hold_capture_open(self):
        # Inherits pipe handles; Job (Windows) / process group (POSIX) must kill it.
        code = ('import subprocess,sys; subprocess.Popen([sys.executable,"-c",'
                '"import time; time.sleep(30)"], stdout=sys.stdout, stderr=sys.stderr)')
        start = time.monotonic()
        rc, out, err, ok = self.run_fake(code, .2)
        self.assertFalse(ok)
        self.assertLess(time.monotonic() - start, 8)

    def test_job_setup_failure_is_fail_closed(self):
        if os.name != 'nt':
            self.skipTest('Windows Job implementation needs real Windows')
        with mock.patch.object(helper, 'WindowsTree', side_effect=OSError('private')):
            with self.assertRaises(OSError):
                self.run_fake('raise RuntimeError("must not execute")')

    def test_canned_success_never_qualifies(self):
        # Even help-ish output and perfect return codes cannot satisfy byte/backup oracles.
        def canned(command, cwd, env, timeout):
            code = 2 if '--not-an-option' in command else 1 if any(
                str(x).endswith(('absent.ini', 'malformed.ini')) for x in command) else 0
            return code, b'--dry-run', b'error' if code else b'', True
        with mock.patch.object(helper, 'run_child', side_effect=canned):
            result = helper.smoke(Path('/fake.exe'))
        self.assertTrue(result['utf8_dry'])
        self.assertFalse(result['utf8_modify'])
        self.assertFalse(result['utf16_le_unique'])
        self.assertFalse(all(result.values()))

    def test_isolation_and_unexpected_state_fail(self):
        seen = []
        def unexpected(command, cwd, env, timeout):
            seen.append(env)
            (cwd.parent / 'profile' / 'unexpected').write_bytes(b'private')
            return 0, b'--dry-run', b'', True
        with mock.patch.dict(os.environ, {'SECRET_TOKEN': 'never-forward'}):
            with mock.patch.object(helper, 'run_child', side_effect=unexpected):
                result = helper.smoke(Path('/fake.exe'))
        self.assertFalse(result['isolated_state_clean'])
        self.assertTrue(all('SECRET_TOKEN' not in env and 'PATH' not in env for env in seen))

    def test_main_exception_always_fixed_report(self):
        with tempfile.TemporaryDirectory() as directory:
            report = Path(directory) / 'report.json'
            with mock.patch.object(helper, 'pe_amd64', side_effect=RuntimeError('PRIVATE_SENTINEL')):
                with mock.patch.object(helper.os, 'name', 'nt'):
                    with mock.patch.object(helper.platform, 'machine', return_value='AMD64'):
                        # Path is instantiated before the os.name patch to avoid POSIX WindowsPath.
                        args = SimpleNamespace(executable=report, source_sha='a'*40, report=report)
                        with mock.patch.object(helper.argparse.ArgumentParser, 'parse_args', return_value=args):
                            self.assertEqual(helper.main([]), 1)
            self.assertNotIn('PRIVATE_SENTINEL', report.read_text())
            self.assertEqual(json.loads(report.read_text())['status'], 'fail')

    def test_total_deadline(self):
        with self.assertRaises(TimeoutError):
            helper.smoke(Path('/fake.exe'), total=0)

    def test_main_rejects_script_and_redacts_exception(self):
        with tempfile.TemporaryDirectory() as directory:
            report = Path(directory) / 'report.json'
            rc = helper.main([__file__, '--source-sha', 'a'*40, '--report', str(report)])
            data = json.loads(report.read_text())
            self.assertEqual(rc, 1)
            self.assertEqual(data['status'], 'fail')
            self.assertNotIn(directory, report.read_text())
            self.assertNotIn(__file__, report.read_text())

    def test_pe_checks(self):
        with tempfile.TemporaryDirectory() as directory:
            exe = Path(directory) / 'fake.exe'
            data = bytearray(90)
            data[:2] = b'MZ'
            struct.pack_into('<I', data, 60, 64)
            data[64:70] = b'PE\0\0\x64\x86'
            struct.pack_into('<H', data, 86, 2)
            data[88:90] = b'\x0b\x02'
            exe.write_bytes(data)
            self.assertTrue(helper.pe_amd64(exe))  # structural preflight only, not acceptance
            data[68:70] = b'\x4c\x01'
            exe.write_bytes(data)
            self.assertFalse(helper.pe_amd64(exe))
            exe.write_bytes(b'print("fake")')
            self.assertFalse(helper.pe_amd64(exe))

    def test_import_has_no_output(self):
        with tempfile.TemporaryDirectory() as directory:
            code = 'import runpy; runpy.run_path(' + repr(str(Path(helper.__file__).resolve())) + ')'
            result = subprocess.run([sys.executable, '-B', '-c', code], cwd=directory,
                                    capture_output=True, timeout=5)
            self.assertEqual((result.returncode, result.stdout, result.stderr), (0, b'', b''))
            self.assertEqual(list(Path(directory).iterdir()), [])


if __name__ == '__main__':
    unittest.main()
