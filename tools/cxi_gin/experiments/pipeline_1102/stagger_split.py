#!/usr/bin/env python3
"""First packed dispatch PUT of every sender warp, bucketed by channel index (the start-stagger knob delays
channel c by c * CXI_EP_STAGGER_NS, so the buckets are start-offset bands): per bucket the medians/p90 of
the first PUT's start offset, total, lock wait (200), credit check (202) and emit (201), plus the rank's
earliest first emission, the receivers' first and last remote-tail observations (115) and the kernel end.
Medians over captures. Channel index from event 113's aux0 (channel << 32 | lane).

usage: stagger_split.py GATE_DIR [GATE_DIR ...] [--buckets N]
"""
import collections, glob, gzip, json, statistics, sys
from pathlib import Path
args = sys.argv[1:]; nb = 4
if '--buckets' in args: nb = int(args[args.index('--buckets') + 1]); del args[args.index('--buckets'):args.index('--buckets') + 2]
def med(v): return statistics.median(v) if v else float('nan')
def p90(v): return sorted(v)[len(v) * 9 // 10] if v else float('nan')
for gate in args:
    gate = Path(gate); agg = collections.defaultdict(list)
    for p in sorted(glob.glob(str(gate / 'direct/ep/device-traces/*-dispatch_fresh-rank*-iteration*.json.gz'))):
        r = json.load(gzip.open(p, 'rt')); ev = r['events']; o = min(e['start_ns'] for e in ev)
        bywarp = collections.defaultdict(lambda: collections.defaultdict(list))
        for e in ev: bywarp[(e['block'], e['thread'])][e['event']].append(e)
        rows = []
        for w, g in bywarp.items():
            puts = sorted(g[113], key=lambda e: e['start_ns'])
            if not puts: continue
            e = puts[0]; s, t = e['start_ns'], e['end_ns']; ch = e['aux0'] >> 32
            def inside(k): return sum(x['end_ns'] - x['start_ns'] for x in g[k] if x['start_ns'] >= s and x['end_ns'] <= t) / 1e3
            rows.append((ch, (s - o) / 1e6, (t - s) / 1e3, inside(200), inside(202), inside(201), (t - o) / 1e6))
        nch = max(r[0] for r in rows) + 1; width = (nch + nb - 1) // nb
        for b in range(nb):
            sel = [r for r in rows if b * width <= r[0] < (b + 1) * width]
            if not sel: continue
            key = 'ch %3d-%3d' % (b * width, min(nch, (b + 1) * width) - 1)
            agg[key + ' start ms med'].append(med([r[1] for r in sel]))
            agg[key + ' total us med/p90'].append((med([r[2] for r in sel]), p90([r[2] for r in sel])))
            agg[key + ' lock200 us med/p90'].append((med([r[3] for r in sel]), p90([r[3] for r in sel])))
            agg[key + ' credit202 us med/p90'].append((med([r[4] for r in sel]), p90([r[4] for r in sel])))
            agg[key + ' emit201 us med/p90'].append((med([r[5] for r in sel]), p90([r[5] for r in sel])))
            agg[key + ' emitted ms min/med'].append((min(r[6] for r in sel), med([r[6] for r in sel])))
        agg['rank first emission ms'].append(min(r[6] for r in rows))
        obs = [e for g in bywarp.values() for e in g[115]]
        if obs:
            agg['receivers first observation ms'].append(min(e['end_ns'] for e in obs) / 1e6 - o / 1e6)
            agg['receivers last observation ms'].append(max(e['end_ns'] for e in obs) / 1e6 - o / 1e6)
        agg['kernel end ms'].append((max(e['end_ns'] for e in ev) - o) / 1e6)
    print('##', gate.name, '(%d captures)' % len(agg['kernel end ms']))
    for k in sorted(agg):
        v = agg[k]
        if isinstance(v[0], tuple): print('  %-34s %8.2f / %8.2f' % (k, med([x[0] for x in v]), med([x[1] for x in v])))
        else: print('  %-34s %8.3f' % (k, med(v)))
