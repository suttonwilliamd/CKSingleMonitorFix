# Windows standalone CLI qualification candidate

This is a build/test path, **not a released or signed binary**. Source usage still
works without dependencies. Building needs Python; the resulting one-file console
EXE is intended to run without a separately installed Python. Only a successful
actual Windows frozen CI job establishes the bounded qualification below. Linux
helper regressions and fake children do not establish frozen acceptance.

## Build (PowerShell, Windows AMD64)

Use a clean checkout of the reviewed commit, Python 3.13 x64, and an isolated venv:

```powershell
py -3.13 -m venv .venv-build
.\.venv-build\Scripts\python.exe -m pip install -r requirements-build.txt
.\.venv-build\Scripts\python.exe -m unittest discover -s tests -v
.\.venv-build\Scripts\python.exe -m PyInstaller --clean --noconfirm CKSingleMonitorFix.spec
```

`PyInstaller==6.16.0` is build-only. Its PyPI metadata declares Python >=3.8,<3.15,
Python 3.13 support, and a win_amd64 wheel. The spec uses no speculative hidden
imports, collect-all hooks, bundled fixtures, runtime hooks, or app changes. UPX
is disabled. Transitive build dependencies are not fully locked; exact freezer,
Python, checked-out SHA and EXE SHA256/size are recorded by qualification. This is
not a reproducible-build claim. PyInstaller must build on Windows, not cross-build
from this Linux workspace.

The spec passes `('X utf8=1', None, 'OPTION')` to `EXE`, the permanent
interpreter option documented by PyInstaller 6.16.0 (spec-files, "Specifying
Python Interpreter Options"). Its bootloader parses `utf8` before interpreter
initialization. This is not an environment-variable workaround: frozen Python
ignores normal `PYTHONUTF8` configuration. It makes piped backup-path diagnostics
Unicode-safe without changing application code. A controlled source regression
shows that a strict cp1252 output pipe can fail *after* the bytes and backup are
correct, whereas UTF-8 succeeds. That analogue supports this packaging fix, but
does not establish the exact cause of the first hosted failure or qualify an EXE.
The original failed report lacked exit/error-class diagnostics.

Fake helper children use only the same `SystemRoot`/`WINDIR` OS allowlist as the
smoke helper, not the full caller environment. CPython 3.9's empty environment
block construction lacks the explicit two-NUL empty-block handling present in
3.13. No timeout, output, descendant or Windows Job checks are relaxed.

## Actual qualification (ephemeral hosted Windows CI only)

The additional job in `.github/workflows/tests.yml` preserves the existing
Ubuntu/Windows Python 3.9/3.13 source matrix. It checks out the exact proposed head,
runs source/helper tests, builds it, then runs `tools/qualify_windows.ps1`.
**Do not run that script on a personal or persistent host:** it creates and removes
one program-scoped outbound firewall deny rule on the ephemeral hosted runner.
It refuses other runner types, requires all firewall profiles already enabled,
and verifies the active rule, direction, scope and exact application filter
before invoking any EXE. Failed enforcement stops qualification. It never enables
profiles or changes host-wide policy. Active-policy inspection is enforcement
configuration evidence, not a network packet-capture experiment.

The helper requires Windows AMD64 and a PE32+ AMD64 executable preflight. It never
uses `python CKSingleMonitorFix.py`, shell commands, canned output or source
fallback as frozen acceptance. Every invocation runs with null stdin and an
allowlisted environment (Windows directory variables plus owned profile/temp),
an isolated cwd/profile/temp, a Windows kill-on-close Job assigned while the
process is suspended, 16 KiB per stdout/stderr stream, 15-second case and
180-second total execution deadlines. Readers bound memory, not an unbounded
capture file. Descendants must exit before a case succeeds; closing the Job
kills owned survivors on failure. Setup/cleanup add bounded overhead. All child
output is discarded after assertions, never copied to the report.

Fixtures are synthetic only; there is no game install/discovery, user INI,
network share, monitor/hardware probing, or real profile input. The independent
literal byte oracle exercises:

- help exit 0 versus syntax exit 2; missing and malformed inputs exit 1 without
  creating input/backups or changing malformed bytes;
- dry-run byte/mtime preservation, no backup;
- real repair with exact expected bytes and exact original unique backup;
- unchanged rerun without rewriting or extra backups;
- a second different repair preserving the first backup and creating a unique
  backup of the intermediate original;
- spaces/Unicode filename, UTF-8 with/without BOM, UTF-16 LE/BE BOMs, LF/CRLF,
  comments/unrelated values, finite decimal custom inclusive bounds;
- no extra fixture/profile/temp/extraction state, no surviving owned process
  state on successful qualification, and removal of the owned test directory.

`frozen-evidence/report.json` is initialized to fixed failure data before install
and retained even on failure (runner cancellation/artifact-service failure can
still prevent upload). Successful reports include exact source/Python/freezer,
platform, EXE size/SHA256, boolean case outcomes. Schema 2 also records each
invocation's integer return code, health boolean and a fixed
`unicode_encode_error` boolean (presence of the literal `UnicodeEncodeError` in
bounded stderr, not proof of exception origin). These diagnostics never influence
the acceptance decision; a repair still requires a healthy exit 0 and all byte,
backup and state oracles. They contain no raw paths,
environment, INI, stdout/stderr or exceptions. Report retention is one day. The
EXE artifact is uploaded for one day **only if all actual cases pass**. There is
no automatic tag, GitHub Release, deployment or publication.

After a successful hosted run, a reviewer can download that exact artifact and
choose a synthetic file explicitly, for example:

```powershell
.\CKSingleMonitorFix.exe '.\synthetic fixtures\chosen Ω.ini' --dry-run
.\CKSingleMonitorFix.exe '.\synthetic fixtures\chosen Ω.ini' --min-x=-2.5 --max-x=20.25
```

No defaults, parser behavior or repair semantics were changed. Do not infer full
ACL/ADS preservation, power-loss guarantees, interprocess locking, Creation Kit
or game/hardware correctness, all Windows versions, signing, certificate trust,
SmartScreen reputation or antivirus acceptance from these tests. The binary is
unsigned; qualification does not make it trusted. Original release/tag/draft
assets remain outside this work. Root review/publication, real hosted acceptance
and a separate release decision are still required.
