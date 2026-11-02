#!/usr/bin/env python3
"""Allocation F: smaller first batches (dispatch first interval, combine first batch) on the packed-combine
+ final-tail candidate. Parent: source-1101-combine-pack-v2. Arms: cand (16/16), dfirst4, cfirst4, both4."""
import copy, hashlib, json, shutil, sys
from pathlib import Path
HERE = Path(__file__).resolve().parent; sys.path.insert(0, str(HERE.parent / 'pipeline_v1')); sys.path.insert(0, str(HERE))
from prepare_first_batch import prepare  # noqa: E402
ROOT = HERE.parents[3]; NEW = ROOT / 'results/deepep_pipeline_20261101'
REMOTE = '/iopsstor/scratch/cscs/zyu/deepep-pipeline-20261030'
out = Path(sys.argv[1]).resolve(); assert not out.exists(), out
parent = NEW / 'source-1101-combine-pack-v2'
shutil.copytree(parent, out, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
prepare(out)
v = json.loads((parent / 'sequence.json').read_text()); T = {g['name']: g for g in v}
snapshot = REMOTE + '/sources/' + out.name
CAND = dict(CXI_EP_PACK_COMBINE='1', CXI_EP_MERGE_FINAL_TAIL='1', CXI_EP_COMBINE_BATCH='16', CXI_EP_UPDATE_INTERVAL='16', CXI_EP_FORWARD_CHUNK='3', CXI_EP_PACK_ROWS='1')
ARMS = {'cand': {}, 'dfirst4': dict(CXI_EP_FIRST_INTERVAL='4'), 'cfirst4': dict(CXI_EP_COMBINE_FIRST_BATCH='4'), 'both4': dict(CXI_EP_FIRST_INTERVAL='4', CXI_EP_COMBINE_FIRST_BATCH='4')}
seq = []
def add(name, tmpl, arm, requires, **env):
    g = copy.deepcopy(T[tmpl]); g['name'] = name; g['snapshot'] = snapshot; g['requires'] = list(requires)
    g['environment'].update(CAND); g['environment'].update(ARMS[arm]); g['environment'].update(env); seq.append(g); return name
base = 8500; ends = {}
for arm in ARMS:
    s = add('%d-%s-irregular-stress' % (base, arm), '7030-both-irregular-stress', arm, [])
    c = add('%d-%s-4k-correctness' % (base + 1, arm), '7031-both-4k-correctness', arm, [s])
    d = add('%d-%s-dropped-correctness' % (base + 2, arm), '7032-both-dropped-correctness', arm, [c])
    ends[arm] = add('%d-%s-sustained16k' % (base + 3, arm), '7033-both-sustained16k', arm, [d]); base += 10
order = [['cand', 'dfirst4', 'cfirst4', 'both4'], ['both4', 'cfirst4', 'dfirst4', 'cand'], ['cfirst4', 'cand', 'both4', 'dfirst4']]
for rep, arms in enumerate(order, 1):
    for pos, arm in enumerate(arms):
        add('%d%d-%s-repeat%d' % (854 + rep - 1, pos, arm, rep), '7043-both-repeat1', arm, list(ends.values()))
known = set()
for g in seq:
    assert g['name'] not in known and all(r in known for r in g['requires']), g['name']; known.add(g['name'])
(out / 'sequence.json').write_text(json.dumps(seq, indent=2) + '\n')
m = json.loads((parent / 'manifest.json').read_text())
m.update(source_parent=str(parent), scope='2026-11-02 allocation F: smaller first dispatch interval / first combine batch on the packed-combine + final-tail candidate; GPU unqualified')
m['files'] = {str(p.relative_to(out)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(out.rglob('*')) if p.is_file() and p.name != 'manifest.json'}
(out / 'manifest.json').write_text(json.dumps(m, indent=2) + '\n')
print(len(seq), 'gates'); print([g['name'] for g in seq]); print(out)
