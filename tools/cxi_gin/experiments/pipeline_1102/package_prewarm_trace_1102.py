#!/usr/bin/env python3
"""Traced context prewarm (2026-11-03, 00:10 CET). Job 3838468 showed the prewarm correct on every gate
and without any effect on wall time. Two traced gates on one pair (leanbw = lean-b + CXI_EP_PREWARM_CONTEXTS,
leanb) tell whether the first PUT still costs ~100 us (a load does not warm what the store needs) or whether
the first emission moved earlier without moving the receive end (the convoy is off the critical path).

Parent: source-1102-trace-dbg-v2 (lean trace code, knob-aware validator). Applied:
prepare_prewarm_1102.prepare on both archives (DeepEP.tar.gz and DeepEP-trace.tar.gz) and the backend header.

usage: package_prewarm_trace_1102.py results/deepep_pipeline_20261101/source-1102-prewarm-trace-v1
"""
import copy, hashlib, json, shutil, sys
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'pipeline_v1')); sys.path.insert(0, str(HERE))
from prepare_prewarm_1102 import prepare  # noqa: E402
ROOT = HERE.parents[3]; NEW = ROOT / 'results/deepep_pipeline_20261101'
REMOTE = '/iopsstor/scratch/cscs/zyu/deepep-pipeline-20261030'
out = Path(sys.argv[1]).resolve(); assert not out.exists(), out
parent = NEW / 'source-1102-trace-dbg-v2'; prewarm = NEW / 'source-1102-prewarm-dbg-v1'
shutil.copytree(parent, out, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
prepare(out, archives=('DeepEP.tar.gz', 'DeepEP-trace.tar.gz'))
assert (out / 'backend/device/gin_cxi.cuh').read_bytes() == (prewarm / 'backend/device/gin_cxi.cuh').read_bytes()
assert 'CXI_EP_PREWARM_CONTEXTS' in (out / 'backend/tests/nvcc_wrapper.py').read_text() and 'prewarm_contexts' in (out / 'backend/tests/ep_benchmark.py').read_text()
import tarfile, tempfile
with tempfile.TemporaryDirectory() as d:
    with tarfile.open(out / 'DeepEP-trace.tar.gz') as a: a.extractall(d)
    t = (Path(d) / 'deep_ep/include/deep_ep/common/comm.cuh').read_text()
    assert 'nccl::gin::cxi::prewarm(' in t and 'CXI_EP_PREWARM_CONTEXTS' in t and 'CXI_EP_LOCAL_SELF_SIGNAL' in t
T = {g['name']: g for g in json.loads((parent / 'sequence.json').read_text())}
snapshot = REMOTE + '/sources/' + out.name
seq = []
def trace(name, tmpl, timeout, **env):
    g = copy.deepcopy(T[tmpl]); g['name'] = name; g['snapshot'] = snapshot; g['requires'] = []
    g['environment'].update(env); g['timeout_seconds'] = timeout; g['environment']['CXI_TEST_TIMEOUT'] = str(timeout - 60)
    assert g['qualification'] == 'ep_trace' and g['environment']['CXI_VARIANT'] == 'lean-b-trace'
    seq.append(g)
trace('A000-trace-leanbw-4k', '9902-trace-leanb-4k', 420, CXI_EP_PREWARM_CONTEXTS='1')
trace('A001-trace-leanb-4k', '9902-trace-leanb-4k', 300, CXI_EP_PREWARM_CONTEXTS='0')
trace('A002-trace-leanbw-4k-repeat', '9902-trace-leanb-4k', 300, CXI_EP_PREWARM_CONTEXTS='1')
(out / 'sequence.json').write_text(json.dumps(seq, indent=2) + '\n')
m = json.loads((parent / 'manifest.json').read_text())
m.update(source_parent=str(parent), scope='2026-11-03 traced context prewarm: leanbw vs leanb at 4K on one pair; DeepEP comm.cuh prewarm loop in both archives, backend prewarm helper')
m['files'] = {str(p.relative_to(out)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(out.rglob('*')) if p.is_file() and p.name != 'manifest.json'}
(out / 'manifest.json').write_text(json.dumps(m, indent=2) + '\n')
print(len(seq), 'gates'); print([g['name'] for g in seq]); print(out)
