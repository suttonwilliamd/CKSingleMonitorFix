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

RANGES = {
    'cell view x': (0, 1800),
    'render window x': (0, 1800),
    'objectwindow x': (0, 1800),
}


class RepairError(ValueError):
    """The input cannot safely be repaired."""


@dataclass(frozen=True)
class RepairResult:
    changes: tuple
    backup: Path = None
    dry_run: bool = False


def _number(value):
    try:
        number = Decimal(str(value))
    except InvalidOperation as exc:
        raise RepairError(f'Not a number: {value!r}') from exc
    if not number.is_finite():
        raise RepairError(f'Not a finite number: {value!r}')
    return number


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


def _plan(text, minimum, maximum):
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
        if key not in RANGES:
            continue
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
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return backup


def check_and_fix_ranges(config_file, *, dry_run=False, min_x=0, max_x=1800):
    """Repair an existing file; return RepairResult, raising on unsafe input/I/O.

    Unlike the old function, this never creates missing files, prints, or rewrites
    unchanged files. All known X keys use the supplied inclusive range.
    """
    minimum, maximum = _number(min_x), _number(max_x)
    if minimum > maximum:
        raise RepairError('min-x must be less than or equal to max-x')
    path = Path(config_file).absolute()
    info = path.lstat()  # Missing files fail before any output is created.
    if not stat.S_ISREG(info.st_mode):
        raise RepairError('Input must be a regular file, not a symlink or directory')
    original = path.read_bytes()
    text, bom, encoding = _decode(original)
    repaired, changes = _plan(text, minimum, maximum)
    if not changes or dry_run:
        return RepairResult(changes, dry_run=dry_run)
    backup = _replace(path, original, bom + repaired.encode(encoding), info.st_mode)
    return RepairResult(changes, backup=backup)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('path', nargs='?', default='CreationKitPrefs.ini',
                        help='existing INI path (default: ./CreationKitPrefs.ini)')
    parser.add_argument('--dry-run', action='store_true', help='report only; write nothing')
    parser.add_argument('--min-x', default='0', help='inclusive minimum and reset value (default: 0)')
    parser.add_argument('--max-x', default='1800', help='inclusive maximum (default: 1800)')
    args = parser.parse_args(argv)
    try:
        result = check_and_fix_ranges(args.path, dry_run=args.dry_run,
                                      min_x=args.min_x, max_x=args.max_x)
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
