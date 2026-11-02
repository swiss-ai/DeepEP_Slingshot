#!/usr/bin/env python3
"""First versus last packed dispatch PUT of every sender warp, split into the nested transport scopes:
lock wait (200), credit check (202), emit body (201), doorbell (209) and the remainder; plus when the
first PUT is emitted (scope end) across the rank, status reads and doorbells per capture.
Medians over captures of per-capture medians/p90 across the 256 sender warps (us unless stated).

usage: put_split.py GATE_DIR [GATE_DIR ...]
"""
import collections, glob, gzip, json, statistics, sys
from pathlib import Path
def med(v): return statistics.median(v) if v else float('nan')
for gate in sys.argv[1:]:
    gate = Path(gate); agg = collections.defaultdict(list)
    for p in sorted(glob.glob(str(gate / 'direct/ep/device-traces/*-dispatch_fresh-rank*-iteration*.json.gz'))):
        r = json.load(gzip.open(p, 'rt')); ev = r['events']; o = min(e['start_ns'] for e in ev)
        bywarp = collections.defaultdict(lambda: collections.defaultdict(list))
        for e in ev: bywarp[(e['block'], e['thread'])][e['event']].append(e)
        parts = collections.defaultdict(list)
        for w, g in bywarp.items():
            puts = sorted(g[113], key=lambda e: e['start_ns'])
            if not puts: continue
            def inside(k, s, t): return sum(x['end_ns'] - x['start_ns'] for x in g[k] if x['start_ns'] >= s and x['end_ns'] <= t) / 1e3
            for idx, label in ((0, 'first'), (len(puts) - 1, 'last')):
                e = puts[idx]; s, t = e['start_ns'], e['end_ns']; total = (t - s) / 1e3
                lock, credit, emit, pub = inside(200, s, t), inside(202, s, t), inside(201, s, t), inside(209, s, t)
                parts[label + ' total'].append(total); parts[label + ' lock200'].append(lock); parts[label + ' credit202'].append(credit)
                parts[label + ' emit201'].append(emit); parts[label + ' publish209'].append(pub); parts[label + ' rest'].append(total - lock - credit - emit - pub)
        for k, v in parts.items(): agg[k + ' med'].append(med(v)); agg[k + ' p90'].append(sorted(v)[len(v) * 9 // 10])
        ends = sorted((e['end_ns'] - o) / 1e6 for g in bywarp.values() for e in g[113])
        agg['first PUT emitted (ms)'].append(ends[0]); agg['10% PUTs emitted (ms)'].append(ends[len(ends) // 10]); agg['last PUT emitted (ms)'].append(ends[-1])
        agg['credit scopes 202 (n)'].append(sum(len(g[202]) for g in bywarp.values())); agg['credit 202 total (us)'].append(sum(e['end_ns'] - e['start_ns'] for g in bywarp.values() for e in g[202]) / 1e3)
        agg['doorbells 209 (n)'].append(sum(len(g[209]) for g in bywarp.values()))
    print('##', gate.name, '(%d captures)' % len(agg['doorbells 209 (n)']))
    for k in sorted(agg): print('  %-28s %9.2f' % (k, med(agg[k])))
