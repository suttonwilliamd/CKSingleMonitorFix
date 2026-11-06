"""Snapshot planning and fail-closed application on synthetic files only."""
from dataclasses import FrozenInstanceError
import errno
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import CKSingleMonitorFix as fix


class PreviewTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.path = self.root / 'chosen.ini'
        self.original = b'[W]\r\ncell view x=9999 ; keep\r\ncell view y=NaN\r\nother=opaque'
        self.path.write_bytes(self.original)

    def assert_no_outputs(self, expected=None):
        self.assertEqual(self.path.read_bytes(), self.original if expected is None else expected)
        self.assertEqual(list(self.root.iterdir()), [self.path])

    def test_preview_is_read_only_and_exact_plan_applies(self):
        with mock.patch.object(fix.tempfile, 'mkstemp', side_effect=AssertionError('write')):
            preview = fix.preview_repair(self.path, min_x=-10, max_x=10, min_y=-20, max_y=20)
        self.assert_no_outputs()
        with self.assertRaises(FrozenInstanceError):
            preview.path = self.root / 'other.ini'
        result = fix.apply_preview(preview)
        self.assertEqual(self.path.read_bytes(), self.original.replace(b'9999', b'-10').replace(b'NaN', b'-20'))
        self.assertEqual(result.backup.read_bytes(), self.original)
        with self.assertRaises(fix.RepairError):
            fix.apply_preview(preview)
        self.assertEqual(len(list(self.root.glob('*.bak'))), 1)

    def test_stale_source_fails_before_any_backup_or_temporary(self):
        preview = fix.preview_repair(self.path)
        changed = b'[W]\ncell view x=8000\n'
        self.path.write_bytes(changed)
        with mock.patch.object(fix.tempfile, 'mkstemp', side_effect=AssertionError('write')):
            with self.assertRaises(fix.RepairError):
                fix.apply_preview(preview)
        self.assert_no_outputs(changed)
        fresh = fix.preview_repair(self.path)
        result = fix.apply_preview(fresh)
        self.assertEqual(result.backup.read_bytes(), changed)

    def test_same_bytes_replaced_file_is_stale(self):
        preview = fix.preview_repair(self.path)
        replacement = self.root / 'replacement'
        replacement.write_bytes(self.original)
        os.replace(replacement, self.path)
        with self.assertRaises(fix.RepairError):
            fix.apply_preview(preview)
        self.assert_no_outputs()

    def test_missing_or_directory_after_preview_creates_nothing(self):
        preview = fix.preview_repair(self.path)
        self.path.unlink()
        with self.assertRaises(FileNotFoundError):
            fix.apply_preview(preview)
        self.assertEqual(list(self.root.iterdir()), [])
        self.path.mkdir()
        with self.assertRaises(fix.RepairError):
            fix.apply_preview(preview)
        self.assertEqual(list(self.path.iterdir()), [])
        self.assertFalse(list(self.root.glob('*.bak')))

    def test_symlink_substitution_rejected_without_following_selected_link(self):
        preview = fix.preview_repair(self.path)
        target = self.root / 'target.ini'
        target.write_bytes(self.original)
        link = self.root / 'link.ini'
        try:
            link.symlink_to(target)
        except OSError:
            self.skipTest('Symlink creation unavailable to this user')
        with self.assertRaises(fix.RepairError):
            fix.preview_repair(link)
        self.path.unlink()
        self.path.symlink_to(target)
        with self.assertRaises(fix.RepairError):
            fix.apply_preview(preview)
        self.assertEqual(target.read_bytes(), self.original)
        self.assertFalse(list(self.root.glob('*.bak')))

    def test_change_during_preview_read_is_rejected(self):
        real_read = Path.read_bytes
        def read(path):
            data = real_read(path)
            path.write_bytes(data + b'\n; concurrent change')
            return data
        with mock.patch.object(Path, 'read_bytes', read):
            with self.assertRaises(fix.RepairError):
                fix.preview_repair(self.path)
        self.assertFalse(list(self.root.glob('*.bak')))

    def test_noop_is_not_rewritten_and_stale_noop_still_rejected(self):
        self.original = b'[W]\ncell view x=0\ncell view y=NaN\n'
        self.path.write_bytes(self.original)
        before = self.path.stat().st_mtime_ns
        preview = fix.preview_repair(self.path)
        with mock.patch.object(fix.tempfile, 'mkstemp', side_effect=AssertionError('write')):
            result = fix.apply_preview(preview)
        self.assertEqual(result.changes, ())
        self.assertIsNone(result.backup)
        self.assertEqual(self.path.stat().st_mtime_ns, before)
        self.assert_no_outputs()
        self.path.write_bytes(b'[W]\ncell view x=9999\n')
        with self.assertRaises(fix.RepairError):
            fix.apply_preview(preview)
        self.assertFalse(list(self.root.glob('*.bak')))

    def test_preview_preserves_all_supported_encoding_bytes(self):
        for bom, encoding in [(b'', 'utf-8'), (b'\xef\xbb\xbf', 'utf-8'),
                              (b'\xff\xfe', 'utf-16-le'), (b'\xfe\xff', 'utf-16-be')]:
            with self.subTest(encoding=encoding, bom=bom):
                text = '[W]\r\n; café\ncell view x:9999 # keep\rcell view y=NaN'
                data = bom + text.encode(encoding)
                self.path.write_bytes(data)
                preview = fix.preview_repair(self.path)
                self.assertEqual(preview.original, data)
                self.assertEqual(preview.repaired, bom + text.replace('9999', '0').encode(encoding))
                result = fix.apply_preview(preview)
                self.assertEqual(self.path.read_bytes(), preview.repaired)
                self.assertEqual(result.backup.read_bytes(), data)

    def test_invalid_bounds_and_malformed_preview_never_write(self):
        for options in [dict(min_x='NaN'), dict(min_x=2, max_x=1), dict(min_y=0),
                        dict(min_y='', max_y=20), dict(min_y=0, max_y='Infinity')]:
            with self.subTest(options=options), self.assertRaises(fix.RepairError):
                fix.preview_repair(self.path, **options)
            self.assert_no_outputs()
        self.original = b'[W]\ncell view x=9999\nbroken'
        self.path.write_bytes(self.original)
        with self.assertRaises(fix.RepairError):
            fix.preview_repair(self.path)
        self.assert_no_outputs()

    def test_apply_failure_exposes_actual_completed_backup(self):
        preview = fix.preview_repair(self.path)
        with mock.patch.object(fix.os, 'replace', side_effect=PermissionError('replace denied')):
            with self.assertRaises(PermissionError) as failure:
                fix.apply_preview(preview)
        self.assertEqual(failure.exception.backup.read_bytes(), self.original)
        self.assertEqual(self.path.read_bytes(), self.original)
        self.assertFalse(list(self.root.glob('*.tmp')))

    def test_cleanup_failure_retains_backup_and_untouched_source(self):
        preview = fix.preview_repair(self.path)
        real_unlink = Path.unlink

        def unlink(path, *, missing_ok=False):
            if path.suffix == '.tmp':
                raise OSError(errno.EIO, 'temporary cleanup failed')
            return real_unlink(path, missing_ok=missing_ok)

        with mock.patch.object(fix.os, 'replace', side_effect=PermissionError('replace denied')):
            with mock.patch.object(Path, 'unlink', unlink):
                with self.assertRaises(OSError) as failure:
                    fix.apply_preview(preview)
        self.assertEqual(failure.exception.errno, errno.EIO)
        self.assertEqual(failure.exception.backup.read_bytes(), self.original)
        self.assertEqual(self.path.read_bytes(), self.original)
        self.assertEqual([path.read_bytes() for path in self.root.glob('*.tmp')],
                         [preview.repaired])

    @unittest.skipUnless(os.name == 'nt', 'Windows read-only attribute semantics')
    def test_readonly_replacement_failure_retains_backup_and_cleans_temporary(self):
        self.path.chmod(0o444)
        self.addCleanup(self.path.chmod, 0o600)
        preview = fix.preview_repair(self.path)
        with self.assertRaises(PermissionError) as failure:
            fix.apply_preview(preview)
        self.assertEqual(failure.exception.backup.read_bytes(), self.original)
        self.assertEqual(self.path.read_bytes(), self.original)
        self.assertFalse(list(self.root.glob('*.tmp')))

    def test_explicit_empty_cli_path_never_repairs_the_default_file(self):
        default = self.root / 'CreationKitPrefs.ini'
        default.write_bytes(self.original)
        before = {path.name: path.read_bytes() for path in self.root.iterdir()}
        cli = subprocess.run([sys.executable, fix.__file__, ''], cwd=self.root,
                             capture_output=True, text=True)
        self.assertEqual(cli.returncode, 1)
        self.assertEqual({path.name: path.read_bytes() for path in self.root.iterdir()}, before)

    def test_cli_import_and_repair_work_without_tkinter(self):
        script = Path(fix.__file__).absolute()
        code = f'''import builtins, sys
original_import = builtins.__import__
def guarded(name, *args, **kwargs):
    if name == "tkinter" or name.startswith("tkinter."):
        raise ImportError("Tk deliberately unavailable")
    return original_import(name, *args, **kwargs)
builtins.__import__ = guarded
sys.path.insert(0, {str(script.parent)!r})
import CKSingleMonitorFix as fix
sys.exit(fix.main(sys.argv[1:]))
'''
        cli = subprocess.run([sys.executable, '-c', code, str(self.path), '--dry-run'],
                             capture_output=True, text=True)
        self.assertEqual(cli.returncode, 0, cli.stderr)
        gui = subprocess.run([sys.executable, '-c', code, '--gui', str(self.path)],
                             capture_output=True, text=True)
        self.assertEqual(gui.returncode, 1)
        self.assert_no_outputs()

    def test_gui_dry_run_conflict_is_syntax_error_without_io(self):
        cli = subprocess.run([sys.executable, fix.__file__, '--gui', '--dry-run', str(self.path)],
                             capture_output=True, text=True)
        self.assertEqual(cli.returncode, 2)
        self.assert_no_outputs()


if __name__ == '__main__':
    unittest.main()
