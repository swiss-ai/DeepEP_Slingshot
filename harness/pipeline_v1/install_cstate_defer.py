"""Build private device-header runtimes from a verified zero-marker parent.

Unchanged files are hardlinked. Every changed file is replaced atomically, never
written through the shared inode. No compiled parent or running source changes.
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify(root, name):
    data = json.loads((root / name).read_text())
    for relative, expected in data['files'].items():
        assert digest(root / relative) == expected, (root, relative)
    return data


def replace_file(path, data):
    temporary = path.with_name(path.name + '.new')
    assert not temporary.exists()
    temporary.write_bytes(data)
    temporary.replace(path)


def main():
    source = Path(sys.argv[1]).resolve(); campaign = source.parent.parent
    parent_name=sys.argv[2] if len(sys.argv)>2 else 'source-marker-probe-v3'
    assert Path(parent_name).name==parent_name
    parent = campaign / 'sources'/parent_name
    before = verify(parent, 'manifest.json'); after = verify(source, 'manifest.json')
    assert set(before['files']) == set(after['files'])
    changed = {k for k in before['files'] if before['files'][k] != after['files'][k]}
    assert changed == {'backend/device/cxi_primitives.cuh', 'variants.json', 'runner/preflight.sh', 'sequence.json'}
    parent_runtime = campaign / 'runtime' / parent.name / 'marker-zero'
    runtime_manifest = verify(parent_runtime, 'runtime-manifest.json')
    parent_defines = json.loads((parent / 'variants.json').read_text())['marker-zero']
    assert runtime_manifest['defines'] == parent_defines
    assert digest(parent_runtime / 'lib/libnccl.so.2.32.3') == after['baseline_library_sha256']
    primitive = 'include/nccl_device/gin/cxi/cxi_primitives.cuh'
    prefix = ''.join('#define %s %d\n' % x for x in sorted(parent_defines.items())).encode()
    assert (parent_runtime / primitive).read_bytes() == prefix + (parent / 'backend/device/cxi_primitives.cuh').read_bytes()
    variants = json.loads((source / 'variants.json').read_text())
    target = campaign / 'runtime' / source.name
    assert not target.exists()
    for name, defines in variants.items():
        assert {k:v for k,v in defines.items() if k != 'CXI_DEFER_CSTATE'} == parent_defines
        assert defines['CXI_DEFER_CSTATE'] in (0, 1)
        dest = target / name
        shutil.copytree(str(parent_runtime), str(dest), symlinks=True, copy_function=os.link)
        prefix = ''.join('#define %s %d\n' % x for x in sorted(defines.items())).encode()
        replace_file(dest / primitive, prefix + (source / 'backend/device/cxi_primitives.cuh').read_bytes())
        data = dict(variant=name, gpu_qualified=False, defines=defines,
                    files={str(p.relative_to(dest)):digest(p) for p in sorted(dest.rglob('*'))
                           if p.is_file() and p.name != 'runtime-manifest.json'})
        replace_file(dest / 'runtime-manifest.json', (json.dumps(data, indent=2)+'\n').encode())
        verify(dest, 'runtime-manifest.json')
    assert verify(parent_runtime, 'runtime-manifest.json') == runtime_manifest
    out = campaign / 'preflight' / source.name; out.mkdir(parents=True, exist_ok=True)
    (out / 'runtime-derivation.json').write_text(json.dumps(dict(parent_runtime=str(parent_runtime.resolve()),
        source_parent=str(parent), changed=sorted(changed), parent_unchanged=True,
        scope='Two private runtime headers; unchanged NCCL library/ABI/host/DeepEP; GPU unqualified'), indent=2)+'\n')
    env = os.environ.copy(); env.update(CAMPAIGN=str(campaign), INITIAL_SNAPSHOT=str(source))
    subprocess.check_call(['bash', str(source / 'runner/preflight.sh')], env=env)
    print('PASS CSTATE deferral host/device compile checks; GPU qualification still required', flush=True)


if __name__ == '__main__':
    main()
