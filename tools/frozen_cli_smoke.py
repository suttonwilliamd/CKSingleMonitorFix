"""Synthetic-only EXE qualification. Child output is bounded and never reported."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import signal
import struct
import subprocess
import tempfile
import threading
import time

LIMIT = 16384


class WindowsTree:
    """Assign suspended child to kill-on-close Job before any application code runs."""
    def __init__(self, child):
        import ctypes as c
        from ctypes import wintypes as w
        self.c = c
        self.k = c.WinDLL('kernel32', use_last_error=True)
        self.k.CreateJobObjectW.restype = w.HANDLE
        self.k.CreateJobObjectW.argtypes = [c.c_void_p, w.LPCWSTR]
        self.k.SetInformationJobObject.argtypes = [w.HANDLE, c.c_int, c.c_void_p, w.DWORD]
        self.k.AssignProcessToJobObject.argtypes = [w.HANDLE, w.HANDLE]
        self.k.QueryInformationJobObject.argtypes = [w.HANDLE, c.c_int, c.c_void_p, w.DWORD, c.c_void_p]
        self.k.CloseHandle.argtypes = [w.HANDLE]
        class Basic(c.Structure):
            _fields_ = [('times', c.c_longlong * 2), ('flags', w.DWORD),
                        ('min', c.c_size_t), ('max', c.c_size_t),
                        ('active', w.DWORD), ('affinity', c.c_size_t),
                        ('priority', w.DWORD), ('scheduling', w.DWORD)]
        class Extended(c.Structure):
            _fields_ = [('basic', Basic), ('io', c.c_ulonglong * 6),
                        ('memory', c.c_size_t * 4)]
        self.handle = self.k.CreateJobObjectW(None, None)
        limits = Extended()
        limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        try:
            if not self.handle or not self.k.SetInformationJobObject(
                    self.handle, 9, c.byref(limits), c.sizeof(limits)):
                raise OSError('job_setup')
            if not self.k.AssignProcessToJobObject(self.handle, int(child._handle)):
                raise OSError('job_assignment')
            resume = c.WinDLL('ntdll').NtResumeProcess
            resume.argtypes = [w.HANDLE]
            resume.restype = c.c_long
            if resume(int(child._handle)) != 0:
                raise OSError('job_resume')
        except BaseException:
            self.close()
            raise

    def empty(self):
        # JOBOBJECT_BASIC_ACCOUNTING_INFORMATION: four LARGE_INTEGERs, four DWORDs.
        data = (self.c.c_ulonglong * 6)()
        if not self.k.QueryInformationJobObject(self.handle, 1, self.c.byref(data), 48, None):
            raise OSError('job_query')
        return struct.unpack_from('I', bytes(data), 40)[0] == 0

    def close(self):
        if self.handle:
            self.k.CloseHandle(self.handle)
            self.handle = None


def run_child(command, cwd, env, timeout=15):
    """Internal test seam accepts fake children; public main never accepts a command."""
    overflow = threading.Event()
    captured = [bytearray(), bytearray()]
    child = subprocess.Popen(command, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             creationflags=4 if os.name == 'nt' else 0,
                             start_new_session=os.name != 'nt')
    tree = None
    threads = []
    def reader(stream, target):
        try:
            while True:
                chunk = stream.read(1024)
                if not chunk:
                    break
                remaining = LIMIT - len(target)
                target.extend(chunk[:remaining])
                if len(chunk) > remaining:
                    overflow.set()
                    break
        finally:
            stream.close()
    expired = False
    clean = False
    try:
        if os.name == 'nt':
            tree = WindowsTree(child)
        for stream, target in zip((child.stdout, child.stderr), captured):
            thread = threading.Thread(target=reader, args=(stream, target), daemon=True)
            thread.start()
            threads.append(thread)
        deadline = time.monotonic() + timeout
        while True:
            exited = child.poll() is not None
            clean = tree.empty() if tree else exited
            if exited and clean and all(not t.is_alive() for t in threads):
                break
            if overflow.is_set() or time.monotonic() >= deadline:
                expired = not overflow.is_set()
                break
            time.sleep(.01)
    finally:
        if tree:
            tree.close()  # kills descendants even if parent already exited
        elif os.name != 'nt':
            try:
                os.killpg(child.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        if child.poll() is None:
            child.kill()
        child.wait(timeout=5)
        for thread in threads:
            thread.join(timeout=2)
        if not threads:
            child.stdout.close()
            child.stderr.close()
    return child.returncode, bytes(captured[0]), bytes(captured[1]), (
        clean and not expired and not overflow.is_set() and all(not t.is_alive() for t in threads))


def pe_amd64(path):
    if path.suffix.lower() != '.exe' or not path.is_file():
        return False
    with path.open('rb') as stream:
        head = stream.read(64)
        if len(head) != 64 or head[:2] != b'MZ':
            return False
        offset = struct.unpack_from('<I', head, 60)[0]
        if offset > path.stat().st_size - 26:
            return False
        stream.seek(offset)
        header = stream.read(26)
        return (header[:6] == b'PE\0\0\x64\x86'
                and struct.unpack_from('<H', header, 22)[0] & 2 != 0
                and header[24:26] == b'\x0b\x02')


def smoke(executable, timeout=15, total=180, results=None, diagnostics=None):
    if results is None:
        results = {}
    deadline = time.monotonic() + total
    with tempfile.TemporaryDirectory(prefix='ck-frozen-') as temporary:
        root = Path(temporary)
        for name in ('cwd', 'profile', 'temp'):
            (root / name).mkdir()
        cwd = root / 'cwd'
        env = {k: os.environ[k] for k in ('SystemRoot', 'WINDIR') if k in os.environ}
        env.update({k: str(root / 'profile') for k in
                    ('HOME', 'USERPROFILE', 'APPDATA', 'LOCALAPPDATA')})
        env.update({k: str(root / 'temp') for k in ('TEMP', 'TMP', 'TMPDIR')})
        known = {p.relative_to(root) for p in root.rglob('*')}
        def inventory():
            return {p.relative_to(root) for p in root.rglob('*')}
        def invoke(name, args, code):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError()
            rc, out, err, healthy = run_child([str(executable)] + args, cwd, env,
                                              min(timeout, remaining))
            results[name] = healthy and rc == code
            if diagnostics is not None:
                # Fixed keys and scalar values only; never retain child output,
                # exception messages, paths, or a parsed arbitrary error class.
                diagnostics[name] = {'rc': rc, 'healthy': healthy,
                                     'unicode_encode_error': b'UnicodeEncodeError' in err}
            return out, err
        out, err = invoke('help', ['--help'], 0)
        results['help'] &= b'--dry-run' in out and not err
        out, err = invoke('syntax', ['--not-an-option'], 2)
        results['syntax'] &= bool(err)
        invoke('missing', ['absent.ini'], 1)
        results['missing'] &= inventory() == known
        bad = cwd / 'malformed.ini'
        bad.write_bytes(b'[broken\ncell view x=9999\n')
        known.add(bad.relative_to(root))
        invoke('malformed', [str(bad)], 1)
        results['malformed'] &= bad.read_bytes() == b'[broken\ncell view x=9999\n' and inventory() == known
        for label, encoding, bom, newline in (
                ('utf8', 'utf-8', b'', '\n'),
                ('utf8_bom', 'utf-8', b'\xef\xbb\xbf', '\r\n'),
                ('utf16_le', 'utf-16-le', b'\xff\xfe', '\r\n'),
                ('utf16_be', 'utf-16-be', b'\xfe\xff', '\n')):
            path = cwd / ('chosen space Ω ' + label + '.ini')
            text = newline.join(('; synthetic Ω', '[Windows]', ' Cell View X = 9999 ; keep',
                                 'render window x: 14', 'objectwindow x= -8', 'other=untouched', ''))
            original = bom + text.encode(encoding)
            # Independent literal byte oracle: no product imports or planner reuse.
            expected = bom + text.replace('9999', '-2.5').replace('= -8', '= -2.5').encode(encoding)
            path.write_bytes(original)
            known.add(path.relative_to(root))
            args = [str(path), '--min-x=-2.5', '--max-x=20.25']
            stamp = path.stat().st_mtime_ns
            invoke(label + '_dry', args + ['--dry-run'], 0)
            results[label + '_dry'] &= (path.read_bytes() == original
                and path.stat().st_mtime_ns == stamp and inventory() == known)
            invoke(label + '_modify', args, 0)
            backups = list(cwd.glob(path.name + '.*.bak'))
            valid = len(backups) == 1 and backups[0].read_bytes() == original
            known.update(p.relative_to(root) for p in backups)
            results[label + '_modify'] &= valid and path.read_bytes() == expected and inventory() == known
            stamp = path.stat().st_mtime_ns
            invoke(label + '_noop', args, 0)
            results[label + '_noop'] &= (path.read_bytes() == expected
                and path.stat().st_mtime_ns == stamp and inventory() == known)
            # Force a second supported modification without rewriting the fixture ourselves.
            invoke(label + '_unique', [str(path), '--min-x=0', '--max-x=10'], 0)
            second = bom + text.replace('9999', '0').replace(': 14', ': 0').replace('= -8', '= 0').encode(encoding)
            newer = set(cwd.glob(path.name + '.*.bak')) - set(backups)
            valid2 = len(newer) == 1 and all(p.read_bytes() == expected for p in newer)
            known.update(p.relative_to(root) for p in newer)
            results[label + '_unique'] &= (valid and valid2 and all(p.read_bytes() == original for p in backups)
                and path.read_bytes() == second and inventory() == known)
        results['isolated_state_clean'] = inventory() == known and not list((root / 'temp').iterdir())
    results['owned_directory_removed'] = not root.exists()
    return results


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('executable', type=Path)
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('--source-sha', required=True)
    args = parser.parse_args(argv)
    report = {'schema': 2, 'status': 'fail', 'cases': {}, 'diagnostics': {}, 'helper_error': True}
    try:
        import re
        import importlib.metadata
        exe = args.executable.resolve()
        if (os.name != 'nt' or platform.machine().lower() not in ('amd64', 'x86_64')
                or not re.fullmatch('[0-9a-f]{40}', args.source_sha) or not pe_amd64(exe)):
            raise ValueError('qualification_platform')
        report.update(source_sha=args.source_sha, python=platform.python_version(),
                      freezer=importlib.metadata.version('pyinstaller'), platform='Windows-AMD64',
                      exe_size=exe.stat().st_size, exe_sha256=hashlib.sha256(exe.read_bytes()).hexdigest())
        smoke(exe, results=report['cases'], diagnostics=report['diagnostics'])
        report['helper_error'] = False
        if report['cases'] and all(report['cases'].values()):
            report['status'] = 'pass'
    except Exception:
        pass  # fixed failure schema, never raw exceptions/paths/output
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    return 0 if report['status'] == 'pass' else 1


if __name__ == '__main__':
    raise SystemExit(main())
