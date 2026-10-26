"""Synthetic fixtures only: these bytes are NOT Windows binaries or qualification."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import zipfile

from tools import package_release_candidate as pack


class ReleaseCandidateTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.exe = self.root / 'synthetic NOT a Windows binary.exe'
        self.exe.write_bytes(b'SYNTHETIC TEST DATA - NOT A WINDOWS BINARY\n')
        self.report = self.root / 'report.json'
        self.verification = self.root / 'artifact-verification.json'
        self.args = dict(exe=self.exe, report=self.report, verification=self.verification,
                         output=self.root / 'output', name='ck-test-rc1',
                         expected_sha256=pack.digest(self.exe.read_bytes()),
                         expected_size=self.exe.stat().st_size, source_sha='a' * 40,
                         qualification_run=123, packager_source='b' * 40,
                         packaging_run='synthetic-test')
        self.qualified = dict(schema=2, status='pass', helper_error=False,
                              platform='Windows-AMD64', source_sha='a' * 40,
                              exe_sha256=self.args['expected_sha256'],
                              exe_size=self.args['expected_size'], python='3.13.16',
                              freezer='6.16.0', cases={case: True for case in pack.CASES},
                              diagnostics={case: dict(
                                  rc=2 if case == 'syntax' else 1 if case in
                                  ('missing', 'malformed') else 0,
                                  healthy=True, unicode_encode_error=False)
                                  for case in pack.INVOCATIONS})
        self.verified = dict(head='a' * 40, run=123,
                             exeSha256=self.args['expected_sha256'],
                             exeBytes=self.args['expected_size'],
                             jobs=[['windows-frozen-cli', 'success']],
                             actualCasesPassed=22, healthyInvocations=20)
        self.save()

    def save(self):
        self.report.write_bytes(pack.canonical(self.qualified))
        self.verified['reportSha256'] = pack.digest(self.report.read_bytes())
        self.verification.write_bytes(pack.canonical(self.verified))

    def refused(self, exception=ValueError):
        with self.assertRaises(exception):
            pack.package(**self.args)
        self.assertFalse(self.args['output'].exists())

    def test_success_archive_manifest_and_checksums(self):
        output = pack.package(**self.args)
        self.assertEqual({p.name for p in output.iterdir()},
                         {'ck-test-rc1.zip', 'manifest.json', 'SHA256SUMS'})
        with zipfile.ZipFile(output / 'ck-test-rc1.zip') as archive:
            self.assertIsNone(archive.testzip())
            names = archive.namelist()
            self.assertEqual(len(names), 6)
            self.assertTrue(all(n.startswith('ck-test-rc1/') and '..' not in n for n in names))
            self.assertEqual(archive.read('ck-test-rc1/CKSingleMonitorFix.exe'), self.exe.read_bytes())
            self.assertEqual(archive.read('ck-test-rc1/manifest.json'),
                             (output / 'manifest.json').read_bytes())
            for line in archive.read('ck-test-rc1/SHA256SUMS').decode().splitlines():
                sha, name = line.split('  ')
                self.assertEqual(sha, hashlib.sha256(archive.read('ck-test-rc1/' + name)).hexdigest())
            self.assertIn(b'not cryptographically authenticated', archive.read('ck-test-rc1/LIMITS.txt'))
        for line in (output / 'SHA256SUMS').read_text().splitlines():
            sha, name = line.split('  ')
            self.assertEqual(sha, pack.digest((output / name).read_bytes()))

    def test_deterministic_even_with_different_input_paths(self):
        first = pack.package(**self.args)
        copied = self.root / 'different.exe'
        copied.write_bytes(self.exe.read_bytes())
        self.args.update(exe=copied, output=self.root / 'second')
        second = pack.package(**self.args)
        for item in first.iterdir():
            self.assertEqual(item.read_bytes(), (second / item.name).read_bytes())

    def test_wrong_digest(self):
        self.args['expected_sha256'] = '0' * 64
        self.refused()

    def test_wrong_size(self):
        self.args['expected_size'] += 1
        self.refused()

    def test_missing_inputs(self):
        for key in ('exe', 'verification', 'report'):
            with self.subTest(key=key):
                original = self.args[key]
                self.args[key] = self.root / ('missing' + ('.exe' if key == 'exe' else '.json'))
                self.refused(OSError)
                self.args[key] = original

    def test_report_hash_mismatch(self):
        self.report.write_bytes(self.report.read_bytes() + b' ')
        self.refused()

    def test_source_run_and_verification_binding(self):
        for key, value in [('head', 'c' * 40), ('run', 124), ('exeBytes', 1),
                           ('exeSha256', '0' * 64), ('actualCasesPassed', 21),
                           ('healthyInvocations', 19), ('jobs', [])]:
            with self.subTest(key=key):
                old = self.verified[key]
                self.verified[key] = value
                self.save()
                self.refused()
                self.verified[key] = old

    def test_failed_or_incomplete_qualification(self):
        for key, value in [('status', 'fail'), ('schema', True), ('helper_error', True),
                           ('platform', 'Linux'), ('cases', {}), ('diagnostics', {}),
                           ('source_sha', 'c' * 40), ('exe_size', 1), ('python', '')]:
            with self.subTest(key=key):
                old = self.qualified[key]
                self.qualified[key] = value
                self.save()
                self.refused()
                self.qualified[key] = old

    def test_boolean_cases_and_diagnostics_are_strict(self):
        self.qualified['cases']['help'] = 1
        self.save()
        self.refused()
        self.qualified['cases']['help'] = True
        self.qualified['diagnostics']['help']['rc'] = False
        self.save()
        self.refused()

    def test_unsafe_archive_names(self):
        for name in ('../escape', '/absolute', r'a\b', 'a/b', 'a:b', '.', '..',
                     'CON', 'nul', 'COM1', 'LPT9', 'bad.', 'bad ', '-bad', 'Ω', 'x' * 81):
            with self.subTest(name=name):
                self.args['name'] = name
                self.refused()

    def test_no_overwrite(self):
        self.args['output'].mkdir()
        marker = self.args['output'] / 'keep'
        marker.write_bytes(b'keep')
        with self.assertRaises(ValueError):
            pack.package(**self.args)
        self.assertEqual(marker.read_bytes(), b'keep')

    def test_symlink_input_refused(self):
        link = self.root / 'linked.exe'
        try:
            link.symlink_to(self.exe)
        except OSError:
            self.skipTest('symlinks unavailable to this user')
        self.args['exe'] = link
        self.refused()

    def test_malformed_and_duplicate_json(self):
        for data in (b'{', b'[]', b'{"schema": 2, "schema": 2}'):
            self.report.write_bytes(data)
            self.verified['reportSha256'] = pack.digest(data)
            self.verification.write_bytes(pack.canonical(self.verified))
            self.refused()

    def test_failed_case_and_unhealthy_diagnostics(self):
        self.qualified['cases']['help'] = False
        self.save()
        self.refused()
        self.qualified['cases']['help'] = True
        for key, value in [('healthy', False), ('unicode_encode_error', True), ('rc', 1)]:
            with self.subTest(key=key):
                old = self.qualified['diagnostics']['help'][key]
                self.qualified['diagnostics']['help'][key] = value
                self.save()
                self.refused()
                self.qualified['diagnostics']['help'][key] = old

    def test_cli_success_and_rejection(self):
        argv = []
        for key, value in self.args.items():
            argv.extend(['--' + key.replace('_', '-'), str(value)])
        with mock.patch('builtins.print'):
            self.assertEqual(pack.main(argv), 0)
        # Existing output is refused, and CLI returns a nonzero failure.
        with mock.patch('sys.stderr'):
            with self.assertRaises(SystemExit) as caught:
                pack.main(argv)
        self.assertEqual(caught.exception.code, 1)

    def test_failed_copy_cleans_reserved_output(self):
        with mock.patch.object(pack.shutil, 'copyfile', side_effect=OSError('synthetic copy failure')):
            self.refused(OSError)
        self.assertFalse(list(self.root.glob('.ck-package-*')))

    def test_identity_validation(self):
        for key, value in [('source_sha', 'main'), ('packager_source', 'HEAD'),
                           ('packaging_run', '../run'), ('qualification_run', True),
                           ('expected_size', True)]:
            with self.subTest(key=key):
                old = self.args[key]
                self.args[key] = value
                self.refused()
                self.args[key] = old


if __name__ == '__main__':
    unittest.main()
