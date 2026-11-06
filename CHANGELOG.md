# Changelog

## Unreleased

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
