"""Offline, stdlib-only packaging of explicitly supplied qualified bytes; never executes them."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import tempfile
import zipfile


CASES = {'help', 'syntax', 'missing', 'malformed',
         'isolated_state_clean', 'owned_directory_removed'} | {
    encoding + '_' + action
    for encoding in ('utf8', 'utf8_bom', 'utf16_le', 'utf16_be')
    for action in ('dry', 'modify', 'noop', 'unique')}
INVOCATIONS = CASES - {'isolated_state_clean', 'owned_directory_removed'}
LIMITS = (
    'UNSIGNED RELEASE CANDIDATE - NOT A PUBLIC RELEASE\n'
    'The supplied evidence is cross-checked, not cryptographically authenticated.\n'
    'No executable was run, rebuilt, signed, uploaded or published by this tool.\n'
    'Qualification is limited to the recorded hosted Windows synthetic CLI cases.\n'
    'No general Windows/game/device, ACL/ADS, concurrency, power-loss, antivirus,\n'
    'SmartScreen, signing, reproducible-build or release acceptance is established.\n'
    'Archive determinism is not reproducible-build evidence. Root review and all\n'
    'existing approval/publication gates still apply.\n'
)


class PackagingError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise PackagingError(message)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def sha(value):
    require(isinstance(value, str) and re.fullmatch(r'[0-9a-f]{64}', value),
            'expected a lowercase SHA256')
    return value


def commit(value):
    require(isinstance(value, str) and re.fullmatch(r'[0-9a-f]{40}', value),
            'expected a full lowercase source commit')
    return value


def safe_name(value):
    # A single portable ASCII component; no paths, ADS, trailing dots or device names.
    require(isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,79}', value),
            'unsafe package name')
    require(value.upper() not in {'CON', 'PRN', 'AUX', 'NUL', 'CLOCK$'} |
            {'COM' + str(n) for n in range(10)} | {'LPT' + str(n) for n in range(10)},
            'reserved Windows package name')
    return value


def read_regular(path, maximum):
    path = Path(path)
    require(stat.S_ISREG(path.lstat().st_mode), 'input must be a regular non-symlink file')
    with path.open('rb') as stream:
        data = stream.read(maximum + 1)
    require(len(data) <= maximum, 'input exceeds size limit')
    return data


def parse_evidence(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, 'duplicate JSON key')
            result[key] = value
        return result
    value = json.loads(raw.decode('utf-8-sig'), object_pairs_hook=unique)
    require(isinstance(value, dict), 'evidence must be a JSON object')
    return value


def canonical(value):
    return (json.dumps(value, sort_keys=True, indent=2, ensure_ascii=True,
                       allow_nan=False) + '\n').encode('ascii')


def checksums(members):
    return ''.join(digest(data) + '  ' + name + '\n'
                   for name, data in sorted(members.items())).encode('ascii')


def package(*, exe, verification, report, output, name, expected_sha256,
            expected_size, source_sha, qualification_run, packager_source,
            packaging_run):
    """Inputs are in trusted directories. Refuse existing output; never execute EXE."""
    name = safe_name(name)
    sha(expected_sha256)
    commit(source_sha)
    commit(packager_source)
    require(type(expected_size) is int and 0 < expected_size <= 128 * 1024 * 1024,
            'invalid expected EXE size')
    require(type(qualification_run) is int and qualification_run > 0,
            'invalid qualification run')
    require(isinstance(packaging_run, str) and
            re.fullmatch(r'[A-Za-z0-9_-]{1,100}', packaging_run), 'invalid packaging run')
    require(Path(exe).suffix.lower() == '.exe', 'explicit .exe input required')
    output = Path(output)
    require(not os.path.lexists(output), 'output already exists; refusing overwrite')
    binary = read_regular(exe, 128 * 1024 * 1024)
    require(len(binary) == expected_size and digest(binary) == expected_sha256,
            'EXE size or SHA256 mismatch')
    verification_bytes = read_regular(verification, 1024 * 1024)
    report_bytes = read_regular(report, 1024 * 1024)
    verified = parse_evidence(verification_bytes)
    qualified = parse_evidence(report_bytes)
    require(verified.get('head') == source_sha and
            type(verified.get('run')) is int and verified['run'] == qualification_run,
            'verification source/run mismatch')
    require(verified.get('exeSha256') == expected_sha256 and
            type(verified.get('exeBytes')) is int and verified['exeBytes'] == expected_size,
            'verification EXE mismatch')
    require(verified.get('reportSha256') == digest(report_bytes), 'report digest mismatch')
    jobs = verified.get('jobs')
    require(isinstance(jobs, list) and jobs and
            all(isinstance(job, list) and len(job) == 2 and
                isinstance(job[0], str) and job[1] == 'success' for job in jobs) and
            sum(job[0] == 'windows-frozen-cli' for job in jobs) == 1,
            'missing or unsuccessful Windows qualification job')
    require(type(qualified.get('schema')) is int and qualified['schema'] == 2 and
            qualified.get('status') == 'pass' and qualified.get('helper_error') is False and
            qualified.get('platform') == 'Windows-AMD64', 'not a passing schema 2 Windows report')
    require(qualified.get('source_sha') == source_sha and
            qualified.get('exe_sha256') == expected_sha256 and
            type(qualified.get('exe_size')) is int and qualified['exe_size'] == expected_size,
            'report EXE/source mismatch')
    cases = qualified.get('cases')
    require(isinstance(cases, dict) and set(cases) == CASES and
            all(value is True for value in cases.values()), 'incomplete or failing cases')
    diagnostics = qualified.get('diagnostics')
    require(isinstance(diagnostics, dict) and set(diagnostics) == INVOCATIONS,
            'missing invocation diagnostics')
    for case, entry in diagnostics.items():
        expected_rc = 2 if case == 'syntax' else 1 if case in ('missing', 'malformed') else 0
        require(isinstance(entry, dict) and type(entry.get('rc')) is int and
                entry['rc'] == expected_rc and entry.get('healthy') is True and
                entry.get('unicode_encode_error') is False, 'unhealthy invocation diagnostics')
    require(type(verified.get('actualCasesPassed')) is int and
            verified['actualCasesPassed'] == len(CASES) and
            type(verified.get('healthyInvocations')) is int and
            verified['healthyInvocations'] == len(INVOCATIONS), 'verification counts mismatch')
    for key in ('python', 'freezer'):
        require(isinstance(qualified.get(key), str) and
                re.fullmatch(r'[0-9]+(?:\.[0-9]+){1,3}', qualified[key]), 'missing tool version')
    manifest = canonical({
        'schema': 1, 'kind': 'unsigned-offline-release-candidate', 'name': name,
        'executable': {'path': 'CKSingleMonitorFix.exe', 'sha256': expected_sha256,
                       'bytes': expected_size},
        'source_sha': source_sha, 'qualification_run': qualification_run,
        'packager': {'source_sha': packager_source, 'run': packaging_run},
        'evidence': {'artifact-verification.json': digest(verification_bytes),
                     'report.json': digest(report_bytes)},
        'qualification': {'platform': qualified['platform'], 'cases': len(CASES),
                          'python': qualified['python'], 'freezer': qualified['freezer']},
        'limits': LIMITS.splitlines(),
    })
    members = {'CKSingleMonitorFix.exe': binary, 'manifest.json': manifest,
               'evidence/artifact-verification.json': verification_bytes,
               'evidence/report.json': report_bytes, 'LIMITS.txt': LIMITS.encode('ascii')}
    members['SHA256SUMS'] = checksums(members)
    # Stage completely before claiming a new output directory. No timestamps or
    # local paths enter the archive. ZIP_STORED avoids zlib-version differences.
    with tempfile.TemporaryDirectory(prefix='.ck-package-', dir=output.parent) as temporary:
        stage = Path(temporary)
        archive = stage / (name + '.zip')
        with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_STORED) as bundle:
            for member, data in sorted(members.items()):
                info = zipfile.ZipInfo(name + '/' + member, date_time=(1980, 1, 1, 0, 0, 0))
                info.create_system = 3
                info.external_attr = (stat.S_IFREG | 0o644) << 16
                bundle.writestr(info, data)
        (stage / 'manifest.json').write_bytes(manifest)
        (stage / 'SHA256SUMS').write_bytes(checksums({archive.name: archive.read_bytes(),
                                                   'manifest.json': manifest}))
        output.mkdir()  # exclusive reservation; never replace an existing directory
        try:
            for file in stage.iterdir():
                shutil.copyfile(file, output / file.name)
        except BaseException:
            shutil.rmtree(output)
            raise
    return output


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ('exe', 'verification', 'report', 'output', 'name', 'expected-sha256',
                 'source-sha', 'packager-source', 'packaging-run'):
        parser.add_argument('--' + flag, required=True)
    parser.add_argument('--expected-size', required=True, type=int)
    parser.add_argument('--qualification-run', required=True, type=int)
    args = vars(parser.parse_args(argv))
    try:
        package(**args)
    except (OSError, ValueError) as error:
        parser.exit(1, 'Packaging refused: ' + str(error) + '\n')
    print('Offline unsigned candidate packaged; no execution or publication performed.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
