#!/usr/bin/env python3
"""Combine levers, traced (2026-11-03 afternoon). Parent: source-1103-ringdiag-trace-v1 (lean-b-trace,
knob-aware validator, ring diagnostic). Applied: prepare_combine_1103.prepare on both DeepEP archives, nvcc
wrapper, ep_benchmark. One traced 4K gate per arm on the same pair, for the pre-wire decomposition
(combine_prewire.py: barrier end 131, first local token 134, first PUT 116, kernel end 130).

Arms (CXI_EP_COMBINE_FIRST_TAIL / CXI_EP_COMBINE_SPLIT_BARRIER / CXI_EP_COMBINE_FIRST_BATCH): leanb 0/0/4,
split 0/1/4, both 1/1/4, bothfb2 1/1/2, tail1 1/0/4, bothfb1 1/1/1. Every gate is a new knob set, so every
gate rebuilds the kernels (300 s timeouts).

usage: package_combine_trace_1103.py results/deepep_pipeline_20261101/source-1103-combine-trace-v1
"""
import copy, hashlib, json, shutil, sys
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'pipeline_v1')); sys.path.insert(0, str(HERE))
from prepare_combine_1103 import prepare  # noqa: E402
ROOT = HERE.parents[3]; NEW = ROOT / 'results/deepep_pipeline_20261101'
REMOTE = '/iopsstor/scratch/cscs/zyu/deepep-pipeline-20261030'
out = Path(sys.argv[1]).resolve(); assert not out.exists(), out
parent = NEW / 'source-1103-ringdiag-trace-v1'
shutil.copytree(parent, out, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
prepare(out)
changed = sorted(str(p.relative_to(out)) for p in out.rglob('*') if p.is_file() and p.name not in ('sequence.json', 'manifest.json')
                 and '__pycache__' not in p.parts and p.read_bytes() != (parent / p.relative_to(out)).read_bytes())
assert changed == ['DeepEP-trace.tar.gz', 'DeepEP.tar.gz', 'backend/tests/ep_benchmark.py', 'backend/tests/nvcc_wrapper.py'], changed
T = {g['name']: g for g in json.loads((parent / 'sequence.json').read_text())}
snapshot = REMOTE + '/sources/' + out.name
ARMS = {'leanb': ('0', '0', '4'), 'split': ('0', '1', '4'), 'both': ('1', '1', '4'), 'bothfb2': ('1', '1', '2'),
        'tail1': ('1', '0', '4'), 'bothfb1': ('1', '1', '1')}
seq = []; budget = []
def trace(name, arm, timeout, expected):
    g = copy.deepcopy(T['A101-trace-leanb-4k']); g['name'] = name; g['snapshot'] = snapshot; g['requires'] = []
    e = g['environment']; tail, split, first_batch = ARMS[arm]
    e['CXI_RING_ACCESS'] = 'register'; e['CXI_EP_COMBINE_FIRST_TAIL'] = tail; e['CXI_EP_COMBINE_SPLIT_BARRIER'] = split
    e['CXI_EP_COMBINE_FIRST_BATCH'] = first_batch
    g['timeout_seconds'] = timeout; e['CXI_TEST_TIMEOUT'] = str(timeout - 60)
    assert g['qualification'] == 'ep_trace' and e['CXI_VARIANT'] == 'lean-b-trace' and e['CXI_DEVICE_TRACE'] == '1'
    assert e['CXI_EP_SKIP_COMBINE_FLUSH'] == '1' and e['CXI_EP_LOCAL_SELF_SIGNAL'] == '1' and e['CXI_EP_TOKENS'] == '4096'
    seq.append(g); budget.append(expected)
trace('T100-trace-leanb-4k', 'leanb', 300, 170)
trace('T101-trace-split-4k', 'split', 300, 160)
trace('T102-trace-both-4k', 'both', 300, 160)
trace('T103-trace-bothfb2-4k', 'bothfb2', 300, 160)
trace('T104-trace-tail1-4k', 'tail1', 300, 160)
trace('T105-trace-bothfb1-4k', 'bothfb1', 300, 160)
t = 10
for g, expected in zip(seq, budget):
    remaining = 1500 - t; fits = g['timeout_seconds'] + 180 < remaining
    print('%-26s start %5.1f min  remaining %4d s  %s' % (g['name'], t / 60, remaining, 'ok' if fits else 'DOES NOT FIT'))
    assert fits, g['name']; t += expected
print('expected end %.1f min' % (t / 60))
(out / 'sequence.json').write_text(json.dumps(seq, indent=2) + '\n')
m = json.loads((parent / 'manifest.json').read_text())
m.update(source_parent=str(parent), scope='2026-11-03 combine pre-wire levers, traced at 4K on one pair: lean-b vs first tail after one round, split entry barrier, first batch 2/1')
m['files'] = {str(p.relative_to(out)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(out.rglob('*')) if p.is_file() and p.name != 'manifest.json'}
(out / 'manifest.json').write_text(json.dumps(m, indent=2) + '\n')
print(len(seq), 'gates'); print([g['name'] for g in seq]); print(out)
