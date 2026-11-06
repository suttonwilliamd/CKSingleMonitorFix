import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import CKSingleMonitorFix as fix

SCRIPT = Path(fix.__file__).resolve()


class RepairTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.path = self.root / 'CreationKitPrefs.ini'

    def fixture(self, data=b'[Windows]\ncell view x=2000\n'):
        self.path.write_bytes(data)
        return data

    def files(self):
        return sorted(p.name for p in self.root.iterdir())

    def test_import_has_no_output_or_files(self):
        self.fixture(b'original bytes')
        proc = subprocess.run([sys.executable, '-c',
                               f'import sys; sys.path.insert(0, {str(SCRIPT.parent)!r}); import CKSingleMonitorFix'],
                              cwd=self.root, capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout + proc.stderr, '')
        self.assertEqual(self.path.read_bytes(), b'original bytes')
        self.assertEqual(self.files(), [self.path.name])

    def test_missing_does_not_create(self):
        with self.assertRaises(FileNotFoundError):
            fix.check_and_fix_ranges(self.path)
        self.assertEqual(self.files(), [])

    def test_unchanged_does_not_write_or_backup(self):
        original = self.fixture(b'[Windows]\ncell view x=0\nrender window x=1800\nother=99999\n')
        before = self.path.stat().st_mtime_ns
        with mock.patch.object(fix.os, 'replace', side_effect=AssertionError('unexpected write')):
            result = fix.check_and_fix_ranges(self.path)
        self.assertEqual(result.changes, ())
        self.assertIsNone(result.backup)
        self.assertEqual(self.path.stat().st_mtime_ns, before)
        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(self.files(), [self.path.name])

    def test_dry_run_never_creates_temp_or_backup(self):
        original = self.fixture()
        with mock.patch.object(fix.tempfile, 'mkstemp', side_effect=AssertionError('write')):
            result = fix.check_and_fix_ranges(self.path, dry_run=True)
        self.assertEqual(len(result.changes), 1)
        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(self.files(), [self.path.name])

    def test_case_comments_crlf_order_and_unrelated_bytes(self):
        original = self.fixture(b'; hello\r\n[Windows] ; heading\r\n  CeLl View X = -4  ; offscreen\r\n'
                                b'other : abc # untouched\r\nrender window x: 12.5\r\n'
                                b'OBJECTWINDOW X=NaN\r\n# end')
        expected = original.replace(b'-4  ;', b'0  ;').replace(b'X=NaN', b'X=0')
        result = fix.check_and_fix_ranges(self.path)
        self.assertEqual(self.path.read_bytes(), expected)
        self.assertEqual(result.backup.read_bytes(), original)
        self.assertEqual(len(result.changes), 2)
        self.assertFalse(list(self.root.glob('*.tmp')))

    def test_mixed_line_endings_and_no_final_newline(self):
        original = self.fixture(b'[W]\rcell view x=9999\r\nother=yes\nobjectwindow x=-1')
        fix.check_and_fix_ranges(self.path)
        self.assertEqual(self.path.read_bytes(), original.replace(b'9999', b'0').replace(b'-1', b'0'))

    def test_empty_values_preserve_inline_comments(self):
        self.fixture(b'[W]\ncell view x= ; keep\nrender window x :  bad \t# also keep\n')
        fix.check_and_fix_ranges(self.path)
        self.assertEqual(self.path.read_bytes(),
                         b'[W]\ncell view x=0 ; keep\nrender window x :  0 \t# also keep\n')
        self.assertFalse(fix.check_and_fix_ranges(self.path).changes)

    def test_symlink_rejected(self):
        self.fixture()
        link = self.root / 'link.ini'
        try:
            link.symlink_to(self.path)
        except OSError:
            self.skipTest('Symlink creation unavailable to this user')
        with self.assertRaises(fix.RepairError):
            fix.check_and_fix_ranges(link)
        self.assertFalse(list(self.root.glob('*.bak')))

    def test_atomic_replacement_uses_sibling_and_completed_backup(self):
        original = self.fixture()
        real_replace = fix.os.replace
        def replace(source, destination):
            self.assertEqual(source.parent, self.path.parent)
            self.assertEqual(destination, self.path)
            self.assertEqual(self.path.read_bytes(), original)
            self.assertEqual(source.read_bytes(), b'[Windows]\ncell view x=0\n')
            self.assertEqual(next(self.root.glob('*.bak')).read_bytes(), original)
            real_replace(source, destination)
        with mock.patch.object(fix.os, 'replace', side_effect=replace) as replacement:
            fix.check_and_fix_ranges(self.path)
        replacement.assert_called_once()

    def test_invalid_numbers_and_nonfinite(self):
        for value in ('text', '', 'nan', 'NaN', 'inf', '-Infinity', '1e9999', '-1', '1801'):
            with self.subTest(value=value):
                self.fixture(f'[W]\ncell view x={value}\n'.encode())
                result = fix.check_and_fix_ranges(self.path)
                self.assertEqual(len(result.changes), 1)
                self.assertEqual(self.path.read_bytes(), b'[W]\ncell view x=0\n')

    def test_custom_range_and_reset(self):
        self.fixture(b'[W]\ncell view x=8\nrender window x=-100\nobjectwindow x=50\n')
        fix.check_and_fix_ranges(self.path, min_x='-100', max_x='0')
        self.assertEqual(self.path.read_bytes(),
                         b'[W]\ncell view x=-100\nrender window x=-100\nobjectwindow x=-100\n')

    def test_y_coordinates_are_opt_in(self):
        original = self.fixture(b'[W]\ncell view x=12\ncell view y=-9999\n'
                                b'render window y=NaN\nobjectwindow y=offscreen\n')
        before = self.path.stat().st_mtime_ns
        result = fix.check_and_fix_ranges(self.path)
        self.assertEqual(result.changes, ())
        self.assertIsNone(result.backup)
        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(self.path.stat().st_mtime_ns, before)
        self.assertEqual(self.files(), [self.path.name])

    def test_independent_xy_ranges_preserve_valid_boundaries_and_other_keys(self):
        original = self.fixture(
            b'[Windows]\r\ncell view x=-1920\r\nrender window x=1919\r\n'
            b'objectwindow x=1920\r\n  CeLl View Y : -1080 ; upper monitor\r\n'
            b'render window y=1079\r\nOBJECTWINDOW Y=1080 # offscreen\r\n'
            b'other y=9999\r\n[More]\rcell view y=-1081')
        expected = original.replace(b'objectwindow x=1920', b'objectwindow x=-1920')
        expected = expected.replace(b'OBJECTWINDOW Y=1080', b'OBJECTWINDOW Y=-1080')
        expected = expected.replace(b'cell view y=-1081', b'cell view y=-1080')
        result = fix.check_and_fix_ranges(self.path, min_x=-1920, max_x=1919,
                                         min_y=-1080, max_y=1079)
        self.assertEqual(self.path.read_bytes(), expected)
        self.assertEqual(result.backup.read_bytes(), original)
        self.assertEqual(len(result.changes), 3)
        self.assertEqual(fix.check_and_fix_ranges(
            self.path, min_x=-1920, max_x=1919, min_y=-1080, max_y=1079).changes, ())
        self.assertEqual(len(list(self.root.glob('*.bak'))), 1)

    def test_y_repair_dry_run_and_supported_encodings(self):
        for bom, encoding in [(b'', 'utf-8'), (b'\xef\xbb\xbf', 'utf-8'),
                              (b'\xff\xfe', 'utf-16-le'), (b'\xfe\xff', 'utf-16-be')]:
            with self.subTest(encoding=encoding, bom=bom):
                text = '[W]\r\n; café\r\ncell view y=NaN ; keep\nrender window y=\r'
                text += 'objectwindow y=-Infinity\r\nunrelated=100% # opaque'
                original = self.fixture(bom + text.encode(encoding))
                before_files = self.files()
                result = fix.check_and_fix_ranges(
                    self.path, min_y='-10.5', max_y='0', dry_run=True)
                self.assertEqual(len(result.changes), 3)
                self.assertEqual(self.path.read_bytes(), original)
                self.assertEqual(self.files(), before_files)
                result = fix.check_and_fix_ranges(self.path, min_y='-10.5', max_y='0')
                expected = text.replace('=NaN', '=-10.5').replace('y=\r', 'y=-10.5\r')
                expected = expected.replace('=-Infinity', '=-10.5')
                self.assertEqual(self.path.read_bytes(), bom + expected.encode(encoding))
                self.assertEqual(result.backup.read_bytes(), original)

    def test_invalid_or_incomplete_y_ranges_reject_before_any_repair(self):
        original = self.fixture(b'[W]\ncell view x=9999\ncell view y=9999\n')
        for limits in [{'min_y': 0}, {'max_y': 1080},
                       {'min_y': 2, 'max_y': 1},
                       {'min_y': 'NaN', 'max_y': 1},
                       {'min_y': 0, 'max_y': 'Infinity'},
                       {'min_y': 'bad', 'max_y': 0}]:
            with self.subTest(limits=limits):
                with self.assertRaises(fix.RepairError):
                    fix.check_and_fix_ranges(self.path, **limits)
                self.assertEqual(self.path.read_bytes(), original)
                self.assertEqual(self.files(), [self.path.name])

    def test_y_limits_do_not_insert_missing_keys(self):
        original = self.fixture(b'[W]\ncell view x=12\nother y=9999\n')
        result = fix.check_and_fix_ranges(self.path, min_y=0, max_y=1080)
        self.assertEqual(result.changes, ())
        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(self.files(), [self.path.name])

    def test_cli_vertical_repair_requires_both_limits_and_preserves_backup(self):
        original = self.fixture(b'[W]\ncell view x=12\ncell view y=9999 ; keep\r\n')
        for args, status in [([], 0), (['--min-y', '0'], 1),
                             (['--max-y', '1079'], 1),
                             (['--min-y', '0', '--max-y', '1079', '--dry-run'], 0)]:
            with self.subTest(args=args):
                proc = subprocess.run([sys.executable, str(SCRIPT), str(self.path), *args],
                                      capture_output=True, text=True)
                self.assertEqual(proc.returncode, status, proc.stderr)
                self.assertEqual(self.path.read_bytes(), original)
                self.assertEqual(self.files(), [self.path.name])
        proc = subprocess.run(
            [sys.executable, str(SCRIPT), str(self.path), '--min-y', '0', '--max-y', '1079'],
            capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('cell view y:', proc.stdout)
        self.assertEqual(self.path.read_bytes(), b'[W]\ncell view x=12\ncell view y=0 ; keep\r\n')
        backup = next(self.root.glob('*.bak'))
        self.assertEqual(backup.read_bytes(), original)
        self.assertIn(str(backup), proc.stdout)

    def test_invalid_ranges_no_writes(self):
        original = self.fixture()
        for minimum, maximum in [('x', 1), ('nan', 1), (0, 'Infinity'), (2, 1)]:
            with self.subTest(minimum=minimum, maximum=maximum):
                with self.assertRaises(fix.RepairError):
                    fix.check_and_fix_ranges(self.path, min_x=minimum, max_x=maximum)
                self.assertEqual(self.path.read_bytes(), original)
                self.assertEqual(self.files(), [self.path.name])

    def test_supported_encodings(self):
        for bom, encoding in [(b'', 'utf-8'), (b'\xef\xbb\xbf', 'utf-8'),
                              (b'\xff\xfe', 'utf-16-le'), (b'\xfe\xff', 'utf-16-be')]:
            with self.subTest(encoding=encoding, bom=bom):
                text = '[W]\r\n; café\r\ncell view x=9999\r\n'
                original = self.fixture(bom + text.encode(encoding))
                result = fix.check_and_fix_ranges(self.path)
                self.assertEqual(self.path.read_bytes(), bom + text.replace('9999', '0').encode(encoding))
                self.assertEqual(result.backup.read_bytes(), original)

    def test_malformed_or_unsupported_rejected_before_any_write(self):
        for data in [b'[W]\ncell view x=9000\nmalformed', b'cell view x=99',
                     b'[W]\ncell view x=99\nCELL VIEW X=3', b'[W]\n[W]\n',
                     b'[W]\nkey=one\n continuation', b'[W\n', b'\xff',
                     b'\xff\xfe\x00\x00', b'[\x00W\x00]\x00', b'[W]\nkey=\x00']:
            with self.subTest(data=data):
                self.fixture(data)
                with self.assertRaises(fix.RepairError):
                    fix.check_and_fix_ranges(self.path)
                self.assertEqual(self.path.read_bytes(), data)
                self.assertEqual(self.files(), [self.path.name])

    def test_backups_are_unique_and_second_run_is_noop(self):
        first = self.fixture()
        one = fix.check_and_fix_ranges(self.path)
        fix.check_and_fix_ranges(self.path)
        self.assertEqual(len(list(self.root.glob('*.bak'))), 1)
        second = self.fixture(b'[W]\ncell view x=-100\n')
        two = fix.check_and_fix_ranges(self.path)
        self.assertNotEqual(one.backup, two.backup)
        self.assertEqual(one.backup.read_bytes(), first)
        self.assertEqual(two.backup.read_bytes(), second)

    def test_backup_creation_failure_leaves_input(self):
        original = self.fixture()
        with mock.patch.object(fix.tempfile, 'mkstemp', side_effect=PermissionError('backup denied')):
            with self.assertRaises(PermissionError):
                fix.check_and_fix_ranges(self.path)
        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(self.files(), [self.path.name])

    def test_backup_write_failure_removes_partial_backup(self):
        original = self.fixture()
        with mock.patch.object(fix.os, 'fsync', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                fix.check_and_fix_ranges(self.path)
        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(self.files(), [self.path.name])

    def test_temp_write_and_replace_failures_retain_backup(self):
        for stage in ('create', 'write', 'replace'):
            with self.subTest(stage=stage):
                original = self.fixture()
                real_create = fix.tempfile.mkstemp
                real_write = fix._write_and_sync
                def create(**kwargs):
                    if kwargs['suffix'] == '.tmp' and stage == 'create':
                        raise OSError('temp denied')
                    return real_create(**kwargs)
                calls = []
                def write(fd, data):
                    calls.append(data)
                    if len(calls) == 2 and stage == 'write':
                        os.close(fd)
                        raise OSError('write failed')
                    return real_write(fd, data)
                with mock.patch.object(fix.tempfile, 'mkstemp', side_effect=create), \
                     mock.patch.object(fix, '_write_and_sync', side_effect=write), \
                     mock.patch.object(fix.os, 'replace', side_effect=OSError('replace denied')):
                    with self.assertRaises(OSError):
                        fix.check_and_fix_ranges(self.path)
                self.assertEqual(self.path.read_bytes(), original)
                self.assertFalse(list(self.root.glob('*.tmp')))
                self.assertTrue(all(p.read_bytes() == original for p in self.root.glob('*.bak')))

    def test_detects_concurrent_modification(self):
        original = self.fixture()
        real_write = fix._write_and_sync
        calls = []
        def write(fd, data):
            real_write(fd, data)
            calls.append(data)
            if len(calls) == 2:
                self.path.write_bytes(b'changed by another writer')
        with mock.patch.object(fix, '_write_and_sync', side_effect=write):
            with self.assertRaises(fix.RepairError):
                fix.check_and_fix_ranges(self.path)
        self.assertEqual(self.path.read_bytes(), b'changed by another writer')
        self.assertEqual(next(self.root.glob('*.bak')).read_bytes(), original)
        self.assertFalse(list(self.root.glob('*.tmp')))

    def test_directory_rejected(self):
        with self.assertRaises(fix.RepairError):
            fix.check_and_fix_ranges(self.root)

    def test_cli_default_dry_run_and_errors(self):
        original = self.fixture()
        for args, status in [(['--dry-run'], 0), (['--min-x', 'nan'], 1),
                             (['missing.ini'], 1), (['--unknown'], 2)]:
            proc = subprocess.run([sys.executable, str(SCRIPT), *args], cwd=self.root,
                                  capture_output=True, text=True)
            self.assertEqual(proc.returncode, status, proc.stderr)
            self.assertEqual(self.path.read_bytes(), original)
            self.assertEqual(self.files(), [self.path.name])
        proc = subprocess.run([sys.executable, str(SCRIPT), str(self.path)],
                              capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('Backup:', proc.stdout)
        self.assertEqual(self.path.read_bytes(), b'[Windows]\ncell view x=0\n')


if __name__ == '__main__':
    unittest.main()
