#!/usr/bin/env python3
"""Traced ATS ring access (2026-11-03 morning). Gate 9A10 (holder 3835100) showed every command ring
registered as IO memory (266 fallbacks per rank = 133 channels x 2 rings) and the GPU translating through
the host page tables (ATS). This snapshot traces lean-b with CXI_RING_ACCESS=ats against the registered
ring on one pair to see what the first PUT costs when the ring is cacheable system memory.

Parent: source-1102-trace-dbg-v2 (lean trace code, knob-aware validator). Applied: prepare_ringdiag_1103
on the backend host code (diagnostic lines + CXI_RING_ACCESS knob); device code unchanged.

usage: package_ringdiag_trace_1103.py results/deepep_pipeline_20261101/source-1103-ringdiag-trace-v1
"""
import copy, hashlib, json, shutil, sys
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'pipeline_v1')); sys.path.insert(0, str(HERE))
from prepare_ringdiag_1103 import prepare  # noqa: E402
ROOT = HERE.parents[3]; NEW = ROOT / 'results/deepep_pipeline_20261101'
REMOTE = '/iopsstor/scratch/cscs/zyu/deepep-pipeline-20261030'
out = Path(sys.argv[1]).resolve(); assert not out.exists(), out
parent = NEW / 'source-1102-trace-dbg-v2'; diag = NEW / 'source-1103-ringdiag-v1'
shutil.copytree(parent, out, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
prepare(out)
changed = sorted(str(p.relative_to(out)) for p in out.rglob('*') if p.is_file() and p.name not in ('sequence.json', 'manifest.json')
                 and '__pycache__' not in p.parts and p.read_bytes() != (parent / p.relative_to(out)).read_bytes())
assert changed == ['backend/host/cxi_resources.cc'], changed
assert (out / 'backend/host/cxi_resources.cc').read_bytes() == (diag / 'backend/host/cxi_resources.cc').read_bytes()  # same host code as the timing slice
T = {g['name']: g for g in json.loads((parent / 'sequence.json').read_text())}
snapshot = REMOTE + '/sources/' + out.name
seq = []
def trace(name, tmpl, timeout, **env):
    g = copy.deepcopy(T[tmpl]); g['name'] = name; g['snapshot'] = snapshot; g['requires'] = []
    g['environment'].update(env); g['timeout_seconds'] = timeout; g['environment']['CXI_TEST_TIMEOUT'] = str(timeout - 60)
    assert g['qualification'] == 'ep_trace' and g['environment']['CXI_VARIANT'] == 'lean-b-trace' and g['environment']['CXI_DEVICE_TRACE'] == '1'
    assert g['environment']['CXI_EP_SKIP_COMBINE_FLUSH'] == '1' and g['environment']['CXI_EP_LOCAL_SELF_SIGNAL'] == '1'
    seq.append(g)
trace('A100-trace-ats-4k', '9902-trace-leanb-4k', 420, CXI_RING_ACCESS='ats')
trace('A101-trace-leanb-4k', '9902-trace-leanb-4k', 300, CXI_RING_ACCESS='register')
trace('A102-trace-ats-4k-repeat', '9902-trace-leanb-4k', 300, CXI_RING_ACCESS='ats')
t = 10
for g, expected in zip(seq, [170, 90, 90]):
    remaining = 1500 - t; assert g['timeout_seconds'] + 180 < remaining, g['name']; t += expected
print('expected end %.1f min' % (t / 60))
(out / 'sequence.json').write_text(json.dumps(seq, indent=2) + '\n')
m = json.loads((parent / 'manifest.json').read_text())
m.update(source_parent=str(parent), scope='2026-11-03 traced ATS ring access: lean-b-trace with CXI_RING_ACCESS=ats vs register at 4K on one pair; host code of source-1103-ringdiag-v1')
m['files'] = {str(p.relative_to(out)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(out.rglob('*')) if p.is_file() and p.name != 'manifest.json'}
(out / 'manifest.json').write_text(json.dumps(m, indent=2) + '\n')
print(len(seq), 'gates'); print([g['name'] for g in seq]); print(out)
