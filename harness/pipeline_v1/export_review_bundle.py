"""Export the actual tested snapshot, not the older development worktree.

Verify a clean pinned DeepEP checkout plus patch and pinned fmt reproduces every
ordinary DeepEP archive file. This is source reconstruction, not a GPU rerun.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile

PIN = 'bd1e1669a9324a4a111e3786658f1a4a43151f1e'
FMT_SHA = 'eddee710df7126bb543e97c84d726030ed097202c78bccf3310c796d2646a89f'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def files(archive):
    result = {}
    with tarfile.open(archive) as stream:
        for member in stream.getmembers():
            if member.isdir():
                continue
            name = member.name.removeprefix('./')
            assert member.isfile() and not Path(name).is_absolute() and '..' not in Path(name).parts, name
            assert name not in result, name
            result[name] = stream.extractfile(member).read()
    return result


def git(repo, *args):
    return subprocess.check_output(['git', '-C', str(repo), *args])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('snapshot', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--repo', type=Path, default=Path('DeepEP'))
    parser.add_argument('--fmt-archive', type=Path, default=Path(
        'results/deepep_direct_10_26/source-bundles/20261027-source-stride-fix/fmt-base.tar'))
    args = parser.parse_args()
    snapshot, output, repo = args.snapshot.resolve(), args.output.resolve(), args.repo.resolve()
    assert not output.exists(), 'Use a new destination; preserve previous bundles'
    manifest = json.loads((snapshot / 'manifest.json').read_text())
    for name, digest in manifest['files'].items():
        assert sha(snapshot / name) == digest, name
    assert git(repo, 'rev-parse', PIN).decode().strip() == PIN
    assert sha(args.fmt_archive) == FMT_SHA
    target = files(snapshot / 'DeepEP.tar.gz')
    fmt = files(args.fmt_archive)
    observed_fmt = {name[len('third-party/fmt/'):]: data for name, data in target.items()
                    if name.startswith('third-party/fmt/')}
    assert observed_fmt == fmt, 'Archive fmt content differs from pinned submodule'
    target_core = {name: data for name, data in target.items() if not name.startswith('third-party/fmt/')}
    with tempfile.TemporaryDirectory(prefix='deepep-review-') as temporary:
        root = Path(temporary)
        checkout = root / 'source'
        subprocess.run(['git', 'clone', '--quiet', '--shared', '--no-checkout', str(repo), str(checkout)], check=True)
        git(checkout, 'checkout', '--quiet', '--detach', PIN)
        tracked = git(checkout, 'ls-files', '-z').decode().split('\0')
        tracked = {name for name in tracked if name and name != 'third-party/fmt'}
        assert tracked <= set(target_core), 'Unexpected removed tracked source'
        for name, data in target_core.items():
            path = checkout / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        new = sorted(set(target_core) - tracked)
        if new:
            git(checkout, 'add', '-N', '--', *new)
        git(checkout, 'diff', '--check')
        patch = git(checkout, 'diff', '--binary', 'HEAD', '--')
        changed = git(checkout, 'diff', '--name-only', 'HEAD').decode().splitlines()
        patch_file = root / 'DeepEP.patch'
        patch_file.write_bytes(patch)
        # Apply to a second, clean checkout; compare every ordinary core file.
        clean = root / 'reconstructed'
        subprocess.run(['git', 'clone', '--quiet', '--shared', '--no-checkout', str(repo), str(clean)], check=True)
        git(clean, 'checkout', '--quiet', '--detach', PIN)
        git(clean, 'apply', '--check', str(patch_file))
        git(clean, 'apply', str(patch_file))
        assert all((clean / name).read_bytes() == data for name, data in target_core.items())
        output.mkdir(parents=True)
        shutil.copyfile(patch_file, output / 'DeepEP.patch')
        git(repo, 'archive', '--format=tar', '--output=' + str(output / 'DeepEP-base.tar'), PIN)
    shutil.copyfile(args.fmt_archive, output / 'fmt-base.tar')
    shutil.copytree(snapshot, output / 'snapshot', ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    record = dict(status='SOURCE_RECONSTRUCTION_PASS', baseline_commit=PIN,
        snapshot=str(snapshot), snapshot_manifest_sha256=sha(snapshot / 'manifest.json'),
        ordinary_archive_sha256=sha(snapshot / 'DeepEP.tar.gz'),
        source_files=len(target), core_files=len(target_core), fmt_files=len(fmt),
        changed_files=changed, changed_files_sha256={name: hashlib.sha256(target[name]).hexdigest() for name in changed},
        baseline_nccl_library_sha256=manifest['baseline_library_sha256'],
        caveat='Source review bundle only; requires the matching private NCCL runtime and CSCS site environment. No new GPU qualification implied.')
    record['files'] = {str(p.relative_to(output)): sha(p) for p in sorted(output.rglob('*')) if p.is_file()}
    (output / 'review-manifest.json').write_text(json.dumps(record, indent=2) + '\n')
    (output / 'README.md').write_text('''# Tested-snapshot source review bundle

`DeepEP.patch` applies to pinned DeepEP bd1e1669. The exporter applied it to
a clean checkout and verified every ordinary source file against the immutable
experiment archive, including the separately pinned fmt submodule. The complete
host plugin, device transport, benchmark and runner are under `snapshot/`.

This is not a standalone installer or a clean GPU rebuild result. The runner
requires the matching private NCCL type-6 host library/device headers, CSCS
container, libcxi interface and job-specific Slingshot service allocation.
`review-manifest.json` records the required library hash. Existing snapshot
documentation contains historical development paths; the current deployment
procedure is `snapshot/runner/install.py` followed by `snapshot/runner/node.sh`
under the bounded retained-allocation executor. Do not invoke it on a login node.

The selected ordinary EP configuration is 64 SMs, 129 contexts,
CXI_EP_UPDATE_INTERVAL=16, CXI_EP_FORWARD_CHUNK=3 and CXI_EP_PACK_ROWS=1.
The marker-zero transport definitions are in snapshot/variants.json. Tracing is
disabled; the private tracing snapshot is separate. GPU submission/completion
uses CXI, not the mlx5/GDAKI implementation, and CPU resource setup/teardown
remains necessary. Combine batching has not been added.

Consult 10_30_DeepEP_v2_Slingshot.md and the immutable gate results for actual
correctness, timing and SGLang qualification. The source bundle does not upgrade
pending checks to passes. No upstream PR or shared installation was changed.
''')
    print(json.dumps({key: record[key] for key in ['status', 'source_files', 'changed_files']}, indent=2))


if __name__ == '__main__':
    main()
