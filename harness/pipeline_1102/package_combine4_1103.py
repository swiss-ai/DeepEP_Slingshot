#!/usr/bin/env python3
"""Combine levers, round 4 (2026-11-03 evening): code-identical to source-1103-combine-v1. Statistics for the
only arm that moved anything, tail1fb2 (first tail after one round, two-row first batch), against lean-b:
alternating 4K repeats (three each) and one 4K+16K gate each, on whatever pair the debug partition grants;
plus the one-row first batch without the early tail (fb1, 0/0/1) with correctness, to tell whether the 4×
slowdown of tail1fb1 (round 2) belongs to the one-row PUT itself.

usage: package_combine4_1103.py results/deepep_pipeline_20261101/source-1103-combine-v4 [--prefix D3]
"""
import argparse, copy, hashlib, json, shutil
from pathlib import Path
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]; NEW = ROOT / 'results/deepep_pipeline_20261101'
REMOTE = '/iopsstor/scratch/cscs/zyu/deepep-pipeline-20261030'
ap = argparse.ArgumentParser(); ap.add_argument('out', type=Path); ap.add_argument('--prefix', default='D3')
ap.add_argument('--parent', default='source-1103-combine-v1')
a = ap.parse_args(); out = a.out.resolve(); assert not out.exists(), out
parent = NEW / a.parent
shutil.copytree(parent, out, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
C1 = {g['name']: g for g in json.loads((NEW / 'source-1103-combine-v1/sequence.json').read_text())}
snapshot = REMOTE + '/sources/' + out.name
ARMS = {'leanb': ('0', '0', '4'), 'tail1fb2': ('1', '0', '2'), 'fb1': ('0', '0', '1')}
SETUP, ALLOC = 10, 25 * 60
seq = []; budget = []
def add(name, tmpl, arm, requires, timeout, expected, tokens=None):
    g = copy.deepcopy(tmpl); g['name'] = name; g['snapshot'] = snapshot; g['requires'] = list(requires)
    e = g['environment']; tail, split, first_batch = ARMS[arm]
    e['CXI_RING_ACCESS'] = 'register'; e['CXI_EP_COMBINE_FIRST_TAIL'] = tail; e['CXI_EP_COMBINE_SPLIT_BARRIER'] = split
    e['CXI_EP_COMBINE_FIRST_BATCH'] = first_batch
    if tokens: e['CXI_EP_TOKENS'] = tokens
    g['timeout_seconds'] = timeout; e['CXI_TEST_TIMEOUT'] = str(timeout - 60)
    assert e['CXI_VARIANT'] == 'lean-b' and e['CXI_EP_SKIP_COMBINE_FLUSH'] == '1' and e['CXI_EP_LOCAL_SELF_SIGNAL'] == '1'
    assert e['CXI_EP_SMS'] == '64' and e['CXI_EP_CONTEXTS'] == '129' and e['CXI_DEVICE_TRACE'] == '0' and g['qualification'] == 'ep'
    assert 'CXI_EP_STAGGER_NS' not in e and e['CXI_EP_PACK_COMBINE'] == '1' and e['CXI_EP_COMBINE_BATCH'] == '16'
    seq.append(g); budget.append(expected); return name
CORR, REP = C1['C100-split-4k-correctness'], C1['C103-leanb-repeat2']
P = a.prefix
# Kernels of both arms are rebuilt here (4K and 16K instances): 300 s for the 4K+16K gates, 200 s for the
# first 4K repeats of the slower pairs (round 2 saw 115 s wall per 4K repeat gate).
add(f'{P}0-tail1fb2-repeat1', REP, 'tail1fb2', [], 300, 200, '4096 16384')
add(f'{P}1-leanb-repeat1', REP, 'leanb', [], 300, 200, '4096 16384')
for i in range(2, 5):
    add(f'{P}{i}-tail1fb2-repeat{i}', REP, 'tail1fb2', [], 200, 80, '4096')
    add(f'{P}{i}-leanb-repeat{i}'.replace(f'{P}{i}-', f'{P}{i}b-'), REP, 'leanb', [], 200, 80, '4096')
c = add(f'{P}6-fb1-4k-correctness', CORR, 'fb1', [], 300, 175)
add(f'{P}7-fb1-repeat2', REP, 'fb1', [c], 200, 90, '4096')
t = SETUP; known = set()
for g, expected in zip(seq, budget):
    assert g['name'] not in known and all(r in known for r in g['requires']), g['name']; known.add(g['name'])
    remaining = ALLOC - t; fits = g['timeout_seconds'] + 180 < remaining
    print('%-30s start %5.1f min  remaining %4d s  timeout %3d  %s' % (g['name'], t / 60, remaining, g['timeout_seconds'], 'ok' if fits else 'DOES NOT FIT'))
    assert fits, g['name']; t += expected
print('expected end of the last gate: %.1f min of %d' % (t / 60, ALLOC // 60))
(out / 'sequence.json').write_text(json.dumps(seq, indent=2) + '\n')
m = json.loads((parent / 'manifest.json').read_text())
m.update(source_parent=str(parent), scope='2026-11-03 combine levers round 4: tail1fb2 vs lean-b, three alternating 4K repeats and one 4K+16K gate each; fb1 alone with correctness; code-identical to source-1103-combine-v1')
m['files'] = {str(p.relative_to(out)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(out.rglob('*')) if p.is_file() and p.name != 'manifest.json'}
(out / 'manifest.json').write_text(json.dumps(m, indent=2) + '\n')
print(len(seq), 'gates'); print([g['name'] for g in seq]); print(out)
