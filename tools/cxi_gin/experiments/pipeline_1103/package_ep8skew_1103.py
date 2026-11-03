#!/usr/bin/env python3
"""EP8 demo, third job: which traffic quantity the per-layer time follows. The synthetic skew routings
(exact received-row skew 1.2 / 1.6 / 2 / 4 with two destination ranks per token) vary rows per destination
while the bank cases vary little in NIC rows; recording the traffic statistics for every routing (not only
the bank ones) lets the per-layer dispatch and combine times be regressed on NIC rows per source, pair
maximum and rows per destination in one table. Code-identical to its parent except for that recording.

usage: package_ep8skew_1103.py results/deepep_pipeline_20261101/source-1103-ep8skew-v1 --parent source-1103-pad128-v1
"""
import argparse, copy, hashlib, json, shutil, sys
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'pipeline_v1')); sys.path.insert(0, str(HERE))
from package import replace  # noqa: E402
ROOT = HERE.parents[3]; NEW = ROOT / 'results/deepep_pipeline_20261101'
REMOTE = '/iopsstor/scratch/cscs/zyu/deepep-pipeline-20261030'
ap = argparse.ArgumentParser(); ap.add_argument('out', type=Path); ap.add_argument('--parent', default='source-1103-pad128-v1')
a = ap.parse_args(); out = a.out.resolve(); assert not out.exists(), out
parent = NEW / a.parent
shutil.copytree(parent, out, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
shutil.copy2(HERE / 'bank_routing.py', out / 'backend/tests/bank_routing.py')  # ratio guard for all-local routings
f = out / 'backend/tests/ep_benchmark.py'
replace(f, '''    if routing.startswith('bank_'):
        rows=bank_routing.route_matrix(bank_ids,ep).tolist(); nic=bank_routing.nic_rows(bank_ids,ep,rank)
        gathered=[None]*ep; dist.all_gather_object(gathered,(rows,nic))
        case['bank']=dict(forward=bank_f,layer=bank_l,placement=bank_placement,unit=8*bank_f+rank,
            tokens_with_fewer_experts=int((idx<0).any(1).sum().item()),
            **bank_routing.traffic_stats([g[0] for g in gathered],[g[1] for g in gathered]))
''', '''    ids_np=idx.cpu().numpy()
    rows=bank_routing.route_matrix(ids_np,ep).tolist(); nic=bank_routing.nic_rows(ids_np,ep,rank)
    gathered=[None]*ep; dist.all_gather_object(gathered,(rows,nic))
    case['traffic']=bank_routing.traffic_stats([g[0] for g in gathered],[g[1] for g in gathered])
    if routing.startswith('bank_'):
        case['bank']=dict(forward=bank_f,layer=bank_l,placement=bank_placement,unit=8*bank_f+rank,
            tokens_with_fewer_experts=int((idx<0).any(1).sum().item()),**case['traffic'])
''')
changed = sorted(str(p.relative_to(out)) for p in out.rglob('*') if p.is_file() and p.name not in ('sequence.json', 'manifest.json')
                 and '__pycache__' not in p.parts and p.read_bytes() != (parent / p.relative_to(out)).read_bytes())
assert changed == ['backend/tests/bank_routing.py', 'backend/tests/ep_benchmark.py'], changed
X = {g['name']: g for g in json.loads((NEW / 'source-1103-ep8bank-v1/sequence.json').read_text())}
snapshot = REMOTE + '/sources/' + out.name
BANK = ['bank_f%d_l%d_%s' % (f_, l, p) for f_ in (302, 303) for l in (3, 20, 37) for p in ('vanilla', 'greedy', 'random')]
SKEW = ['mixed', 'skew1.2', 'skew1.6', 'skew2', 'skew4', 'local', 'remote', 'uniform']
SETUP, ALLOC = 10, 25 * 60
seq = []; budget = []
def add(name, routing, dtypes, timeout, expected, requires=()):
    g = copy.deepcopy(X['X100-leanb-bank-fp8']); g['name'] = name; g['snapshot'] = snapshot; g['requires'] = list(requires)
    e = g['environment']; e['CXI_EP_ROUTING'] = ' '.join(routing); e['CXI_EP_DTYPES'] = dtypes
    g['timeout_seconds'] = timeout; e['CXI_TEST_TIMEOUT'] = str(timeout - 60)
    seq.append(g); budget.append(expected); return name
add('S100-skews-fp8', SKEW, 'fp8', 420, 200)
add('S101-bank-f302-f303-fp8', BANK, 'fp8', 480, 260)
add('S102-skews-fp8-repeat', SKEW, 'fp8', 300, 150)
add('S103-skews-bf16', SKEW, 'bf16', 300, 150)
t = SETUP
for g, expected in zip(seq, budget):
    remaining = ALLOC - t; fits = g['timeout_seconds'] + 180 < remaining
    print('%-30s start %5.1f min  remaining %4d s  timeout %3d  %s' % (g['name'], t / 60, remaining, g['timeout_seconds'], 'ok' if fits else 'DOES NOT FIT'))
    assert fits, g['name']; t += expected
print('expected end of the last gate: %.1f min of %d' % (t / 60, ALLOC // 60))
(out / 'sequence.json').write_text(json.dumps(seq, indent=2) + '\n')
m = json.loads((parent / 'manifest.json').read_text())
m.update(source_parent=str(parent), scope=f'2026-11-03 EP8 demo job 3: synthetic skew routings and bank forwards 302/303 with traffic statistics recorded for every case; parent {a.parent}')
m['files'] = {str(p.relative_to(out)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(out.rglob('*')) if p.is_file() and p.name != 'manifest.json'}
(out / 'manifest.json').write_text(json.dumps(m, indent=2) + '\n')
print(len(seq), 'gates'); print([g['name'] for g in seq]); print(out)
