#!/usr/bin/env python3
"""Combine pre-wire decomposition from the private device traces: entry barrier end (131), scale-up and
forward role starts (132/133), first local arrival (134), first and 10/50 % reduce completions (135),
first and 10/50 % packed PUT submissions (116, start = intent, end = emitted), last PUT, scale-up end,
forward end, kernel end (130). Medians across captures; None-valued milestones are skipped.

usage: combine_prewire.py GATE_DIR [GATE_DIR ...]
"""
import collections, glob, gzip, json, statistics, sys
from pathlib import Path
for gate in sys.argv[1:]:
    gate = Path(gate); rows = collections.defaultdict(list)
    for p in sorted(glob.glob(str(gate / 'direct/ep/device-traces/*-combine-rank*-iteration*.json.gz'))):
        r = json.load(gzip.open(p, 'rt')); ev = r['events']; o = min(e['start_ns'] for e in ev)
        g = collections.defaultdict(list)
        for e in ev: g[e['event']].append(e)
        def first(k, key='start_ns'): return (min(e[key] for e in g[k]) - o) / 1e6 if g[k] else None
        def last(k, key='end_ns'): return (max(e[key] for e in g[k]) - o) / 1e6 if g[k] else None
        def q(k, frac, key='start_ns'):
            if not g[k]: return None
            ts = sorted((e[key] - o) / 1e6 for e in g[k]); return ts[int(frac * (len(ts) - 1))]
        m = dict(barrier_end_131=last(131), scaleup_start_132=first(132), forward_start_133=first(133),
                 first_local_134=first(134, 'end_ns'), first_reduce_done_135=first(135, 'end_ns'), reduce_done_10pct=q(135, .1, 'end_ns'),
                 reduce_done_50pct=q(135, .5, 'end_ns'), reduce_done_last=last(135),
                 first_put_116_start=first(116), first_put_116_end=first(116, 'end_ns'), put_116_10pct_end=q(116, .1, 'end_ns'),
                 put_116_50pct_end=q(116, .5, 'end_ns'), last_put_116_end=last(116), scaleup_end_132=last(132), first_tma_wait_136=first(136, 'end_ns'),
                 remote_tail_first_138=first(138, 'end_ns'), remote_tail_last_138=last(138), forward_end_133=last(133), kernel_end_130=last(130),
                 cuda_event=r['cuda_event_us'] / 1000, n135=len(g[135]), n116=len(g[116]), n134=len(g[134]))
        for k, v in m.items():
            if v is not None: rows[k].append(v)
    print('##', gate.name, 'combine', len(rows['n116']), 'captures (median ms unless a count)')
    for k, v in rows.items(): print('  %-24s %9.3f  (min %8.3f max %8.3f)' % (k, statistics.median(v), min(v), max(v)))
