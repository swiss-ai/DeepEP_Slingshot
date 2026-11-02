#!/usr/bin/env python3
"""Follow-up requests for allocation F (job 3830101, snapshot source-1101-first-batch-v1).

F showed that a 4-row first notification interval (CXI_EP_FIRST_INTERVAL=4) removes most of
the dispatch per-call term at 4K while the regular interval stays 16. This sweep asks two
questions on the same immutable snapshot (env-only variation, as the F arms themselves):
  * how small should the first interval be (1, 2, 4, 8 with the regular interval 16), and
  * is it the *first* interval that matters or a denser cadence overall (regular 8 and 4).
All arms keep CXI_EP_COMBINE_FIRST_BATCH=4 (the F 'both4' base) so only dispatch varies.
Each new arm gets the irregular-stress and 4K exact-correctness gates (the precedent of the C
cadence variants) before three counterbalanced repeats of all six arms.
"""
import json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
SEQ = ROOT / 'results/deepep_pipeline_20261101/source-1101-first-batch-v1/sequence.json'
OUT = ROOT / 'results/deepep_pipeline_20261101/job-3830101-followup-requests.json'

seq = {s['name']: s for s in json.loads(SEQ.read_text())}
base_irregular = seq['8530-both4-irregular-stress']
base_4k = seq['8531-both4-4k-correctness']
base_repeat = seq['8543-both4-repeat1']
for b in (base_irregular, base_4k, base_repeat):
    assert b['environment']['CXI_EP_FIRST_INTERVAL'] == '4'
    assert b['environment']['CXI_EP_COMBINE_FIRST_BATCH'] == '4'
    assert b['environment']['CXI_EP_UPDATE_INTERVAL'] == '16'

# arm -> (first interval, regular interval)
ARMS = {
    'ref': (4, 16),   # = F both4, re-run so every arm shares the same node pair and hour
    'f1':  (1, 16),
    'f2':  (2, 16),
    'f8':  (8, 16),
    'u8':  (4, 8),
    'u4':  (4, 4),
}
NEW_ARMS = [a for a in ARMS if a != 'ref']

def with_env(spec, name, arm, requires):
    first, regular = ARMS[arm]
    assert 1 <= first <= regular <= 64
    env = dict(spec['environment'])
    env['CXI_EP_FIRST_INTERVAL'] = str(first)
    env['CXI_EP_UPDATE_INTERVAL'] = str(regular)
    return dict(spec, name=name, environment=env, requires=list(requires))

requests = []
correctness = []
for i, arm in enumerate(NEW_ARMS):
    irr = f'{8570 + 2 * i}-{arm}-irregular-stress'
    k4 = f'{8571 + 2 * i}-{arm}-4k-correctness'
    requests.append(with_env(base_irregular, irr, arm, []))
    requests.append(with_env(base_4k, k4, arm, [irr]))
    correctness += [irr, k4]
# 'ref' is already qualified in F (8530-8533); repeats additionally wait for its sustained gate.
repeat_requires = correctness + ['8533-both4-sustained16k']

ROUNDS = [
    ['ref', 'f1', 'f2', 'f8', 'u8', 'u4'],
    ['u4', 'u8', 'f8', 'f2', 'f1', 'ref'],
    ['f2', 'u4', 'ref', 'f8', 'f1', 'u8'],
]
for r, order in enumerate(ROUNDS, start=1):
    for pos, arm in enumerate(order):
        name = f'{8580 + 10 * (r - 1) + pos}-{arm}-repeat{r}'
        requests.append(with_env(base_repeat, name, arm, repeat_requires))

names = [r['name'] for r in requests]
assert len(set(names)) == len(names)
assert names == sorted(names), 'controller executes requests in name order'
OUT.write_text(json.dumps(requests, indent=2) + '\n')
total = sum(r['timeout_seconds'] for r in requests)
print(f'{len(requests)} requests -> {OUT}')
print('arms:', {a: dict(first=v[0], regular=v[1]) for a, v in ARMS.items()})
print('names:', names)
print(f'sum of timeouts {total/60:.0f} min (worst case); expected ~{(10*2.2 + 18*2.4):.0f} min from F gate durations')
