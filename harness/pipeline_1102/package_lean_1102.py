#!/usr/bin/env python3
"""Allocation J (2026-11-02): lean signal path and kernel-side signal changes on the final candidate.

Parent: source-1101-first-batch-v1 (the F-qualified GPU archive). Applied: prepare_lean_1102.prepare.
Arms (all on the candidate knobs: packed rows I16/F4/C3, packed combine B16/FB4, final tail, 64 SMs,
129 contexts unless stated):
  cand      marker-zero transport, kernels unchanged (reference; correctness from the holder's 9000 gate)
  kern      marker-zero transport + CXI_EP_SKIP_COMBINE_FLUSH + CXI_EP_LOCAL_SELF_SIGNAL
  leana     lean-a transport (fence elision, CSTATE cache) + both kernel knobs
  leanb     lean-b transport (lean-a + marker fold) + both kernel knobs
  leanb128  leanb with CXI_EP_SMS=128 CXI_EP_CONTEXTS=257
Every non-reference arm runs the correctness ladder (irregular stress, 4K FP8/BF16, dropped tokens,
sustained 16K) before three counterbalanced 4K/16K repeat gates per arm.

usage: package_lean_1102.py results/deepep_pipeline_20261101/source-1102-lean-v1
"""
import copy, hashlib, json, shutil, sys
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'pipeline_v1')); sys.path.insert(0, str(HERE))
from prepare_lean_1102 import prepare  # noqa: E402
ROOT = HERE.parents[3]; NEW = ROOT / 'results/deepep_pipeline_20261101'
REMOTE = '/iopsstor/scratch/cscs/zyu/deepep-pipeline-20261030'
out = Path(sys.argv[1]).resolve(); assert not out.exists(), out
parent = NEW / 'source-1101-first-batch-v1'; templates = NEW / 'source-1101-release-h-v1'
shutil.copytree(parent, out, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
prepare(out)
T = {g['name']: g for g in json.loads((templates / 'sequence.json').read_text())}
snapshot = REMOTE + '/sources/' + out.name
KERN = dict(CXI_EP_SKIP_COMBINE_FLUSH='1', CXI_EP_LOCAL_SELF_SIGNAL='1')
ARMS = {
    'cand': ('marker-zero', {}),
    'kern': ('marker-zero', KERN),
    'leana': ('lean-a', KERN),
    'leanb': ('lean-b', KERN),
    'leanb128': ('lean-b', dict(KERN, CXI_EP_SMS='128', CXI_EP_CONTEXTS='257')),
}
seq = []
def add(name, tmpl, arm, requires):
    g = copy.deepcopy(T[tmpl]); g['name'] = name; g['snapshot'] = snapshot; g['requires'] = list(requires)
    variant, env = ARMS[arm]; g['environment']['CXI_VARIANT'] = variant; g['environment'].update(env)
    e = g['environment']
    assert e['CXI_EP_FIRST_INTERVAL'] == '4' and e['CXI_EP_COMBINE_FIRST_BATCH'] == '4' and e['CXI_EP_UPDATE_INTERVAL'] == '16'
    assert e['CXI_EP_PACK_ROWS'] == '1' and e['CXI_EP_PACK_COMBINE'] == '1' and e['CXI_EP_MERGE_FINAL_TAIL'] == '1'
    seq.append(g); return name
ends = {'cand': []}
base = 9110
for arm in ['kern', 'leana', 'leanb', 'leanb128']:
    s = add('%d-%s-irregular-stress' % (base, arm), '8800-fresh-irregular-stress', arm, [])
    c = add('%d-%s-4k-correctness' % (base + 1, arm), '8801-fresh-4k-correctness', arm, [s])
    d = add('%d-%s-dropped-correctness' % (base + 2, arm), '8802-fresh-dropped-correctness', arm, [c])
    ends[arm] = [add('%d-%s-sustained16k' % (base + 3, arm), '8803-fresh-sustained16k', arm, [d])]
    base += 10
order = [['cand', 'kern', 'leana', 'leanb', 'leanb128'],
         ['leanb128', 'leanb', 'leana', 'kern', 'cand'],
         ['leana', 'cand', 'leanb128', 'kern', 'leanb']]
for rep, arms in enumerate(order, 1):
    for pos, arm in enumerate(arms):
        add('92%d%d-%s-repeat%d' % (rep - 1, pos, arm, rep), '8804-fresh-repeat1', arm, ends[arm])
known = set()
for g in seq:
    assert g['name'] not in known and all(r in known for r in g['requires']), g['name']; known.add(g['name'])
assert [g['name'] for g in seq] == sorted(g['name'] for g in seq)
(out / 'sequence.json').write_text(json.dumps(seq, indent=2) + '\n')
m = json.loads((parent / 'manifest.json').read_text())
m.update(source_parent=str(parent), scope='2026-11-02 allocation J: lean signal path (fence elision, CSTATE cache, marker fold) and kernel-side signal changes (no combine flush, no NIC self-signal) on the final candidate; GPU unqualified')
m['files'] = {str(p.relative_to(out)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(out.rglob('*')) if p.is_file() and p.name != 'manifest.json'}
(out / 'manifest.json').write_text(json.dumps(m, indent=2) + '\n')
print(len(seq), 'gates; sum of timeouts h =', round(sum(g['timeout_seconds'] for g in seq) / 3600, 2)); print([g['name'] for g in seq]); print(out)
