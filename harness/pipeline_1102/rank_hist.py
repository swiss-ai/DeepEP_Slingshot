#!/usr/bin/env python3
"""Per-gate rank-level timing structure: rank median, median of the per-iteration rank maximum (the
harness's headline metric), minimum, and a histogram of all per-rank per-iteration times.
usage: rank_hist.py RESULTS_DIR GATE [GATE ...] [--bin US] [--dtype fp8]"""
import json, statistics, sys
from pathlib import Path
args = sys.argv[1:]; binw = 25; dtype = 'fp8'
if '--bin' in args: binw = int(args[args.index('--bin') + 1]); del args[args.index('--bin'):args.index('--bin') + 2]
if '--dtype' in args: dtype = args[args.index('--dtype') + 1]; del args[args.index('--dtype'):args.index('--dtype') + 2]
root = Path(args[0])
for gate in args[1:]:
    rows = {}
    for rank in range(8):
        p = root / gate / ('direct/ep/timings-rank%d.jsonl' % rank)
        if not p.exists(): continue
        for line in open(p):
            r = json.loads(line)
            if r.get('dispatch_dtype') != dtype or r['operation'] not in ('dispatch_fresh', 'combine'): continue
            rows.setdefault((r['tokens_per_gpu'], r['operation']), {})[rank] = r['cuda_event_us']
    for (tokens, op), d in sorted(rows.items()):
        n = len(d[0]); allv = sorted(v for rk in d for v in d[rk])
        itmax = [max(d[rk][i] for rk in d) for i in range(n)]
        bins = {}
        for v in allv: bins[int(v // binw * binw)] = bins.get(int(v // binw * binw), 0) + 1
        print('== %s %d %s  rank-median %.0f  iter-max median %.0f  min %.0f  max %.0f' % (gate, tokens, op, statistics.median(allv), statistics.median(itmax), allv[0], allv[-1]))
        print('   ' + ' '.join('%d:%d' % (b, bins[b]) for b in sorted(bins) if bins[b] >= max(3, n // 25)))
