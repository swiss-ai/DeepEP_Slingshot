#!/usr/bin/env python3
"""Allocation J (2026-11-02): hold a two-node allocation with the final qualified candidate while the
lean-signal snapshot is prepared, and measure the candidate on the allocation's node pair as the
in-allocation reference (one irregular-stress gate, three 4K/16K repeat gates).

Parent: source-1101-first-batch-v1 (GPU archive and backend unchanged, asserted file by file).
Gate templates: source-1101-release-h-v1 8800 (fresh irregular stress) and 8804 (repeat).

usage: package_hold_1102.py results/deepep_pipeline_20261101/source-1102-hold-v1
"""
import copy, hashlib, json, shutil, sys
from pathlib import Path
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]; NEW = ROOT / 'results/deepep_pipeline_20261101'
REMOTE = '/iopsstor/scratch/cscs/zyu/deepep-pipeline-20261030'
out = Path(sys.argv[1]).resolve(); assert not out.exists(), out
parent = NEW / 'source-1101-first-batch-v1'; templates = NEW / 'source-1101-release-h-v1'
shutil.copytree(parent, out, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
for path in parent.rglob('*'):
    if path.is_file() and path.name not in ('sequence.json', 'manifest.json') and '__pycache__' not in path.parts:
        assert path.read_bytes() == (out / path.relative_to(parent)).read_bytes(), path
T = {g['name']: g for g in json.loads((templates / 'sequence.json').read_text())}
snapshot = REMOTE + '/sources/' + out.name
seq = []
def add(name, tmpl, requires):
    g = copy.deepcopy(T[tmpl]); g['name'] = name; g['snapshot'] = snapshot; g['requires'] = list(requires); seq.append(g); return name
s = add('9000-cand-irregular-stress', '8800-fresh-irregular-stress', [])
for r in (1, 2, 3):
    add('900%d-cand-repeat%d' % (r, r), '8804-fresh-repeat1', [s])
for g in seq:
    e = g['environment']
    assert e['CXI_EP_FIRST_INTERVAL'] == '4' and e['CXI_EP_COMBINE_FIRST_BATCH'] == '4' and e['CXI_EP_UPDATE_INTERVAL'] == '16' and e['CXI_EP_COMBINE_BATCH'] == '16'
    assert e['CXI_EP_PACK_ROWS'] == '1' and e['CXI_EP_PACK_COMBINE'] == '1' and e['CXI_EP_MERGE_FINAL_TAIL'] == '1' and e['CXI_VARIANT'] == 'marker-zero'
(out / 'sequence.json').write_text(json.dumps(seq, indent=2) + '\n')
m = json.loads((parent / 'manifest.json').read_text())
m.update(source_parent=str(parent), scope='2026-11-02 allocation J: hold the allocation and measure the final candidate (reference for the lean-signal arms); GPU archive and backend identical to source-1101-first-batch-v1')
m['files'] = {str(p.relative_to(out)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(out.rglob('*')) if p.is_file() and p.name != 'manifest.json'}
(out / 'manifest.json').write_text(json.dumps(m, indent=2) + '\n')
print(len(seq), 'gates:', [g['name'] for g in seq]); print(out)
