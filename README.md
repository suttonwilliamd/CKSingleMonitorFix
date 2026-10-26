# CKSingleMonitorFix v0.1.0

A conservative, standard-library Python CLI for repairing off-screen Creation Kit
window **X coordinates** in an existing `CreationKitPrefs.ini`. The old README
incorrectly named `CreationKit.ini`; the source has always targeted
**CreationKitPrefs.ini**. This is not a general INI formatter, a GUI, or a guarantee
that every window will be visible. It does not change Y coordinates, add missing
keys, detect monitors, or discover game files.

Requires Python **3.9+** (no packages to install). Close Creation Kit first and
choose your file explicitly. Defaults to `CreationKitPrefs.ini` in the current
working directory, **not** an automatically discovered game directory.

A standalone Windows EXE **qualification candidate**, not a release, is documented
in [Windows frozen CLI qualification](docs/windows-frozen-cli.md). Building needs
Python; only a successful actual hosted Windows job qualifies the resulting EXE.

## PowerShell quick start

From the directory containing this script, with Python installed:

```powershell
py -3 --version
# Choose the actual existing file yourself; this is only an example path.
$ini = 'C:\My INI Backups\CreationKitPrefs.ini'
py -3 .\CKSingleMonitorFix.py $ini --dry-run
# Review the proposed repairs before allowing writes:
py -3 .\CKSingleMonitorFix.py $ini
if ($LASTEXITCODE -ne 0) { throw 'Repair failed; read the error above.' }

# Optional: inclusive range for your setup; bad values reset to --min-x.
py -3 .\CKSingleMonitorFix.py $ini --min-x -1920 --max-x 1920 --dry-run
# Or use the explicit current-directory default:
py -3 .\CKSingleMonitorFix.py --dry-run
```

On Ubuntu, substitute `python3` for `py -3`. No administrative privileges are
required except whatever your selected file/directory already requires.

## Exact repair behavior

Only existing keys in `RANGES` are candidates (case-insensitive, in any section):

- `cell view x`
- `render window x`
- `objectwindow x`

Values must be finite numeric values in the inclusive range `0..1800` by default.
Non-numeric, empty, NaN, infinite, and out-of-range values are replaced with the
minimum (`0` by default). Decimals and scientific notation are supported.
Both limits must be finite numbers, with minimum <= maximum. Negative ranges
are allowed. Valid values and all other keys are left alone.

Exit status: **0** for successful repair, unchanged input, or successful dry-run;
**1** for rejected input or I/O failure; **2** for command-line syntax errors.
Dry-run describes proposed changes but does **no writes**, including no backup.
Missing files are errors and are never created. An unchanged file is not rewritten
and has no backup created.

### Preservation and deliberately supported input

Supported encodings: strict UTF-8 (with or without BOM), or UTF-16 LE/BE **with
BOM**. ASCII is also UTF-8. UTF-32, malformed byte sequences, BOM-less UTF-16,
control characters other than tab/CR/LF, and Unicode line separators are rejected.
Legacy code pages are not guessed; convert a separate copy yourself if needed.

The supported INI subset has named `[sections]`, one `key=value` or `key:value`
per line, blank lines, and `;` / `#` whole-line comments. Indented keys are allowed.
Inline value comments start with whitespace followed by `;` or `#`; section
headings may have trailing comments. Bare keys, multiline/continuation values,
duplicate sections (case-insensitive), duplicate keys within a section
(case-insensitive), and malformed structure are rejected before any writes.
Interpolation and inheritance are not performed; `%` strings in unrelated values
are opaque. A missing coordinate key or section is never inserted.

Within this subset, only invalid coordinate value spans are replaced. Other bytes,
comments, ordering, BOM, CRLF/LF/CR line endings (including mixed endings), and
presence/absence of the final newline are preserved. This is intentionally stricter
than the old `ConfigParser` implementation, which normalized the entire file.

### Backup, replacement, and recovery

Before every actual modifying invocation, an exclusively created, uniquely named
sibling `CreationKitPrefs.ini.<random>.bak` receives the exact original bytes and
is flushed/fsynced. Existing backups are never overwritten. A sibling temporary
file receives the repaired bytes, is flushed/fsynced, and is atomically installed
with `os.replace`. The original permission mode is copied to the replacement.
A backup or temporary-write error prevents replacement. An incomplete backup is
removed; a complete backup remains available if subsequent replacement fails.
Temporary files are cleaned up when possible. An error may leave a complete backup;
read the error and inspect the directory before retrying.

For rollback, close Creation Kit, select the **exact backup path printed by the
successful repair**, and explicitly copy it back (this overwrites the repaired
file, so inspect both files first):

```powershell
Copy-Item -LiteralPath 'C:\My INI Backups\CreationKitPrefs.ini.EXACT-RANDOM.bak' -Destination $ini
```

Do not run concurrent writers: a best-effort check refuses a changed input before
replacement, but this is **not** a cross-process locking protocol and a race remains
between check and replace. Symlink/directory inputs are rejected. Do not use this
on hostile/untrusted directories. Atomic replacement is subject to OS/filesystem
semantics and may fail if Windows has the file open. File owner, Windows ACLs,
NTFS alternate streams, timestamps, extended attributes, and power-loss directory
entry durability are **not** guaranteed preserved. Backups are never auto-deleted.

## Python API and development

Importing the module performs no file I/O or printing. The public
`check_and_fix_ranges(path, *, dry_run=False, min_x=0, max_x=1800)` function remains,
but now returns a `RepairResult` (`changes`, `backup`, `dry_run`) rather than printing
and unconditionally rewriting. Invalid input raises `RepairError` (a `ValueError`),
and filesystem failures raise `OSError`. The obsolete `CaseConfigParser` helper
was removed because rewriting through it cannot preserve source formatting.

```powershell
py -3 -m unittest discover -s tests -v
```

All tests use isolated temporary fixtures; none access real game files. GitHub
Actions runs the same standard-library tests on public Ubuntu and Windows hosted
runners. Native Windows results are only established when that workflow is run;
local Linux results do not prove Windows behavior.
