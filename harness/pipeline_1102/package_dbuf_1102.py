#!/usr/bin/env python3
"""Round 2 (2026-11-02): double-buffered TMA staging in the combine scale-up warps, on top of the lean
snapshot. Parent: source-1102-lean-v1. Applied: prepare_dbuf_1102.prepare.
Arms: leanb (lean-b + kernel knobs; same semantics as lean-v1's leanb, rebuilt from this archive),
dbuf (leanb + CXI_EP_COMBINE_DOUBLE_TMA), leanb128 and dbuf128 (128 SMs / 257 contexts).
Ladder for dbuf and dbuf128, stress for leanb (build sanity), then three counterbalanced repeats.

usage: package_dbuf_1102.py results/deepep_pipeline_20261101/source-1102-dbuf-v1 [--debug]
  --debug writes the short debug-partition sequence (shortened timeouts) instead of the full one.
"""
import copy, hashlib, json, shutil, sys
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'pipeline_v1')); sys.path.insert(0, str(HERE))
from prepare_dbuf_1102 import prepare  # noqa: E402
ROOT = HERE.parents[3]; NEW = ROOT / 'results/deepep_pipeline_20261101'
REMOTE = '/iopsstor/scratch/cscs/zyu/deepep-pipeline-20261030'
debug = '--debug' in sys.argv[2:]
out = Path(sys.argv[1]).resolve(); assert not out.exists(), out
parent = NEW / 'source-1102-lean-v1'
shutil.copytree(parent, out, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
prepare(out)
T = {g['name']: g for g in json.loads((parent / 'sequence.json').read_text())}
snapshot = REMOTE + '/sources/' + out.name
ARMS = {
    'leanb': ('lean-b', {}),
    'dbuf': ('lean-b', dict(CXI_EP_COMBINE_DOUBLE_TMA='1')),
    'leanb128': ('lean-b', dict(CXI_EP_SMS='128', CXI_EP_CONTEXTS='257')),
    'dbuf128': ('lean-b', dict(CXI_EP_COMBINE_DOUBLE_TMA='1', CXI_EP_SMS='128', CXI_EP_CONTEXTS='257')),
}
seq = []
def add(name, tmpl, arm, requires, timeout=None):
    g = copy.deepcopy(T[tmpl]); g['name'] = name; g['snapshot'] = snapshot; g['requires'] = list(requires)
    variant, env = ARMS[arm]; g['environment']['CXI_VARIANT'] = variant; g['environment'].update(env)
    e = g['environment']
    assert e['CXI_EP_SKIP_COMBINE_FLUSH'] == '1' and e['CXI_EP_LOCAL_SELF_SIGNAL'] == '1' and e['CXI_EP_FIRST_INTERVAL'] == '4'
    if timeout: g['timeout_seconds'] = timeout; e['CXI_TEST_TIMEOUT'] = str(timeout - 60)
    seq.append(g); return name
if not debug:
    s = add('9300-leanb-irregular-stress', '9130-leanb-irregular-stress', 'leanb', [])
    ends = {'leanb': [s], 'leanb128': [s]}
    base = 9310
    for arm in ['dbuf', 'dbuf128']:
        s = add('%d-%s-irregular-stress' % (base, arm), '9130-leanb-irregular-stress', arm, [])
        c = add('%d-%s-4k-correctness' % (base + 1, arm), '9131-leanb-4k-correctness', arm, [s])
        d = add('%d-%s-dropped-correctness' % (base + 2, arm), '9132-leanb-dropped-correctness', arm, [c])
        ends[arm] = [add('%d-%s-sustained16k' % (base + 3, arm), '9133-leanb-sustained16k', arm, [d])]
        base += 10
    order = [['leanb', 'dbuf', 'leanb128', 'dbuf128'], ['dbuf128', 'leanb128', 'dbuf', 'leanb'], ['dbuf', 'leanb', 'dbuf128', 'leanb128']]
    for rep, arms in enumerate(order, 1):
        for pos, arm in enumerate(arms):
            add('94%d%d-%s-repeat%d' % (rep - 1, pos, arm, rep), '9203-leanb-repeat1', arm, ends[arm])
else:
    s = add('9600-dbuf-irregular-stress', '9130-leanb-irregular-stress', 'dbuf', [], 420)
    c = add('9601-dbuf-4k-correctness', '9131-leanb-4k-correctness', 'dbuf', [s], 300)
    d = add('9602-dbuf-dropped-correctness', '9132-leanb-dropped-correctness', 'dbuf', [c], 300)
    e = add('9603-dbuf-sustained16k', '9133-leanb-sustained16k', 'dbuf', [d], 360)
    add('9604-leanb-repeat1', '9203-leanb-repeat1', 'leanb', [], 360)
    add('9605-dbuf-repeat1', '9203-leanb-repeat1', 'dbuf', [e], 360)
    s128 = add('9606-dbuf128-irregular-stress', '9130-leanb-irregular-stress', 'dbuf128', [], 420)
    add('9607-dbuf128-repeat1', '9203-leanb-repeat1', 'dbuf128', [s128], 360)
    add('9608-leanb128-repeat1', '9203-leanb-repeat1', 'leanb128', [], 360)
known = set()
for g in seq:
    assert g['name'] not in known and all(r in known for r in g['requires']), g['name']; known.add(g['name'])
assert [g['name'] for g in seq] == sorted(g['name'] for g in seq)
(out / 'sequence.json').write_text(json.dumps(seq, indent=2) + '\n')
m = json.loads((parent / 'manifest.json').read_text())
m.update(source_parent=str(parent), scope='2026-11-02 round 2: double-buffered TMA staging in combine scale-up warps (CXI_EP_COMBINE_DOUBLE_TMA) on the lean snapshot; GPU unqualified' + (' (debug-partition sequence)' if debug else ''))
m['files'] = {str(p.relative_to(out)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(out.rglob('*')) if p.is_file() and p.name != 'manifest.json'}
(out / 'manifest.json').write_text(json.dumps(m, indent=2) + '\n')
print(len(seq), 'gates; sum of timeouts min =', sum(g['timeout_seconds'] for g in seq) / 60); print([g['name'] for g in seq]); print(out)
