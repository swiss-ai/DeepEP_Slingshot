"""Audit the dispatch-only archive delta and alias the unchanged transport."""
import hashlib
import json
import os
import shutil
import sys
import tarfile
from pathlib import Path

name = sys.argv[1]; assert Path(name).name == name
campaign = Path(__file__).resolve().parent
parent = campaign/'sources/source-zero-packed-v7'; source = campaign/'sources'/name
assert not source.exists() and (campaign/'preflight'/parent.name/'PASS').is_file()
before = json.loads((parent/'manifest.json').read_text())
shutil.copytree(str(parent), str(source), copy_function=os.link,
                ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
allowed = {'DeepEP.tar.gz', 'backend/tests/nvcc_wrapper.py', 'backend/tests/ep_benchmark.py',
           'runner/validate_gate.py', 'sequence.json', 'manifest.json'}
with tarfile.open(str(campaign/(name+'-overlay.tar.gz'))) as archive:
    assert {m.name for m in archive.getmembers()} == allowed
    for member in archive:
        assert member.isfile()
        dest = source/member.name; temp = dest.with_name(dest.name+'.new')
        with temp.open('xb') as file:
            file.write(archive.extractfile(member).read())
        os.chmod(str(temp), member.mode); temp.replace(dest)
after = json.loads((source/'manifest.json').read_text())
assert set(before['files']) == set(after['files'])
assert {k for k in before['files'] if before['files'][k] != after['files'][k]} == allowed-{'manifest.json'}
for root, manifest in [(parent, before), (source, after)]:
    for relative, digest in manifest['files'].items():
        assert hashlib.sha256((root/relative).read_bytes()).hexdigest() == digest, (root, relative)
def archive_files(path):
    with tarfile.open(str(path)) as archive:
        return {str(Path(m.name)):hashlib.sha256(archive.extractfile(m).read()).hexdigest()
                for m in archive if m.isfile()}
a, b = archive_files(parent/'DeepEP.tar.gz'), archive_files(source/'DeepEP.tar.gz')
assert set(a) == set(b)
assert {k for k in a if a[k] != b[k]} == {'deep_ep/include/deep_ep/impls/hybrid_dispatch.cuh'}
runtime = campaign/'runtime'/name
assert not runtime.exists(); runtime.symlink_to(parent.name, target_is_directory=True)
rm = json.loads((runtime/'marker-zero/runtime-manifest.json').read_text())
for relative, digest in rm['files'].items():
    assert hashlib.sha256((runtime/'marker-zero'/relative).read_bytes()).hexdigest() == digest, relative
out = campaign/'preflight'/name; out.mkdir()
(out/'transport-equivalence.json').write_text(json.dumps(dict(parent=parent.name,
    archive_changed=['deep_ep/include/deep_ep/impls/hybrid_dispatch.cuh'],
    scope='Transport and combine unchanged; dispatch compiler/GPU validation pending'), indent=2)+'\n')
(out/'TRANSPORT_PREFLIGHT_PASS').write_text('Exact immutable archive and runtime audit PASS\n')
print('STAGED final tail; no template/GPU qualification yet', name)
