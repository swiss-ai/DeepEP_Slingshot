#!/usr/bin/env python3
"""Allocation B (2026-11-01): combine packing on the qualified packed/I16 transport.

Parent: results/deepep_pipeline_20261030/source-zero-packed-v7 (marker-zero transport, packed dispatch).
Changes: hybrid_combine.cuh / combine_reduce_epilogue.cuh gain the CXI_EP_PACK_COMBINE path
(prepare_packed_combine.py); hybrid_dispatch.cuh gains the already-prepared CXI_EP_MERGE_FINAL_TAIL
switch (pipeline_v1/prepare_final_tail.py). Both default to 0, so the control arm is the parent.
Arms: control (0/0), combine (1/0), merge (0/1), both (1/1). Correctness matrix per arm, then
three counterbalanced ordinary repeats per arm. Every `requires` edge points inside this sequence.
"""
import copy, hashlib, json, shutil, sys
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'pipeline_v1')); sys.path.insert(0, str(HERE))
from prepare_final_tail import prepare as prepare_final_tail  # noqa: E402
from prepare_packed_combine import prepare as prepare_packed_combine  # noqa: E402
ROOT = HERE.parents[3]
OLD = ROOT / 'results/deepep_pipeline_20261030'
REMOTE = '/iopsstor/scratch/cscs/zyu/deepep-pipeline-20261030'
out = Path(sys.argv[1]).resolve(); assert not out.exists(), out
parent = OLD / 'source-zero-packed-v7'
shutil.copytree(parent, out, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
prepare_final_tail(out)
prepare_packed_combine(out)
shutil.copyfile(HERE / 'test_packed_combine.cc', out / 'runner/test_packed_combine.cc')
pre = out / 'runner/preflight.sh'
t = pre.read_text(); assert t.count('date -Is > "$out/TRANSPORT_PREFLIGHT_PASS"') == 1
pre.write_text(t.replace('date -Is > "$out/TRANSPORT_PREFLIGHT_PASS"', '''g++ -std=c++17 -O2 -Wall -Wextra -Werror -I"$src/runner" "$src/runner/test_packed_combine.cc" -o "$out/packed-combine-model"
"$out/packed-combine-model"
date -Is > "$out/TRANSPORT_PREFLIGHT_PASS"'''))
v7 = json.loads((parent / 'sequence.json').read_text())
snapshot = REMOTE + '/sources/' + out.name
CAND = dict(CXI_EP_PACK_ROWS='1', CXI_EP_UPDATE_INTERVAL='16', CXI_EP_FORWARD_CHUNK='3', CXI_EP_COMBINE_BATCH='16',
            CXI_LOCAL_JIT='1', CXI_LOCAL_RESULTS='1', CXI_LOCAL_LOGS='1', CXI_DIAGNOSTIC_WATCHDOG='0')
ARMS = {'control': ('0', '0'), 'combine': ('1', '0'), 'merge': ('0', '1'), 'both': ('1', '1')}
seq = []
def add(name, template, arm, requires, **env):
    g = copy.deepcopy(template); g['name'] = name; g['snapshot'] = snapshot; g['requires'] = list(requires)
    g['environment'].update(CAND); packc, merge = ARMS[arm]
    g['environment'].update(CXI_EP_PACK_COMBINE=packc, CXI_EP_MERGE_FINAL_TAIL=merge); g['environment'].update(env)
    seq.append(g); return name
base = 7000; ends = {}
for arm in ARMS:
    s = add('%d-%s-irregular-stress' % (base, arm), v7[3], arm, [])
    c = add('%d-%s-4k-correctness' % (base + 1, arm), v7[4], arm, [s])
    d = add('%d-%s-dropped-correctness' % (base + 2, arm), v7[5], arm, [c])
    k = add('%d-%s-sustained16k' % (base + 3, arm), v7[7], arm, [d], CXI_EP_TOKENS='16384', CXI_EP_DTYPES='fp8 bf16',
            CXI_EP_SEEDS='1 2 3', CXI_EP_NIC_ITERS='0', CXI_REQUIRE_REUSE='1')
    ends[arm] = k; base += 10
order = [['control', 'combine', 'merge', 'both'], ['both', 'merge', 'combine', 'control'], ['combine', 'control', 'both', 'merge']]
for rep, arms in enumerate(order, 1):
    for arm in arms:
        add('%d-%s-repeat%d' % (base, arm, rep), v7[7], arm, list(ends.values())); base += 1
known = set()
for g in seq:
    assert g['name'] not in known and all(r in known for r in g['requires']), g['name']; known.add(g['name'])
    assert g['environment']['CXI_VARIANT'] == 'marker-zero' and g['snapshot'] == snapshot
(out / 'sequence.json').write_text(json.dumps(seq, indent=2) + '\n')
m = json.loads((parent / 'manifest.json').read_text())
m.update(source_parent=str(parent), scope='2026-11-01 allocation B: EP8 combine packing (channel-major receive layer, batched PUTs) and dispatch final-tail merge, each as compile-time arms on the byte-identical marker-zero transport; GPU unqualified')
m['files'] = {str(p.relative_to(out)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(out.rglob('*')) if p.is_file() and p.name != 'manifest.json'}
(out / 'manifest.json').write_text(json.dumps(m, indent=2) + '\n')
# Archive delta audit: only the intended DeepEP files change.
import tarfile, tempfile
with tempfile.TemporaryDirectory() as tmp:
    roots = []
    for i, src in enumerate([parent, out]):
        d = Path(tmp) / str(i); d.mkdir(); roots.append(d)
        with tarfile.open(src / 'DeepEP.tar.gz') as a: a.extractall(d)
    before = {str(p.relative_to(roots[0])): hashlib.sha256(p.read_bytes()).hexdigest() for p in roots[0].rglob('*') if p.is_file()}
    after = {str(p.relative_to(roots[1])): hashlib.sha256(p.read_bytes()).hexdigest() for p in roots[1].rglob('*') if p.is_file()}
    assert set(after) - set(before) == {'deep_ep/include/deep_ep/common/cxi_packed_combine.cuh'}, set(after) - set(before)
    changed = {k for k in before if before[k] != after[k]}
    assert changed == {'deep_ep/include/deep_ep/impls/hybrid_combine.cuh', 'deep_ep/include/deep_ep/impls/combine_reduce_epilogue.cuh',
                       'deep_ep/include/deep_ep/impls/hybrid_dispatch.cuh'}, changed
for path in (parent / 'backend').rglob('*'):
    if path.is_file() and path.parent.name in ('device', 'host', 'include'):
        assert path.read_bytes() == (out / path.relative_to(parent)).read_bytes(), path
print(len(seq), 'gates; total timeout h =', round(sum(g['timeout_seconds'] for g in seq) / 3600, 2)); print(out)
