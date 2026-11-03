#!/usr/bin/env python3
"""Combine levers, round 2 (2026-11-03 evening): code-identical to source-1103-combine-v1 (only sequence.json
differs, so launch_debug_1102.py --skip-preflight applies).

Round 1 (job 3843432) showed no wall-time change for tail1, split or both (1.756 → 1.761 / 1.758 / 1.752
ms). The split barrier cannot help here: every node holds one rank of every rail pair, so the node-local
NVLink barrier waits for the slowest pair exactly as the global barrier did. tail1 alone does not move
the first PUT because the first batch still needs four remote rows and the tails after the first come
every three rounds. Round 2 therefore sweeps the first batch with the early tail: tail1fb2 (1/0/2),
tail1fb1 (1/0/1), plus bothfb2 (1/1/2) for comparison with the traced gate, each with 4K correctness
before timing, and lean-b on the same pair.

Arms (CXI_EP_COMBINE_FIRST_TAIL / CXI_EP_COMBINE_SPLIT_BARRIER / CXI_EP_COMBINE_FIRST_BATCH).

usage: package_combine2_1103.py results/deepep_pipeline_20261101/source-1103-combine-v2 [--sweep tail1fb2,tail1fb1,bothfb2] [--prefix D1]
"""
import argparse, copy, hashlib, json, shutil
from pathlib import Path
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]; NEW = ROOT / 'results/deepep_pipeline_20261101'
REMOTE = '/iopsstor/scratch/cscs/zyu/deepep-pipeline-20261030'
ap = argparse.ArgumentParser(); ap.add_argument('out', type=Path)
ap.add_argument('--sweep', default='tail1fb2,tail1fb1,bothfb2'); ap.add_argument('--prefix', default='D1')
ap.add_argument('--parent', default='source-1103-combine-v1')
a = ap.parse_args(); out = a.out.resolve(); assert not out.exists(), out
parent = NEW / a.parent
shutil.copytree(parent, out, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
C1 = {g['name']: g for g in json.loads((NEW / 'source-1103-combine-v1/sequence.json').read_text())}
snapshot = REMOTE + '/sources/' + out.name
ARMS = {'leanb': ('0', '0', '4'), 'tail1': ('1', '0', '4'), 'split': ('0', '1', '4'), 'both': ('1', '1', '4'),
        'bothfb2': ('1', '1', '2'), 'bothfb1': ('1', '1', '1'), 'tail1fb2': ('1', '0', '2'), 'tail1fb1': ('1', '0', '1'),
        'fb2': ('0', '0', '2'), 'fb1': ('0', '0', '1')}
FIRST, EP_4K, SETUP, ALLOC = 175, 70, 10, 25 * 60
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
P = a.prefix; sweep = [s for s in a.sweep.split(',') if s]; n = 0
def nxt():
    global n; s = '%s%X' % (P, n); n += 1; return s
corr = {s: add(f'{nxt()}-{s}-4k-correctness', CORR, s, [], 300, FIRST) for s in sweep}
add(f'{nxt()}-leanb-repeat2', REP, 'leanb', [], 300, FIRST, '4096')
for s in sweep:
    add(f'{nxt()}-{s}-repeat2', REP, s, [corr[s]], 150, EP_4K, '4096')
for s in sweep:
    add(f'{nxt()}-{s}-repeat3', REP, s, [corr[s]], 150, EP_4K, '4096')
add(f'{nxt()}-leanb-repeat3', REP, 'leanb', [], 150, EP_4K, '4096')
t = SETUP; known = set()
for g, expected in zip(seq, budget):
    assert g['name'] not in known and all(r in known for r in g['requires']), g['name']; known.add(g['name'])
    remaining = ALLOC - t; fits = g['timeout_seconds'] + 180 < remaining
    print('%-30s start %5.1f min  remaining %4d s  timeout %3d  %s' % (g['name'], t / 60, remaining, g['timeout_seconds'], 'ok' if fits else 'DOES NOT FIT'))
    assert fits, g['name']; t += expected
print('expected end of the last gate: %.1f min of %d' % (t / 60, ALLOC // 60))
(out / 'sequence.json').write_text(json.dumps(seq, indent=2) + '\n')
m = json.loads((parent / 'manifest.json').read_text())
m.update(source_parent=str(parent), scope=f'2026-11-03 combine levers round 2: first-batch sweep with the early tail {sweep}, correctness before timing, lean-b reference; code-identical to {a.parent}')
m['files'] = {str(p.relative_to(out)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(out.rglob('*')) if p.is_file() and p.name != 'manifest.json'}
(out / 'manifest.json').write_text(json.dumps(m, indent=2) + '\n')
print(len(seq), 'gates'); print([g['name'] for g in seq]); print(out)
