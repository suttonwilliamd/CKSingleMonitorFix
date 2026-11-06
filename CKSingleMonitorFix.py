"""Conservative, standard-library-only repair of CreationKitPrefs.ini coordinates."""

import argparse
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import os
from pathlib import Path
import re
import stat
import sys
import tempfile

X_KEYS = ('cell view x', 'render window x', 'objectwindow x')
Y_KEYS = ('cell view y', 'render window y', 'objectwindow y')


class RepairError(ValueError):
    """The input cannot safely be repaired."""


@dataclass(frozen=True)
class RepairResult:
    changes: tuple
    backup: Path = None
    dry_run: bool = False


@dataclass(frozen=True)
class RepairPreview:
    """Immutable plan tied to one source snapshot; obtain via preview_repair."""
    path: Path
    changes: tuple
    original: bytes
    repaired: bytes
    identity: tuple


def _number(value):
    try:
        number = Decimal(str(value))
    except InvalidOperation as exc:
        raise RepairError(f'Not a number: {value!r}') from exc
    if not number.is_finite():
        raise RepairError(f'Not a finite number: {value!r}')
    return number


def _limits(minimum, maximum, axis):
    minimum, maximum = _number(minimum), _number(maximum)
    if minimum > maximum:
        raise RepairError(f'min-{axis} must be less than or equal to max-{axis}')
    return minimum, maximum


def _decode(data):
    # BOMs are explicit; guessing legacy code pages would risk corrupting text.
    if data.startswith((b'\xff\xfe\x00\x00', b'\x00\x00\xfe\xff')):
        raise RepairError('UTF-32 is unsupported')
    if data.startswith(b'\xef\xbb\xbf'):
        bom, encoding = b'\xef\xbb\xbf', 'utf-8'
    elif data.startswith(b'\xff\xfe'):
        bom, encoding = b'\xff\xfe', 'utf-16-le'
    elif data.startswith(b'\xfe\xff'):
        bom, encoding = b'\xfe\xff', 'utf-16-be'
    else:
        bom, encoding = b'', 'utf-8'
    try:
        text = data[len(bom):].decode(encoding, errors='strict')
    except UnicodeError as exc:
        raise RepairError('Invalid or unsupported encoding') from exc
    if any((ord(c) < 32 and c not in '\t\r\n') or c in '\x7f\x85\u2028\u2029' for c in text):
        raise RepairError('Unsupported control character (or BOM-less UTF-16)')
    return text, bom, encoding


def _plan(text, ranges):
    """Validate a deliberately narrow INI dialect, replacing only value spans."""
    lines = text.splitlines(keepends=True)
    changes = []
    section = None
    sections = set()
    keys = set()
    for index, line in enumerate(lines):
        body = line.rstrip('\r\n')
        if not body.strip() or body.lstrip().startswith((';', '#')):
            continue
        heading = re.fullmatch(r'\s*\[([^\[\]\r\n]+)\]\s*(?:[;#].*)?', body)
        if heading:
            section = heading.group(1).strip()
            if not section or section.casefold() in sections:
                raise RepairError(f'Empty or duplicate section at line {index + 1}')
            sections.add(section.casefold())
            keys = set()
            continue
        # Indented options are supported, but multiline/continuation values are not.
        option = re.fullmatch(r'([ \t]*)([^=:\[\]\r\n]+?)([ \t]*[=:])(.*)', body)
        if section is None or option is None:
            raise RepairError(f'Malformed or unsupported INI syntax at line {index + 1}')
        key = option.group(2).strip().casefold()
        if not key or key in keys:
            raise RepairError(f'Empty or duplicate key at line {index + 1}')
        keys.add(key)
        if key not in ranges:
            continue
        minimum, maximum = ranges[key]
        raw_value = option.group(4)
        # Inline comments start with ; or # preceded by whitespace.
        comment = re.search(r'[ \t]+[;#]', raw_value)
        value_end = comment.start() if comment else len(raw_value)
        value_part = raw_value[:value_end]
        leading = len(value_part) - len(value_part.lstrip(' \t'))
        value = value_part.strip(' \t')
        try:
            number = _number(value)
            valid = minimum <= number <= maximum
        except RepairError:
            valid = False
        if not valid:
            replacement = str(minimum)
            start = option.start(4) + leading
            lines[index] = line[:start] + replacement + line[start + len(value):]
            changes.append(f'line {index + 1} [{section}] {key}: {value!r} -> {replacement}')
    return ''.join(lines), tuple(changes)


def _write_and_sync(fd, data):
    with os.fdopen(fd, 'wb') as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def _replace(path, original, repaired, mode):
    backup = None
    temporary = None
    # mkstemp uses exclusive creation, never clobbering an earlier backup.
    fd, name = tempfile.mkstemp(prefix=path.name + '.', suffix='.bak', dir=path.parent)
    backup = Path(name)
    try:
        _write_and_sync(fd, original)
    except BaseException:
        backup.unlink(missing_ok=True)
        raise
    try:
        fd, name = tempfile.mkstemp(prefix=path.name + '.', suffix='.tmp', dir=path.parent)
        temporary = Path(name)
        _write_and_sync(fd, repaired)
        os.chmod(temporary, stat.S_IMODE(mode))
        # Best-effort stale-input guard; no portable interprocess locking is claimed.
        if path.is_symlink() or path.read_bytes() != original:
            raise RepairError('Input changed during repair; refusing replacement')
        os.replace(temporary, path)
    except (OSError, RepairError) as exc:
        # A completed backup survives later failure; let UI callers name it.
        exc.backup = backup
        raise
    finally:
        if temporary is not None:
            try:
                try:
                    temporary.unlink(missing_ok=True)
                except PermissionError:
                    if os.name != 'nt':
                        raise
                    # Windows will not delete our read-only failed-repair temp.
                    temporary.chmod(stat.S_IWRITE)
                    temporary.unlink(missing_ok=True)
            except OSError as exc:
                exc.backup = backup
                raise
    return backup


def _identity(info):
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _read_source(path):
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode):
        raise RepairError('Input must be a regular file, not a symlink or directory')
    original = path.read_bytes()
    if _identity(path.lstat()) != _identity(info):
        raise RepairError('Input changed while reading; preview again')
    return original, info


def preview_repair(config_file, *, min_x=0, max_x=1800, min_y=None, max_y=None):
    """Read and plan without writes. Both Y limits are required to opt in."""
    ranges = dict.fromkeys(X_KEYS, _limits(min_x, max_x, 'x'))
    if min_y is not None or max_y is not None:
        if min_y is None or max_y is None:
            raise RepairError('min-y and max-y must be supplied together')
        ranges.update(dict.fromkeys(Y_KEYS, _limits(min_y, max_y, 'y')))
    path = Path(config_file).absolute()
    original, info = _read_source(path)
    text, bom, encoding = _decode(original)
    repaired, changes = _plan(text, ranges)
    return RepairPreview(path, changes, original, bom + repaired.encode(encoding),
                         _identity(info))


def apply_preview(preview):
    """Apply exactly this plan, rejecting a stale source before making a backup.

    This is a best-effort guard, not a portable cross-process lock. Callers must
    keep Creation Kit and other writers closed.
    """
    original, info = _read_source(preview.path)
    if original != preview.original or _identity(info) != preview.identity:
        raise RepairError('Input changed since preview; preview again before applying')
    if not preview.changes:
        return RepairResult(())
    backup = _replace(preview.path, original, preview.repaired, info.st_mode)
    return RepairResult(preview.changes, backup=backup)


def check_and_fix_ranges(config_file, *, dry_run=False, min_x=0, max_x=1800,
                         min_y=None, max_y=None):
    """Repair existing coordinates; return RepairResult or raise on unsafe input.

    X keys use the supplied inclusive range. Y keys are left untouched unless
    both Y limits are provided. Missing keys are never inserted.
    """
    preview = preview_repair(config_file, min_x=min_x, max_x=max_x,
                             min_y=min_y, max_y=max_y)
    if dry_run:
        return RepairResult(preview.changes, dry_run=True)
    return apply_preview(preview)


class RepairWindow:
    """A manual, single-file preview/apply form. Construction never opens an INI."""

    def __init__(self, root, *, path='', min_x='0', max_x='1800',
                 min_y=None, max_y=None):
        import tkinter as tk
        from tkinter import filedialog, ttk

        self.root = root
        self.preview = None
        self.path = tk.StringVar(root, path)
        self.min_x = tk.StringVar(root, str(min_x))
        self.max_x = tk.StringVar(root, str(max_x))
        self.min_y = tk.StringVar(root, '' if min_y is None else str(min_y))
        self.max_y = tk.StringVar(root, '' if max_y is None else str(max_y))
        self.use_y = tk.BooleanVar(root, min_y is not None or max_y is not None)
        frame = ttk.Frame(root, padding=16)
        frame.grid(sticky='nsew')
        root.columnconfigure(0, weight=1)
        root.rowconfigure(0, weight=1)
        frame.columnconfigure(1, weight=1)
        frame.rowconfigure(7, weight=1)
        ttk.Label(frame, text='Close Creation Kit and all other INI writers before Preview / Apply.',
                  foreground='#a02020').grid(row=0, column=0, columnspan=4, sticky='w', pady=(0, 12))
        ttk.Label(frame, text='Existing INI:').grid(row=1, column=0, sticky='w')
        ttk.Entry(frame, textvariable=self.path, width=65).grid(
            row=1, column=1, columnspan=2, sticky='ew', padx=8)

        def browse():
            chosen = filedialog.askopenfilename(
                parent=root, title='Choose one existing INI',
                filetypes=[('INI files', '*.ini'), ('All files', '*')])
            if chosen:
                self.path.set(chosen)  # Do not resolve away a selected symlink.

        ttk.Button(frame, text='Browse...', command=browse).grid(row=1, column=3)
        ttk.Label(frame, text='Inclusive bounds (invalid coordinates reset to the minimum).').grid(
            row=2, column=0, columnspan=4, sticky='w', pady=(12, 4))
        bounds = ttk.Frame(frame)
        bounds.grid(row=3, column=0, columnspan=4, sticky='w')
        for column, (label, variable) in enumerate(
                [('X minimum', self.min_x), ('X maximum', self.max_x)]):
            ttk.Label(bounds, text=label).grid(row=0, column=column * 2, padx=(0, 8))
            ttk.Entry(bounds, textvariable=variable, width=16).grid(
                row=0, column=column * 2 + 1, padx=(0, 16))
        ttk.Checkbutton(frame, text='Also repair Y (both Y bounds required)',
                        variable=self.use_y).grid(row=4, column=0, columnspan=4, sticky='w', pady=8)
        y_bounds = ttk.Frame(frame)
        y_bounds.grid(row=5, column=0, columnspan=4, sticky='w')
        self.y_entries = []
        for column, (label, variable) in enumerate(
                [('Y minimum', self.min_y), ('Y maximum', self.max_y)]):
            ttk.Label(y_bounds, text=label).grid(row=0, column=column * 2, padx=(0, 8))
            entry = ttk.Entry(y_bounds, textvariable=variable, width=16)
            entry.grid(row=0, column=column * 2 + 1, padx=(0, 16))
            self.y_entries.append(entry)
        actions = ttk.Frame(frame)
        actions.grid(row=6, column=0, columnspan=4, sticky='w', pady=12)
        ttk.Button(actions, text='Preview', command=self.make_preview).grid(row=0, column=0)
        self.apply_button = ttk.Button(actions, text='Apply preview', command=self.apply,
                                       state='disabled')
        self.apply_button.grid(row=0, column=1, padx=12)
        self.output = tk.Text(frame, width=88, height=18, wrap='word', state='disabled')
        self.output.grid(row=7, column=0, columnspan=3, sticky='nsew')
        scrollbar = ttk.Scrollbar(frame, orient='vertical', command=self.output.yview)
        scrollbar.grid(row=7, column=3, sticky='ns')
        self.output.configure(yscrollcommand=scrollbar.set)
        for variable in (self.path, self.min_x, self.max_x, self.min_y, self.max_y, self.use_y):
            variable.trace_add('write', self.invalidate)
        self.invalidate()

    def show(self, text):
        self.output.configure(state='normal')
        self.output.delete('1.0', 'end')
        self.output.insert('1.0', text)
        self.output.configure(state='disabled')

    def invalidate(self, *unused):
        self.preview = None
        self.apply_button.configure(state='disabled')
        for entry in self.y_entries:
            entry.configure(state='normal' if self.use_y.get() else 'disabled')
        self.show('No current preview. Choose an existing INI, enter bounds, then click Preview.\n'
                  'Path or bounds edits invalidate the preview. Preview itself writes nothing.')

    def make_preview(self):
        self.preview = None
        self.apply_button.configure(state='disabled')
        try:
            if not self.path.get():
                raise RepairError('Choose or enter one existing INI path')
            limits = dict(min_x=self.min_x.get(), max_x=self.max_x.get())
            if self.use_y.get():
                limits.update(min_y=self.min_y.get(), max_y=self.max_y.get())
            preview = preview_repair(self.path.get(), **limits)
        except (OSError, RepairError) as exc:
            self.show(f'Preview failed: {exc}\nNo files written. Correct the input and preview again.')
            return
        self.preview = preview
        description = (f'File: {preview.path}\n'
                       f'X: {limits["min_x"]} .. {limits["max_x"]}\n'
                       + (f'Y: {limits["min_y"]} .. {limits["max_y"]}\n'
                          if self.use_y.get() else 'Y: untouched (opt-in disabled)\n'))
        if preview.changes:
            self.show(description + '\nProposed repairs (no files written):\n'
                      + '\n'.join(preview.changes)
                      + '\n\nKeep Creation Kit closed. Apply writes only this preview and creates a backup.')
            self.apply_button.configure(state='normal')
        else:
            self.show(description + '\nNo repairs needed; file left untouched. Apply is disabled.')

    def apply(self):
        preview = self.preview
        self.preview = None
        self.apply_button.configure(state='disabled')
        if preview is None:
            return
        try:
            result = apply_preview(preview)
        except (OSError, RepairError) as exc:
            backup = getattr(exc, 'backup', None)
            self.show(f'Apply failed: {exc}\n'
                      + (f'Backup retained: {backup}\n' if backup else 'No backup created.\n')
                      + 'Preview again before any retry. Keep Creation Kit closed.')
            return
        self.show(f'Repaired: {preview.path}\n' + '\n'.join(result.changes)
                  + f'\n\nBackup: {result.backup}\n'
                  'Apply consumed this preview. Preview again to check the current file.\n'
                  'Creation Kit was not opened or contacted.')


def run_gui(*, title='CKSingleMonitorFix — Preview and Apply', **options):
    """Lazily load Tk; opening the form does not read or repair an INI."""
    try:
        import tkinter as tk
    except ImportError as exc:
        print(f'GUI unavailable: Tkinter is not installed ({exc}). Use the CLI instead.',
              file=sys.stderr)
        return 1
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        print(f'GUI unavailable: could not start Tk ({exc}). Use the CLI instead.',
              file=sys.stderr)
        return 1
    try:
        root.title(title)
        RepairWindow(root, **options)
        root.mainloop()
    finally:
        try:
            root.destroy()
        except tk.TclError:
            pass  # The user may already have closed the window.
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('path', nargs='?',
                        help='existing INI path (default: ./CreationKitPrefs.ini)')
    parser.add_argument('--dry-run', action='store_true', help='report only; write nothing')
    parser.add_argument('--min-x', default='0', help='inclusive minimum and reset value (default: 0)')
    parser.add_argument('--max-x', default='1800', help='inclusive maximum (default: 1800)')
    parser.add_argument('--min-y', help='opt-in inclusive Y minimum and reset value; requires --max-y')
    parser.add_argument('--max-y', help='opt-in inclusive Y maximum; requires --min-y')
    parser.add_argument('--gui', action='store_true', help='open the explicit preview/apply window')
    args = parser.parse_args(argv)
    if args.gui:
        if args.dry_run:
            parser.error('--dry-run is CLI-only; the GUI always previews before Apply')
        return run_gui(path=args.path or '', min_x=args.min_x, max_x=args.max_x,
                       min_y=args.min_y, max_y=args.max_y)
    try:
        result = check_and_fix_ranges(
            'CreationKitPrefs.ini' if args.path is None else args.path,
            dry_run=args.dry_run, min_x=args.min_x, max_x=args.max_x,
            min_y=args.min_y, max_y=args.max_y)
    except (OSError, RepairError) as exc:
        print(f'Error: {exc}', file=sys.stderr)
        return 1
    for change in result.changes:
        print(('Would repair ' if result.dry_run else 'Repaired ') + change)
    if result.backup:
        print(f'Backup: {result.backup}')
    elif not result.changes:
        print('No repairs needed; file left untouched.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
