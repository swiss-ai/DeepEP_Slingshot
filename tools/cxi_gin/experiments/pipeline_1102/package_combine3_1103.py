#!/usr/bin/env python3
"""Combine levers, round 3 (2026-11-03 evening, submitted as a hedge while round 2 waited in the debug queue):
code-identical to source-1103-combine-v1. The early-tail arms with a one- or two-row first batch at 4K+16K
on the same pair as lean-b, the irregular-token stress of tail1fb1, and the two-row first batch without the
early tail (fb2, 0/0/2) to attribute any 4K gain between the two knobs.

usage: package_combine3_1103.py results/deepep_pipeline_20261101/source-1103-combine-v3 [--prefix D2]
"""
import argparse, copy, hashlib, json, shutil
from pathlib import Path
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]; NEW = ROOT / 'results/deepep_pipeline_20261101'
REMOTE = '/iopsstor/scratch/cscs/zyu/deepep-pipeline-20261030'
ap = argparse.ArgumentParser(); ap.add_argument('out', type=Path); ap.add_argument('--prefix', default='D2')
ap.add_argument('--parent', default='source-1103-combine-v1')
a = ap.parse_args(); out = a.out.resolve(); assert not out.exists(), out
parent = NEW / a.parent
shutil.copytree(parent, out, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
C1 = {g['name']: g for g in json.loads((NEW / 'source-1103-combine-v1/sequence.json').read_text())}
R = {g['name']: g for g in json.loads((NEW / 'source-1103-ringdiag-v1/sequence.json').read_text())}
snapshot = REMOTE + '/sources/' + out.name
ARMS = {'leanb': ('0', '0', '4'), 'tail1fb2': ('1', '0', '2'), 'tail1fb1': ('1', '0', '1'), 'fb2': ('0', '0', '2'), 'fb1': ('0', '0', '1')}
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
CORR, REP, STR = C1['C100-split-4k-correctness'], C1['C103-leanb-repeat2'], R['9A15-ats-irregular-stress']
assert STR['environment']['CXI_EP_TOKENS'] == '32 257' and STR['environment']['CXI_EP_SEEDS'] == '1 2 3'
P = a.prefix
# Each arm's kernels are rebuilt in this job (4K and 16K instances): 300 s for the 4K+16K repeat gates.
add(f'{P}0-tail1fb1-repeat1', REP, 'tail1fb1', [], 300, 200, '4096 16384')
add(f'{P}1-tail1fb2-repeat1', REP, 'tail1fb2', [], 300, 200, '4096 16384')
add(f'{P}2-leanb-repeat1', REP, 'leanb', [], 300, 200, '4096 16384')
add(f'{P}3-tail1fb1-irregular-stress', STR, 'tail1fb1', [], 420, 160)
c = add(f'{P}4-fb2-4k-correctness', CORR, 'fb2', [], 300, 175)
add(f'{P}5-fb2-repeat2', REP, 'fb2', [c], 150, 70, '4096')
add(f'{P}6-tail1fb1-repeat2', REP, 'tail1fb1', [], 150, 70, '4096')
add(f'{P}7-leanb-repeat2', REP, 'leanb', [], 150, 70, '4096')
t = SETUP; known = set()
for g, expected in zip(seq, budget):
    assert g['name'] not in known and all(r in known for r in g['requires']), g['name']; known.add(g['name'])
    remaining = ALLOC - t; fits = g['timeout_seconds'] + 180 < remaining
    print('%-30s start %5.1f min  remaining %4d s  timeout %3d  %s' % (g['name'], t / 60, remaining, g['timeout_seconds'], 'ok' if fits else 'DOES NOT FIT'))
    assert fits, g['name']; t += expected
print('expected end of the last gate: %.1f min of %d' % (t / 60, ALLOC // 60))
(out / 'sequence.json').write_text(json.dumps(seq, indent=2) + '\n')
m = json.loads((parent / 'manifest.json').read_text())
m.update(source_parent=str(parent), scope='2026-11-03 combine levers round 3: tail1fb1 / tail1fb2 / lean-b at 4K+16K, tail1fb1 irregular stress, fb2 alone with correctness; code-identical to source-1103-combine-v1')
m['files'] = {str(p.relative_to(out)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(out.rglob('*')) if p.is_file() and p.name != 'manifest.json'}
(out / 'manifest.json').write_text(json.dumps(m, indent=2) + '\n')
print(len(seq), 'gates'); print([g['name'] for g in seq]); print(out)
