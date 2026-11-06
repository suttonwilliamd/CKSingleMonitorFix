# CKSingleMonitorFix

A conservative, standard-library Python tool for repairing off-screen Creation Kit
window coordinates in an existing `CreationKitPrefs.ini`, with a CLI and an
explicit native Tkinter preview/apply window. **X-coordinate repair is enabled by
default; Y-coordinate repair is opt-in with explicit limits.** The old README
incorrectly named `CreationKit.ini`; the source has always targeted
**CreationKitPrefs.ini**. This is not a general INI formatter or a guarantee that
every window will be visible. It does not add missing keys, detect monitors, or
discover game files.

Requires Python **3.9+** (no packages to install). Close Creation Kit first and
choose your file explicitly. Defaults to `CreationKitPrefs.ini` in the current
working directory, **not** an automatically discovered game directory.

A standalone Windows EXE **qualification candidate**, not a release, is documented
in [Windows frozen CLI qualification](docs/windows-frozen-cli.md). Building needs
Python; only a successful actual hosted Windows job qualifies the resulting EXE.
An [offline release-candidate packager](docs/release-candidate-packaging.md)
can wrap explicitly supplied qualified bytes and evidence; it never executes or
publishes an EXE and does not turn synthetic packaging tests into Windows proof.

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
# Optional: also repair Y coordinates. Supply BOTH limits for your setup.
# These are example coordinate limits, not detected monitor dimensions.
py -3 .\CKSingleMonitorFix.py $ini --min-y 0 --max-y 1079 --dry-run
# Negative coordinates can represent a monitor above the primary display:
py -3 .\CKSingleMonitorFix.py $ini --min-y -1080 --max-y 1079 --dry-run
# Or use the explicit current-directory default:
py -3 .\CKSingleMonitorFix.py --dry-run
```

On Ubuntu, substitute `python3` for `py -3`. No administrative privileges are
required except whatever your selected file/directory already requires.

## Native preview/apply window (Python source)

```powershell
py -3 .\CKSingleMonitorFix.py --gui
# Optional: prefill a chosen path and limits, without reading or repairing it:
py -3 .\CKSingleMonitorFix.py --gui $ini --min-x -1920 --max-x 1919
```

The GUI requires your Python installation's optional **Tkinter/Tcl/Tk** component.
Tk is imported only for `--gui`; importing the module and running the CLI work
without it. If Tk is unavailable or cannot start, the command reports the error
and exits with status 1, without a substitute GUI or automatic repair.

1. **Close Creation Kit and all other writers.** Browse for one existing INI or
   enter its path. Opening the GUI does not read or write the selected INI.
2. Enter inclusive X minimum/maximum. Y is untouched unless you enable **Also
   repair Y** and supply both Y limits. These are coordinates you choose, not
   detected monitor dimensions.
3. Click **Preview**. The read-only report lists the exact proposed repairs by
   line, section, key, old value and replacement. Preview writes nothing.
4. Review the report, then explicitly click **Apply preview**. The result shows
   the actual unique backup path, or the error and any completed retained backup.

Path/range edits (including the Y checkbox) discard the plan and disable Apply.
No-op previews leave Apply disabled and never rewrite the file or make a backup.
Each Apply attempt consumes the preview, including failures: preview again before
retrying. A source whose bytes or observed file identity changed since Preview is
rejected **before any backup or write**. Changes after Apply's initial check still
have the existing best-effort check before replacement; there is no cross-process
lock and a check/replace race remains. Do not run concurrent writers.

Without an explicit path the GUI starts blank; the CLI retains its existing
current-directory default. CLI bounds can prefill the form; `--dry-run` is
CLI-only and cannot be combined with `--gui`. The GUI never discovers game files,
infers monitors, repairs multiple files, restores/deletes backups, or opens
Creation Kit. A source GUI is **not qualification of a new frozen GUI EXE**:
the existing packaging workflow and qualification suite remain CLI-scoped.

## Exact repair behavior

Only the following existing keys are candidates (case-insensitive, in any section):

| Axis | Keys | Enabled range |
| --- | --- | --- |
| X | `cell view x`, `render window x`, `objectwindow x` | `0..1800` by default; set with `--min-x` / `--max-x` |
| Y | `cell view y`, `render window y`, `objectwindow y` | Disabled unless **both** `--min-y` and `--max-y` are supplied |

Each axis uses its own finite, inclusive limits. Non-numeric, empty, NaN, infinite,
and out-of-range values are replaced with that axis's minimum. Decimals and
scientific notation are supported; minimum must be <= maximum and negative ranges
are allowed. Supplying only one Y limit, a non-finite limit, or a reversed range
fails before any repair or backup. Without Y limits, even invalid Y values remain
untouched. Valid values and all other keys are left alone.

Limits describe allowed **window-origin coordinates**, not window sizes. The tool
does not know your display work areas or whether a window fits entirely on-screen.
Choose limits for your setup and inspect the dry-run before repairing.

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

Importing the module performs no file I/O or printing and does not load Tk. The CLI API is:

```python
check_and_fix_ranges(path, *, dry_run=False, min_x=0, max_x=1800,
                     min_y=None, max_y=None)
```

It returns a `RepairResult` (`changes`, `backup`, `dry_run`). Both Y limits must be
provided together to enable Y repair; omitted limits preserve X-only behavior.
Invalid input raises `RepairError` (a `ValueError`), and filesystem failures raise
`OSError`. The obsolete `CaseConfigParser` helper was removed because rewriting
through it cannot preserve source formatting.

For a two-step workflow, `preview_repair(path, *, min_x=0, max_x=1800,
min_y=None, max_y=None)` returns an immutable `RepairPreview` containing the
absolute (not symlink-resolved) path, exact `changes`, original/repaired bytes,
and observed file identity. `apply_preview(preview)` accepts that unchanged plan
and returns `RepairResult`; stale input raises `RepairError` before creating
outputs. Obtain plans through `preview_repair`, rather than constructing them.
Both steps use the same parser and replacement path as the CLI. A later
replacement failure can attach the completed backup path as `exception.backup`;
inspect it before retrying. Plans are in-memory snapshots, not saved permissions,
cross-process locks, or a security boundary for hostile directories.

```powershell
py -3 -m unittest discover -s tests -v
```

All tests use isolated temporary fixtures; none access real game files. GitHub
Actions runs the same standard-library tests on public Ubuntu and Windows hosted
runners. Local Windows source verification on 2026-11-06 used Python 3.15:
76 tests ran: 73 passed, with three symlink cases skipped because creation was
unavailable. Actual CLI subprocess regressions cover dry-run, repair, errors,
explicit-empty-path rejection and operation with Tk deliberately unavailable.
Real Windows Tk 9.0 form callbacks were exercised against disposable TEMP
fixtures: manual path/bounds, paired Y, edit invalidation, invalid bounds,
stale-source rejection with zero outputs, exact UTF-16/BOM/comment/CRLF repair
and backup, repeat no-op, malformed/missing input, and a real locked-file
replacement failure retaining its exact backup.

Independent native mouse/keyboard and file-chooser checks exercised the form,
bounds editing, preview invalidation, Browse and successful repair. A fresh
production `--gui` process also confirmed successful byte-exact repair/no-op and
read-only-input failure with the correct retained backup, original bytes and
read-only attribute preserved, and no temporary file left behind. Fresh screenshots confirmed the
visible states; byte comparisons verified the original backups and exact value
span changes. The broader error matrix above used real toolkit callbacks, not
mocks. No real game files were accessed. This is source evidence, not
qualification of a rebuilt standalone EXE or a guarantee of visibility in
Creation Kit.
