#!/usr/bin/env python3
"""Zero-code cadence arms on the lean-b transport + kernel knobs (snapshot source-1102-lean-v1), for
pre-staging into an allocation: li8 (dispatch regular interval 8, first 4), lc8 (combine batch 8, first
4), li8c8 (both). PUT boundaries stay on multiples of four rows (4, 12, 20, ... rows). Each arm: irregular
stress, 4K correctness, sustained 16K, then three repeats interleaved with leanb repeats.
usage: make_cadence_requests.py OUT_DIR"""
import copy, json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[4]
seq = json.loads((ROOT / 'results/deepep_pipeline_20261101/source-1102-lean-v1/sequence.json').read_text()); T = {g['name']: g for g in seq}
ARMS = {'li8': dict(CXI_EP_UPDATE_INTERVAL='8', CXI_EP_FORWARD_CHUNK='3'), 'lc8': dict(CXI_EP_COMBINE_BATCH='8'),
        'li8c8': dict(CXI_EP_UPDATE_INTERVAL='8', CXI_EP_FORWARD_CHUNK='3', CXI_EP_COMBINE_BATCH='8')}
out = Path(sys.argv[1]); out.mkdir(parents=True, exist_ok=True); names = []
def add(name, tmpl, arm, requires):
    g = copy.deepcopy(T[tmpl]); g['name'] = name; g['requires'] = list(requires)
    if arm != 'leanb': g['environment'].update(ARMS[arm])
    e = g['environment']; assert e['CXI_VARIANT'] == 'lean-b' and e['CXI_EP_SKIP_COMBINE_FLUSH'] == '1' and e['CXI_EP_FIRST_INTERVAL'] == '4' and e['CXI_EP_COMBINE_FIRST_BATCH'] == '4'
    assert int(e['CXI_EP_COMBINE_FIRST_BATCH']) <= int(e['CXI_EP_COMBINE_BATCH']) and int(e['CXI_EP_FIRST_INTERVAL']) <= int(e['CXI_EP_UPDATE_INTERVAL'])
    (out / (name + '.json')).write_text(json.dumps(g, indent=2) + '\n'); names.append(name); return name
ends = {'leanb': ['9133-leanb-sustained16k']}
base = 9510
for arm in ['li8', 'lc8', 'li8c8']:
    s = add('%d-%s-irregular-stress' % (base, arm), '9130-leanb-irregular-stress', arm, [])
    c = add('%d-%s-4k-correctness' % (base + 1, arm), '9131-leanb-4k-correctness', arm, [s])
    ends[arm] = [add('%d-%s-sustained16k' % (base + 2, arm), '9133-leanb-sustained16k', arm, [c])]
    base += 10
order = [['leanb', 'li8', 'lc8', 'li8c8'], ['li8c8', 'lc8', 'li8', 'leanb'], ['lc8', 'leanb', 'li8c8', 'li8']]
for rep, arms in enumerate(order, 1):
    for pos, arm in enumerate(arms):
        add('96%d%d-%s-repeat%d' % (rep - 1, pos, arm, rep), '9203-leanb-repeat1', arm, ends[arm])
print(len(names), names)
