#!/usr/bin/env python3
"""Export exact private patches and verify clean-baseline reconstruction.

This does not claim a clean GPU rebuild/rerun. It packages source evidence and
checks patch applicability/content without modifying the developer worktrees.
"""
import argparse
import datetime
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile

from verify_rebuild_inputs import PINS, verify


def git(repo, *args, **kwargs):
    return subprocess.check_output(['git', '-C', str(repo), *args], **kwargs)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def export(repo, revision, destination):
    commit = git(repo, 'rev-parse', 'HEAD').decode().strip()
    if not commit.startswith(revision):
        raise RuntimeError('Unexpected baseline for ' + str(repo) + ': ' + commit)
    git(repo, 'diff', '--check')
    patch = git(repo, 'diff', '--binary', 'HEAD', '--')
    new_files = git(repo, 'ls-files', '--others', '--exclude-standard', '-z').decode().split('\0')
    new_files = [name for name in new_files if name]
    for name in new_files:
        if not (repo / name).is_file() or (repo / name).is_symlink():
            raise RuntimeError('Review non-regular new source: ' + name)
        result = subprocess.run(['git', 'diff', '--no-index', '--binary', '--', '/dev/null', name],
                                cwd=str(repo), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if result.returncode != 1:
            raise RuntimeError('Cannot export new source: ' + name)
        patch += result.stdout
    destination.write_bytes(patch)
    names = git(repo, 'diff', '--name-only', '-z', 'HEAD').decode().split('\0')
    names = sorted(set(name for name in names + new_files if name))
    hashes = {name: sha(repo / name) if (repo / name).exists() else None for name in names}
    with tempfile.TemporaryDirectory(prefix='cxi-reconstruct-') as temp:
        checkout = Path(temp) / 'source'
        subprocess.run(['git', 'clone', '--quiet', '--shared', '--no-checkout', str(repo), str(checkout)], check=True)
        git(checkout, 'checkout', '--quiet', '--detach', commit)
        git(checkout, 'apply', '--check', str(destination))
        git(checkout, 'apply', str(destination))
        for name, expected in hashes.items():
            actual = sha(checkout / name) if (checkout / name).exists() else None
            if actual != expected:
                raise RuntimeError('Reconstructed source differs: ' + name)
    return {'baseline_commit': commit, 'patch': destination.name, 'patch_sha256': sha(destination),
            'reconstruction': 'PASS: clean baseline + exported patch reproduces all changed/new files',
            'changed_files_sha256': hashes}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--destination', type=Path, required=True)
    parser.add_argument('--fmt-archive', type=Path,
                        help='Include all three pinned rebuild archives; supply the already verified fmt git archive')
    args = parser.parse_args()
    destination = args.destination.resolve()
    if destination.exists():
        raise SystemExit('Destination must be new; prior bundles stay immutable')
    backend = Path(__file__).resolve().parents[1]
    source_root = backend.parent
    # Validate mirrored host/device source before producing a partial bundle.
    headers = source_root / 'nccl-cxi-dev/src/include/nccl_device/gin/cxi'
    for relative in ['include/cxi_gin_abi.h', 'include/cassini_user_defs.h',
                     'device/cxi_primitives.cuh', 'device/gin_cxi.cuh']:
        path = backend / relative
        if sha(path) != sha(headers / path.name):
            raise RuntimeError('Mirrored host/device source differs: ' + relative)
    destination.mkdir(parents=True)
    manifest = {'created_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
                'qualification': 'Source reconstruction only; clean GPU rebuild/rerun remains required',
                'repositories': {}}
    for name, revision in [('DeepEP', 'bd1e1669'), ('nccl', '12df1a11afad322be5a204a2db890161cbf8131d')]:
        repo = source_root / (name + '-cxi-dev')
        manifest['repositories'][name] = export(repo, revision, destination / (name + '.patch'))
    shutil.copytree(backend, destination / 'backend',
                    ignore=shutil.ignore_patterns('__pycache__', '*.pyc', '*.so', '*.o'))
    manifest['backend_sha256'] = {
        str(p.relative_to(destination)): sha(p)
        for p in sorted((destination / 'backend').rglob('*')) if p.is_file()}
    abi = headers / 'cxi_gin_abi.h'
    manifest['host_device_abi_sha256'] = sha(abi)
    (destination / 'source-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    if args.fmt_archive:
        # Export base source from the pinned Git objects, never from the dirty
        # worktree. fmt is an explicitly supplied, hash-pinned upstream archive.
        expected_fmt = 'eddee710df7126bb543e97c84d726030ed097202c78bccf3310c796d2646a89f'
        if sha(args.fmt_archive) != expected_fmt:
            raise RuntimeError('Unexpected fmt archive hash')
        inputs = {}
        for name in ['DeepEP', 'nccl']:
            archive = destination / (name + '-base.tar')
            repo = source_root / (name + '-cxi-dev')
            subprocess.run(['git', '-C', str(repo), 'archive', '--format=tar',
                            '--output=' + str(archive), PINS[name]], check=True)
            inputs[name] = dict(commit=PINS[name], archive=archive.name, sha256=sha(archive))
        archive = destination / 'fmt-base.tar'
        shutil.copyfile(args.fmt_archive, archive)
        inputs['fmt'] = dict(commit=PINS['fmt'], archive=archive.name, sha256=sha(archive))
        (destination / 'rebuild-inputs.json').write_text(json.dumps(inputs, indent=2) + '\n')
        verify(destination, sorted(PINS))
    (destination / 'README.md').write_text('''# Experimental direct CXI GIN source bundle

Apply `DeepEP.patch` and `nccl.patch` to the exact commits in
`source-manifest.json` using `git apply --check` followed by `git apply`.
The exporter reconstructed both patches in fresh temporary checkouts and
compared every changed/new file with the worktrees.

`backend/` contains the host plugin, device code, bounded Slurm launcher,
qualification tests and SGLang adapter. Its README documents the experimental
support boundary. Source reconstruction is not a build or GPU correctness pass.
The cluster scripts currently contain site-specific paths; use new isolated
prefixes for a clean rebuild and never overwrite the recorded tested release.
Preserve the vendor license notices in the hardware-definition header.

DeepEP remains at bd1e1669. CXI uses private GIN type 6, not GDAKI type 3.
This bundle is local preparation; no upstream PR has been published.

If `rebuild-inputs.json` is included, all three pinned base archives are bundled.
Before building, run `python3 backend/tools/verify_rebuild_inputs.py .`.
See `backend/docs/reproduce.md` for the site-specific rebuild and qualification
procedure. A complete archive bundle is not a completed clean GPU rerun.
''')
    print(json.dumps({'destination': str(destination),
                      'source_reconstruction': {k: v['reconstruction'] for k, v in manifest['repositories'].items()},
                      'backend_files': len(manifest['backend_sha256'])}, indent=2))


if __name__ == '__main__':
    main()
