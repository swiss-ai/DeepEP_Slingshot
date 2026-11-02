#!/usr/bin/env python3
"""Per-arm medians of the repeat gates with the effective per-rail rate against the 22.5 GB/s bound.

usage: effective_rate.py RESULTS_DIR GATE_REGEX [--ref ARM] [--wall]
Default: the harness headline (median over iterations of the per-iteration maximum across ranks).
--wall: throughput time instead, the slowest rank's host wall time per iteration over the timed loop
(window_wall_seconds / iters, which equals that rank's mean CUDA window since the loop is GPU-bound);
unlike the headline it is not inflated when the ranks' kernel ends are skewed against each other.
Bounds (payload serialisation at 22.5 GB/s per rail per direction, V4 Flash FP8 dispatch / BF16 combine):
4K dispatch 0.786 ms, 4K combine 1.503 ms, 16K dispatch 3.146 ms, 16K combine 6.013 ms.
"""
import collections, json, re, statistics, sys
from pathlib import Path
BOUND_MS = {(4096, 'dispatch'): 0.786, (4096, 'combine'): 1.503, (16384, 'dispatch'): 3.146, (16384, 'combine'): 6.013}
root = Path(sys.argv[1]); pat = re.compile(sys.argv[2]); ref = sys.argv[sys.argv.index('--ref') + 1] if '--ref' in sys.argv else None
wall = '--wall' in sys.argv
samples = collections.defaultdict(lambda: collections.defaultdict(list)); gates = collections.Counter()
for gate in sorted(root.iterdir()):
    if not pat.search(gate.name): continue
    rep, fin = gate / 'direct/ep/repeatability.json', gate / 'FINISHED.json'
    if not rep.exists() or not fin.exists(): continue
    if json.loads(fin.read_text()).get('qualification', {}).get('status') != 'PASS':
        print('# skipping', gate.name); continue
    arm = gate.name.split('-')[1]; gates[arm] += 1
    if wall:
        per = {}
        for rank in range(8):
            for line in open(gate / ('direct/ep/timings-rank%d.jsonl' % rank)):
                r = json.loads(line)
                if r['operation'] not in ('dispatch_fresh', 'dispatch_cached', 'combine', 'cycle') or r['dispatch_dtype'] != 'fp8': continue
                k = (r['tokens_per_gpu'], r['routing'], r['operation']); per[k] = max(per.get(k, 0), r['host_us_per_iteration'])
        for k, v in per.items(): samples[k][arm].append(v / 1000)
        continue
    for r in json.loads(rep.read_text()):
        if r['operation'] not in ('dispatch_fresh', 'dispatch_cached', 'combine') or r['dispatch_dtype'] != 'fp8': continue
        samples[(r['tokens_per_gpu'], r['routing'], r['operation'])][arm].append(r['repeat_median_us'] / 1000)
arms = sorted(gates, key=lambda a: (a != ref, a)); ref = ref if ref in gates else (arms[0] if arms else None)
print('# gates per arm:', dict(gates), '| reference:', ref, '| metric:', 'wall per iteration (slowest rank)' if wall else 'median of per-iteration rank max')
print('| tokens | routing | operation | ' + ' | '.join('%s ms (GB/s eff.)' % a for a in arms) + ' |')
print('|---:|---|---|' + '---:|' * len(arms))
for key in sorted(samples):
    tokens, routing, op = key; kind = 'combine' if op == 'combine' else 'dispatch'
    bound = None if op == 'cycle' else BOUND_MS.get((tokens, kind))
    cells = []
    for a in arms:
        v = samples[key].get(a)
        if not v: cells.append('—'); continue
        med = statistics.median(v); spread = (max(v) - min(v)) / med * 100 if len(v) > 1 else 0
        eff = ' %.1f' % (bound / med * 22.5) if bound else ''
        base = samples[key].get(ref); rel = '' if (a == ref or not base) else ' %+.1f%%' % ((med / statistics.median(base) - 1) * 100)
        cells.append('%.3f ±%.1f%%%s%s' % (med, spread, (' (%s)' % eff.strip()) if eff else '', rel))
    print('| %d | %s | %s | %s |' % (tokens, routing, op, ' | '.join(cells)))
