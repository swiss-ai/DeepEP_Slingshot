#!/usr/bin/env python3
"""Debug-partition isolation run (2026-11-02): which change slows the 16K combine? Parent (code):
source-1102-dbuf-v1 (all knobs available, defaults = candidate behaviour). Arms cand, kern (kernel knobs
on marker-zero), leana, leanb, dbuf; one sustained-16K gate per transport arm (correctness + 16K timing)
then one 4K/16K repeat per arm, dbuf last. Shortened timeouts for the 25-minute debug allocation.

usage: package_iso_dbg_1102.py results/deepep_pipeline_20261101/source-1102-iso-dbg-v1
"""
import copy, hashlib, json, shutil, sys
from pathlib import Path
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]; NEW = ROOT / 'results/deepep_pipeline_20261101'
REMOTE = '/iopsstor/scratch/cscs/zyu/deepep-pipeline-20261030'
out = Path(sys.argv[1]).resolve(); assert not out.exists(), out
parent = NEW / 'source-1102-dbuf-v1'
shutil.copytree(parent, out, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
for path in parent.rglob('*'):
    if path.is_file() and path.name not in ('sequence.json', 'manifest.json') and '__pycache__' not in path.parts:
        assert path.read_bytes() == (out / path.relative_to(parent)).read_bytes(), path
T = {g['name']: g for g in json.loads((parent / 'sequence.json').read_text())}
snapshot = REMOTE + '/sources/' + out.name
KERN = dict(CXI_EP_SKIP_COMBINE_FLUSH='1', CXI_EP_LOCAL_SELF_SIGNAL='1')
OFF = dict(CXI_EP_SKIP_COMBINE_FLUSH='0', CXI_EP_LOCAL_SELF_SIGNAL='0', CXI_EP_COMBINE_DOUBLE_TMA='0')
ARMS = {'cand': ('marker-zero', OFF), 'kern': ('marker-zero', dict(OFF, **KERN)), 'leana': ('lean-a', dict(OFF, **KERN)),
        'leanb': ('lean-b', dict(OFF, **KERN)), 'dbuf': ('lean-b', dict(OFF, **KERN, CXI_EP_COMBINE_DOUBLE_TMA='1'))}
seq = []
def add(name, tmpl, arm, requires, timeout):
    g = copy.deepcopy(T[tmpl]); g['name'] = name; g['snapshot'] = snapshot; g['requires'] = list(requires)
    variant, env = ARMS[arm]; g['environment']['CXI_VARIANT'] = variant; g['environment'].update(env)
    g['timeout_seconds'] = timeout; g['environment']['CXI_TEST_TIMEOUT'] = str(timeout - 60)
    assert g['environment']['CXI_EP_SMS'] == '64' and g['environment']['CXI_EP_CONTEXTS'] == '129'
    seq.append(g); return name
ends = {}
for i, arm in enumerate(['cand', 'kern', 'leana', 'leanb']):
    ends[arm] = add('970%d-%s-sustained16k' % (i, arm), '9313-dbuf-sustained16k', arm, [], 420)
for i, arm in enumerate(['cand', 'kern', 'leana', 'leanb']):
    add('970%d-%s-repeat1' % (4 + i, arm), '9401-dbuf-repeat1', arm, [ends[arm]], 360)
s = add('9708-dbuf-irregular-stress', '9310-dbuf-irregular-stress', 'dbuf', [], 420)
add('9709-dbuf-repeat1', '9401-dbuf-repeat1', 'dbuf', [s], 360)
known = set()
for g in seq:
    assert g['name'] not in known and all(r in known for r in g['requires']), g['name']; known.add(g['name'])
(out / 'sequence.json').write_text(json.dumps(seq, indent=2) + '\n')
m = json.loads((parent / 'manifest.json').read_text())
m.update(source_parent=str(parent), scope='2026-11-02 debug isolation: cand/kern/leana/leanb sustained-16K and 4K/16K repeats, dbuf stress+repeat; code identical to source-1102-dbuf-v1')
m['files'] = {str(p.relative_to(out)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(out.rglob('*')) if p.is_file() and p.name != 'manifest.json'}
(out / 'manifest.json').write_text(json.dumps(m, indent=2) + '\n')
print(len(seq), 'gates; sum of timeouts min =', sum(g['timeout_seconds'] for g in seq) / 60); print([g['name'] for g in seq]); print(out)
