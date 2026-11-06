# Changelog

## Unreleased

- Add an explicit `--gui` native Tkinter single-file preview/apply form: manual
  path selection, X bounds, opt-in paired Y bounds, read-only exact repair report,
  edit-invalidated and one-attempt Apply, actual backup/error results, and a
  close-Creation-Kit warning. Startup does not read or write an INI; Tk loads only
  when requested, and the existing default CLI/import behavior remains available
  without Tk.
- Share immutable `preview_repair` / `apply_preview` snapshots with the existing
  parser, backup and atomic replacement. Reject source bytes/identity changed
  since Preview before making outputs; preserve no-op and symlink rejection.
  The final concurrent-writer check remains best-effort, not a process lock.
- Add source snapshot/error/encoding/no-write regressions and exercise real
  Windows Tk callbacks/storage, native mouse/keyboard and file selection using
  synthetic TEMP files and fresh screenshots. Successful repair/no-op and
  read-only replacement failure preserve exact backups; this does not qualify
  a rebuilt frozen GUI EXE.
- Keep an explicitly empty CLI path invalid rather than repairing a different
  default file. Retain completed-backup metadata on cleanup failures and remove
  owned Windows read-only temporary files without changing the original INI.

- Add opt-in Y-coordinate repair for existing `cell view y`, `render window y`,
  and `objectwindow y` keys using paired `--min-y` / `--max-y` limits (or Python
  API `min_y` / `max_y`). Each axis resets invalid values to its own minimum.
- Preserve default X-only behavior, supported encodings and untouched bytes,
  no-write dry-runs, unique exact backups, and atomic replacement. Reject
  incomplete, reversed, or non-finite Y limits before any repair or backup.
- Add independent-axis, boundary, opt-in, encoding, invalid-range, missing-key
  and actual source-CLI regressions; document that limits describe origins,
  not detected monitor work areas or whole-window visibility.

## 0.1.0

- Add an import-safe, standard-library CLI for explicitly selected existing
  `CreationKitPrefs.ini` files (correcting the previous README's filename).
- Repair only known X keys, case-insensitively, with configurable finite inclusive
  limits and non-finite/nonnumeric detection. Reset invalid values to the minimum.
- Add a no-write dry-run; preserve supported INI text/encoding and leave unchanged
  files untouched. Reject missing files, malformed syntax, unsupported encoding,
  duplicate keys/sections, and invalid limits.
- Create unique byte-exact backups before sibling-tempfile atomic replacement;
  fail without replacing the input on backup/write failure.
- Retain `check_and_fix_ranges` with a result-returning, exception-based API rather
  than unconditional rewriting/printing; remove the obsolete parser helper.
- Add temporary-fixture unittest regressions and Ubuntu/Windows hosted CI.

This is a source implementation version, not evidence of a published release.
