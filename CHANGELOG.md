# Changelog

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
