#!/usr/bin/env python3
"""Allocation A (2026-11-01): fresh qualification plus the full release/re-evaluation matrix for the
qualified packed/interval-16 candidate, as ONE self-contained snapshot sequence.

Parent: results/deepep_pipeline_20261030/source-serving-local-v2 (GPU code, transport and DeepEP
archive byte-identical to source-zero-packed-v7; adds the SGLang local-journal harness).
Only sequence.json and manifest.json change. Every `requires` edge points inside this sequence.
"""
import copy, hashlib, json, shutil, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[4]
OLD = ROOT / 'results/deepep_pipeline_20261030'
REMOTE = '/iopsstor/scratch/cscs/zyu/deepep-pipeline-20261030'
out = Path(sys.argv[1]).resolve(); assert not out.exists(), out
parent = OLD / 'source-serving-local-v2'
shutil.copytree(parent, out, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
v7 = json.loads((OLD / 'source-zero-packed-v7/sequence.json').read_text())
rel = json.loads((OLD / 'prepared-allocation2-release-packed-i16-v2-sequence.json').read_text())
snapshot = REMOTE + '/sources/' + out.name
CAND = dict(CXI_EP_PACK_ROWS='1', CXI_EP_UPDATE_INTERVAL='16', CXI_EP_FORWARD_CHUNK='3',
            CXI_LOCAL_JIT='1', CXI_LOCAL_RESULTS='1', CXI_LOCAL_LOGS='1', CXI_DIAGNOSTIC_WATCHDOG='0')
seq = []
def add(name, template, requires, **env):
    g = copy.deepcopy(template); g['name'] = name; g['snapshot'] = snapshot; g['requires'] = list(requires)
    g['environment'].update(CAND); g['environment'].update(env); seq.append(g); return name
# Fresh qualification of the candidate on this allocation (templates: packed gates of v7).
s = add('6000-fresh-irregular-stress', v7[3], [])
c = add('6001-fresh-4k-correctness', v7[4], [s])
d = add('6002-fresh-dropped-correctness', v7[5], [c])
k = add('6003-fresh-sustained16k', v7[7], [d], CXI_EP_TOKENS='16384', CXI_EP_DTYPES='fp8 bf16', CXI_EP_SEEDS='1 2 3', CXI_EP_NIC_ITERS='0', CXI_REQUIRE_REUSE='1')
reps = [add('600%d-fresh-repeat%d' % (3 + r, r), v7[7], [k]) for r in (1, 2, 3)]
# Release matrix: same gates as the prepared release-v2 sequence, re-pointed and re-wired.
names = {}
for g in rel:
    old = g['name']; num = int(old.split('-')[0]) - 5400
    new = '%d-%s' % (6010 + num, old.split('-', 1)[1]); names[old] = new
for g in rel:
    n = copy.deepcopy(g); n['name'] = names[g['name']]; n['snapshot'] = snapshot
    if n['name'].endswith('-correctness'):
        n['requires'] = [k]
    else:
        n['requires'] = [names[r] for r in g['requires']]
        assert all(r in names.values() for r in n['requires']), n['requires']
    n['environment'].update(CAND); seq.append(n)
known = set()
for g in seq:
    assert g['name'] not in known and all(r in known for r in g['requires']), g['name']; known.add(g['name'])
    assert g['environment']['CXI_VARIANT'] == 'marker-zero' and g['snapshot'] == snapshot
(out / 'sequence.json').write_text(json.dumps(seq, indent=2) + '\n')
m = json.loads((parent / 'manifest.json').read_text())
m.update(source_parent=str(parent), scope='2026-11-01 allocation A: fresh qualification + release/re-evaluation matrix of the packed/I16/129-context candidate; GPU code identical to source-zero-packed-v7')
m['files'] = {str(p.relative_to(out)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(out.rglob('*')) if p.is_file() and p.name != 'manifest.json'}
(out / 'manifest.json').write_text(json.dumps(m, indent=2) + '\n')
print(len(seq), 'gates; total timeout h =', round(sum(g['timeout_seconds'] for g in seq) / 3600, 2)); print(out)
