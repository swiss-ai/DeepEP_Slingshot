#!/usr/bin/env python3
"""Traced start-stagger slice (2026-11-03 midday). Parent: source-1103-ringdiag-trace-v1 (lean trace code,
knob-aware validator, ring diagnostic + CXI_RING_ACCESS). Applied: prepare_stagger_1103.prepare on both
DeepEP archives, the nvcc wrapper and ep_benchmark. Gates: stagger 400 ns and 800 ns per channel with the
registered ring, a control, and stagger 400 ns with the ATS ring; all traced at 4K on one pair.
A110 and A111 are also staged into the holder 3835100 (its old controller pauses after every skip-flush
trace gate; resume between them).

usage: package_stagger_trace_1103.py results/deepep_pipeline_20261101/source-1103-stagger-trace-v1
"""
import copy, hashlib, json, shutil, sys, tarfile, tempfile
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'pipeline_v1')); sys.path.insert(0, str(HERE))
from prepare_stagger_1103 import prepare  # noqa: E402
ROOT = HERE.parents[3]; NEW = ROOT / 'results/deepep_pipeline_20261101'
REMOTE = '/iopsstor/scratch/cscs/zyu/deepep-pipeline-20261030'
out = Path(sys.argv[1]).resolve(); assert not out.exists(), out
parent = NEW / 'source-1103-ringdiag-trace-v1'
shutil.copytree(parent, out, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
prepare(out)
changed = sorted(str(p.relative_to(out)) for p in out.rglob('*') if p.is_file() and p.name not in ('sequence.json', 'manifest.json')
                 and '__pycache__' not in p.parts and p.read_bytes() != (parent / p.relative_to(out)).read_bytes())
assert changed == ['DeepEP-trace.tar.gz', 'DeepEP.tar.gz', 'backend/tests/ep_benchmark.py', 'backend/tests/nvcc_wrapper.py'], changed
with tempfile.TemporaryDirectory() as d:
    with tarfile.open(out / 'DeepEP-trace.tar.gz') as a: a.extractall(d)
    t = (Path(d) / 'deep_ep/include/deep_ep/impls/hybrid_dispatch.cuh').read_text()
    assert t.count('CXI_EP_STAGGER_NS') == 7 and '__nanosleep(static_cast<unsigned>(channel_idx) * CXI_EP_STAGGER_NS)' in t and 'ep_trace::' in t
T = {g['name']: g for g in json.loads((parent / 'sequence.json').read_text())}
snapshot = REMOTE + '/sources/' + out.name
seq = []
def trace(name, timeout, **env):
    g = copy.deepcopy(T['A101-trace-leanb-4k']); g['name'] = name; g['snapshot'] = snapshot; g['requires'] = []
    g['environment'].update(env); g['timeout_seconds'] = timeout; g['environment']['CXI_TEST_TIMEOUT'] = str(timeout - 60)
    e = g['environment']
    assert g['qualification'] == 'ep_trace' and e['CXI_VARIANT'] == 'lean-b-trace' and e['CXI_DEVICE_TRACE'] == '1'
    assert e['CXI_EP_SKIP_COMBINE_FLUSH'] == '1' and e['CXI_EP_LOCAL_SELF_SIGNAL'] == '1' and e['CXI_RING_ACCESS'] in ('register', 'ats')
    seq.append(g)
trace('A110-trace-stagger400-4k', 420, CXI_EP_STAGGER_NS='400', CXI_RING_ACCESS='register')
trace('A111-trace-stagger800-4k', 300, CXI_EP_STAGGER_NS='800', CXI_RING_ACCESS='register')
trace('A112-trace-leanb-4k', 300, CXI_EP_STAGGER_NS='0', CXI_RING_ACCESS='register')
trace('A113-trace-stagger400-ats-4k', 300, CXI_EP_STAGGER_NS='400', CXI_RING_ACCESS='ats')
t = 10
for g, expected in zip(seq, [170, 90, 90, 90]):
    remaining = 1500 - t; assert g['timeout_seconds'] + 180 < remaining, g['name']; t += expected
print('expected end %.1f min' % (t / 60))
(out / 'sequence.json').write_text(json.dumps(seq, indent=2) + '\n')
m = json.loads((parent / 'manifest.json').read_text())
m.update(source_parent=str(parent), scope='2026-11-03 traced start stagger of the dispatch channels (CXI_EP_STAGGER_NS 400/800 ns per channel) vs control, registered and ATS rings, 4K on one pair')
m['files'] = {str(p.relative_to(out)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(out.rglob('*')) if p.is_file() and p.name != 'manifest.json'}
(out / 'manifest.json').write_text(json.dumps(m, indent=2) + '\n')
print(len(seq), 'gates'); print([g['name'] for g in seq]); print(out)
