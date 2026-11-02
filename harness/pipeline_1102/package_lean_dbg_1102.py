#!/usr/bin/env python3
"""Debug-partition companion of source-1102-lean-v1 (identical code, short sequence): the leanb arm's
correctness ladder first, then one cand and one leanb 4K/16K repeat, then the leanb128 stress gate and
repeat, then the kern stress gate. Gate timeouts are shortened so every gate fits the 25-minute
two-node debug allocation (the controller requires timeout + 180 s of remaining time).

usage: package_lean_dbg_1102.py results/deepep_pipeline_20261101/source-1102-lean-dbg-v1
"""
import copy, hashlib, json, shutil, sys
from pathlib import Path
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]; NEW = ROOT / 'results/deepep_pipeline_20261101'
REMOTE = '/iopsstor/scratch/cscs/zyu/deepep-pipeline-20261030'
out = Path(sys.argv[1]).resolve(); assert not out.exists(), out
parent = NEW / 'source-1102-lean-v1'
shutil.copytree(parent, out, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
for path in parent.rglob('*'):
    if path.is_file() and path.name not in ('sequence.json', 'manifest.json') and '__pycache__' not in path.parts:
        assert path.read_bytes() == (out / path.relative_to(parent)).read_bytes(), path
T = {g['name']: g for g in json.loads((parent / 'sequence.json').read_text())}
snapshot = REMOTE + '/sources/' + out.name
seq = []
def add(name, tmpl, timeout, requires):
    g = copy.deepcopy(T[tmpl]); g['name'] = name; g['snapshot'] = snapshot; g['requires'] = list(requires)
    g['timeout_seconds'] = timeout; g['environment']['CXI_TEST_TIMEOUT'] = str(timeout - 60); seq.append(g); return name
s = add('9500-leanb-irregular-stress', '9130-leanb-irregular-stress', 420, [])
c = add('9501-leanb-4k-correctness', '9131-leanb-4k-correctness', 300, [s])
d = add('9502-leanb-dropped-correctness', '9132-leanb-dropped-correctness', 300, [c])
e = add('9503-leanb-sustained16k', '9133-leanb-sustained16k', 360, [d])
add('9504-cand-repeat1', '9200-cand-repeat1', 360, [])
add('9505-leanb-repeat1', '9203-leanb-repeat1', 360, [e])
s128 = add('9506-leanb128-irregular-stress', '9140-leanb128-irregular-stress', 420, [])
add('9507-leanb128-repeat1', '9204-leanb128-repeat1', 360, [s128])
add('9508-kern-irregular-stress', '9110-kern-irregular-stress', 420, [])
known = set()
for g in seq:
    assert g['name'] not in known and all(r in known for r in g['requires']), g['name']; known.add(g['name'])
(out / 'sequence.json').write_text(json.dumps(seq, indent=2) + '\n')
m = json.loads((parent / 'manifest.json').read_text())
m.update(source_parent=str(parent), scope='2026-11-02 debug companion of source-1102-lean-v1: leanb ladder, first cand/leanb/leanb128 timings, kern stress; code identical to source-1102-lean-v1')
m['files'] = {str(p.relative_to(out)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(out.rglob('*')) if p.is_file() and p.name != 'manifest.json'}
(out / 'manifest.json').write_text(json.dumps(m, indent=2) + '\n')
print(len(seq), 'gates; sum of timeouts min =', sum(g['timeout_seconds'] for g in seq) / 60); print([g['name'] for g in seq]); print(out)
