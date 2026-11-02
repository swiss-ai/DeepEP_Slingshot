"""Audit the zero-marker packing derivative and compile without allocating GPUs.

Run on a Clariden login node. This creates a private runtime namespace whose
only variant aliases the byte-identical parent transport; DeepEP is built from
the derivative archive independently by each GPU gate.
"""
import hashlib
import json
import subprocess
import sys
from pathlib import Path


def manifest(root):
    data = json.loads((root / 'manifest.json').read_text())
    for name, digest in data['files'].items():
        assert hashlib.sha256((root / name).read_bytes()).hexdigest() == digest, name
    return data['files']


def main():
    source = Path(sys.argv[1]).resolve()
    checker = Path(sys.argv[2]).resolve()
    campaign = source.parent.parent
    parent = campaign / 'sources/source-marker-probe-v3'
    assert (campaign / 'preflight' / parent.name / 'PASS').is_file()
    before, after = manifest(parent), manifest(source)
    expected_changed = {
        'DeepEP.tar.gz', 'variants.json', 'sequence.json',
        'backend/tests/nvcc_wrapper.py', 'backend/tests/ep_benchmark.py',
        'runner/node.sh', 'runner/validate_gate.py', 'runner/preflight.sh',
    }
    assert {k for k in before if before[k] != after[k]} == expected_changed
    assert set(after) - set(before) == {
        'runner/cxi_packed_channel.cuh', 'runner/test_packed_rows.cc'}
    variants = json.loads((source / 'variants.json').read_text())
    parent_variants = json.loads((parent / 'variants.json').read_text())
    assert variants == {'marker-zero': parent_variants['marker-zero']}
    assert variants['marker-zero']['CXI_ZERO_DELIVERY_MARKER'] == 1
    runtime_parent = campaign / 'runtime' / parent.name / 'marker-zero'
    runtime_manifest = json.loads((runtime_parent / 'runtime-manifest.json').read_text())
    for name, digest in runtime_manifest['files'].items():
        assert hashlib.sha256((runtime_parent / name).read_bytes()).hexdigest() == digest, name
    runtime = campaign / 'runtime' / source.name
    runtime.mkdir(exist_ok=True)
    link = runtime / 'marker-zero'
    if not link.exists():
        link.symlink_to(runtime_parent, target_is_directory=True)
    assert link.resolve() == runtime_parent.resolve()
    out = campaign / 'preflight' / source.name
    out.mkdir(exist_ok=True)
    (out / 'transport-equivalence.json').write_text(json.dumps(dict(
        parent=str(parent), runtime_parent=str(runtime_parent.resolve()),
        changed=sorted(expected_changed), scope='Transport identity only; GPU unqualified'), indent=2)+'\n')
    import os
    env = os.environ.copy()
    env.update(CAMPAIGN=str(campaign), INITIAL_SNAPSHOT=str(source))
    subprocess.check_call(['bash', str(source / 'runner/preflight.sh')], env=env)
    subprocess.check_call([sys.executable, str(checker), str(source),
                           '--transport-parent', parent.name, '--variant', 'marker-zero'])


if __name__ == '__main__':
    main()
