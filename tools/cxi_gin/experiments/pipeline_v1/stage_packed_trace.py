"""Install a private trace overlay and runtime without changing any parent inode."""
import hashlib
import importlib.util
import json
import os
import shutil
import sys
import tarfile
from pathlib import Path

name, parent_name = sys.argv[1:]
assert all(Path(x).name == x for x in [name, parent_name])
campaign = Path(__file__).resolve().parent
parent = campaign/'sources'/parent_name
source = campaign/'sources'/name
before = json.loads((parent/'manifest.json').read_text())
assert not source.exists()
shutil.copytree(str(parent), str(source), copy_function=os.link,
                ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
with tarfile.open(str(campaign/(name+'-overlay.tar.gz'))) as archive:
    for member in archive:
        path = Path(member.name)
        assert member.isfile() and not path.is_absolute() and '..' not in path.parts
        dest = source/path
        dest.parent.mkdir(parents=True, exist_ok=True)
        temp = dest.with_name(dest.name+'.overlay-tmp')
        with temp.open('xb') as file:
            file.write(archive.extractfile(member).read())
        os.chmod(str(temp), member.mode)
        temp.replace(dest)
after = json.loads((source/'manifest.json').read_text())
for root, manifest in [(parent, before), (source, after)]:
    for relative, digest in manifest['files'].items():
        assert hashlib.sha256((root/relative).read_bytes()).hexdigest() == digest, (root, relative)
assert before['files']['DeepEP.tar.gz'] == after['files']['DeepEP.tar.gz']
runtime_parent = campaign/'runtime'/parent_name/'marker-zero'
runtime = campaign/'runtime'/name/'marker-zero-trace'
assert not runtime.exists()
shutil.copytree(str(runtime_parent), str(runtime), copy_function=os.link)
device = runtime/'include/nccl_device/gin/cxi'
# These paths alone are changed by instrumentation; first detach their inodes.
for relative in ['cxi_primitives.cuh', 'gin_cxi.cuh', 'device_trace.cuh']:
    path = device/relative
    if not path.exists():
        continue
    temp = path.with_name(path.name+'.private-tmp')
    temp.write_bytes(path.read_bytes())
    temp.replace(path)
spec = importlib.util.spec_from_file_location('private_trace', str(source/'runner/prepare_trace.py'))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
module.prepare_headers(device)
sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
old = json.loads((runtime_parent/'runtime-manifest.json').read_text())
for relative, digest in old['files'].items():
    assert sha(runtime_parent/relative) == digest, relative
manifest = dict(variant='marker-zero-trace', gpu_qualified=False,
    defines=json.loads((source/'variants.json').read_text())['marker-zero-trace'],
    files={str(p.relative_to(runtime)): sha(p) for p in sorted(runtime.rglob('*'))
           if p.is_file() and p.name != 'runtime-manifest.json'})
temp = runtime/'runtime-manifest.new.json'
temp.write_text(json.dumps(manifest, indent=2)+'\n')
temp.replace(runtime/'runtime-manifest.json')
out = campaign/'preflight'/name
out.mkdir()
(out/'staged.json').write_text(json.dumps(dict(parent=parent_name,
    scope='Private trace overlay; ordinary archive and parent runtime unchanged; no compilation/GPU PASS'), indent=2)+'\n')
print('STAGED private tracing; compile and GPU validation pending', name)
