# Offline unsigned Windows release-candidate handoff

`tools/package_release_candidate.py` uses only Python 3.9+ stdlib. It packages an
**explicitly supplied, already-built** `.exe` and two qualification evidence
files. It never builds, executes, downloads, signs, uploads or publishes anything.
It does not alter app behavior, repair tests or workflows. The existing build and
hosted qualification path remains in [windows-frozen-cli.md](windows-frozen-cli.md).
There was no existing ZIP/manifest release packager in that path.

## Required evidence and trust boundary

The operator must obtain the actual qualified EXE from the authorized root's
verified artifact store, plus exact `artifact-verification.json` and `report.json`
bytes. **No real EXE is provisioned in this service workspace. No real release
bundle was produced here.** Local unit-test `.exe` fixtures contain text labelled
synthetic, NOT Windows binaries; passing those tests is not Windows acceptance.

The tool checks explicit expected EXE SHA256/size against bytes, verification and
schema-2 report; report raw-byte SHA256 against verification; source and run IDs;
a successful `windows-frozen-cli` job (and no failed listed jobs); every known
case/diagnostic, health, return code, error flag and case count. Unknown/incomplete
qualification schemas fail closed and need review before support is added.

These are consistency checks, **not signed attestations**. SHA256 does not
establish trust if all inputs were replaced together. Supply evidence and expected
identities from a separately trusted review, not untrusted artifact assertions.
The tool does not inspect PE authenticity or detect signatures. It conservatively
labels the candidate unsigned/not signing-qualified. It neither invokes the EXE
nor claims the binary is runnable. No local absolute paths enter generated
metadata; raw evidence is copied unchanged, so inspect supplied evidence for
sensitive data before any separately authorized sharing.

Use trusted input/output directories, no concurrent writers. Leaf symlinks and
non-regular inputs are refused; parent-directory race/hardlink attacks are not
contained. Inputs are bounded (128 MiB EXE, 1 MiB per evidence file). Output parent
must exist. The output directory must not exist, even if empty; inputs are fully
validated and outputs staged before reserving it. Ordinary copy failure cleans up
the new directory, but interruption/power loss may leave an incomplete directory;
verify checksums and use a fresh directory for a retry. Never treat mere directory
existence as success.

## Exact root-side command for the existing qualified artifact

After independent review/integration of this packaging commit, the **original
root** must provision its downloaded qualified EXE as
`$W/evidence/WIL-132/provisioned/CKSingleMonitorFix.exe` (not a rebuild, and not a
synthetic placeholder). This is a future root action, not performed by the worker.
Keep all approval/recovery/BOARD holds; this local command authorizes no publication.
On the root's Linux workspace, run:

```bash
W=/srv/apps/garfield/company-work/token-burn-20261025
R="$W/repos/ck-release-package-wil132"
# Must name the reviewed packaging commit, not an unreviewed working tree.
PACKAGER_SHA=$(git -C "$R" rev-parse HEAD)
# Operator-supplied real packaging run identifier; never borrow an old run ID.
: "${PAPERCLIP_RUN_ID:?Use the active authorized root run or set an honest local run ID}"
mkdir -p "$W/cache/ck-root-package/home" "$W/cache/ck-root-package/tmp"
HOME="$W/cache/ck-root-package/home" TMPDIR="$W/cache/ck-root-package/tmp" \
PYTHONDONTWRITEBYTECODE=1 python3 "$R/tools/package_release_candidate.py" \
  --exe "$W/evidence/WIL-132/provisioned/CKSingleMonitorFix.exe" \
  --verification "$W/evidence/ck-frozen-passing-ci/artifact-verification.json" \
  --report "$W/evidence/ck-frozen-passing-ci/report.json" \
  --expected-sha256 c7b493555d77066b687e199f1490081026d019b0c6604c5e8a0ec8537e8abeb5 \
  --expected-size 8536232 \
  --source-sha 2fc26d7abdc8cc4104d9939e3ac3e541c7eb0a14 \
  --qualification-run 40296635018 \
  --packager-source "$PACKAGER_SHA" --packaging-run "$PAPERCLIP_RUN_ID" \
  --name CKSingleMonitorFix-windows-amd64-rc1 \
  --output "$W/evidence/WIL-132/CKSingleMonitorFix-windows-amd64-rc1"
# Only after command success:
(cd "$W/evidence/WIL-132/CKSingleMonitorFix-windows-amd64-rc1" && sha256sum -c SHA256SUMS)
```

The trusted report SHA256 for these exact report bytes is
`8d2311a296e7c2c4e4b6d67f029098a442fb6f470e64dbc0dcccb06ce5e20776`.
Qualification source is `2fc26d7abdc8cc4104d9939e3ac3e541c7eb0a14`, not
merge commit `25b3153664d9a3bd0a3e52bd6b2ff790926f47ec` (same integrated tree).
Do not relabel an artifact from a different run/source as this one.

## Output contract and tests

Output is one named portable ZIP, identical sidecar `manifest.json`, and external
`SHA256SUMS` covering ZIP and sidecar. ZIP has one safe ASCII top directory,
`CKSingleMonitorFix.exe`, manifest, raw evidence files, `LIMITS.txt` and internal
`SHA256SUMS` covering every other member. There is no self-referential digest.
Manifest records EXE bytes/hash, source commit, qualification run, evidence hashes,
Python/freezer, packaging implementation commit and packaging run, and explicit
limits. No wall clock or input filenames enter it. ZIP uses sorted members, fixed
1980 timestamp, fixed regular-file mode and stored compression for deterministic
bytes given identical inputs/provenance/name. This is **not** reproducible EXE-build
proof. Portable names refuse traversal, separators, ADS and Windows devices.

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
```

All new tests are synthetic offline packaging tests. They check round-trip bytes,
internal/external hashes, determinism, wrong digest/size, missing/failed/mismatched
evidence, diagnostic types, JSON/path safety, symlink refusal and no overwrite.
Linux tests do not qualify Windows execution or extraction. No EXE is executed.

This output is only an unsigned release candidate for independent review. Existing
old v0.1.0 draft/assets are untouched. Root retains integration/publication and the
stop-before-publication gate. No signing/SmartScreen/AV, general game/device,
ACL/ADS, concurrency or power-loss acceptance is established.
