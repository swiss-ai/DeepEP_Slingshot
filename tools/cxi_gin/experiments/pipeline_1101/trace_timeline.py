#!/usr/bin/env python3
"""Milestones of the private device traces, per capture and summarised across ranks/iterations.

usage: trace_timeline.py GATE_DIR [GATE_DIR ...] [--op dispatch_fresh|combine] [--per-capture]

Reads direct/ep/device-traces/*-<op>-rank<r>-iteration<i>.json.gz of each gate. Times are relative to
the earliest event of the capture (the kernel's first traced instruction on that rank). Reported:
role starts (103 forwarder / 104 receiver for dispatch, 132/133 for combine), the first and last
packed payload submission (113) and its row-count distribution (aux1 & 0xffffffff), tail
notifications (114), the receiver's last tail observation (115), GIN put count (206), the kernel's
last traced event and the host-side CUDA event time. Medians across captures are printed per gate;
nothing is interpolated. Scopes overlap, so sums are not durations.
"""
import argparse, collections, gzip, json, statistics
from pathlib import Path

ap = argparse.ArgumentParser()
ap.add_argument('gates', nargs='+')
ap.add_argument('--op', default='dispatch_fresh')
ap.add_argument('--per-capture', action='store_true')
args = ap.parse_args()

ROLES = {'dispatch_fresh': (103, 104), 'combine': (132, 133)}
role_a, role_b = ROLES[args.op]

def milestones(r):
    ev = r['events']; o = min(e['start_ns'] for e in ev)
    g = collections.defaultdict(list)
    for e in ev: g[e['event']].append(e)
    def first(k): return (min(e['start_ns'] for e in g[k]) - o) / 1e6 if g[k] else None
    def last(k): return (max(e['end_ns'] for e in g[k]) - o) / 1e6 if g[k] else None
    rows = [e['aux1'] & 0xffffffff for e in g[113]]
    m = dict(
        role_a_start=first(role_a), role_b_start=first(role_b), role_a_end=last(role_a), role_b_end=last(role_b),
        put113_first=first(113), put113_last=last(113), n113=len(g[113]), n114=len(g[114]), n206=len(g[206]),
        gin206_first=first(206), gin206_last=last(206), obs115_last=last(115), kernel_end=last(100) if g[100] else last(130),
        cuda_event=r['cuda_event_us'] / 1000,
        wait202=sum(e['end_ns'] - e['start_ns'] for e in g[202]) / 1e6, wait207=sum(e['end_ns'] - e['start_ns'] for e in g[207]) / 1e6,
        wait200=sum(e['end_ns'] - e['start_ns'] for e in g[200]) / 1e6,
    )
    return m, collections.Counter(rows)

for gate in args.gates:
    gate = Path(gate); traces = sorted((gate / 'direct/ep/device-traces').glob('*-%s-rank*-iteration*.json.gz' % args.op))
    if not traces:
        print('#', gate.name, 'no', args.op, 'traces'); continue
    agg = collections.defaultdict(list); rows_total = collections.Counter()
    for p in traces:
        r = json.load(gzip.open(str(p), 'rt'))
        m, rows = milestones(r); rows_total.update(rows)
        for k, v in m.items():
            if v is not None: agg[k].append(v)
        if args.per_capture:
            print(gate.name, 'rank', r['rank'], 'iter', r['iteration'], ' '.join('%s=%.3f' % (k, v) if isinstance(v, float) else '%s=%s' % (k, v) for k, v in m.items()))
    print('##', gate.name, args.op, len(traces), 'captures (median across captures, ms unless a count)')
    order = ['role_a_start', 'role_b_start', 'put113_first', 'gin206_first', 'put113_last', 'role_a_end', 'gin206_last', 'obs115_last', 'role_b_end', 'kernel_end', 'cuda_event', 'n113', 'n114', 'n206', 'wait200', 'wait202', 'wait207']
    for k in order:
        if k in agg:
            v = agg[k]; print('  %-13s median %9.3f  min %9.3f  max %9.3f' % (k, statistics.median(v), min(v), max(v)))
    if rows_total:
        print('  113 rows per PUT (rows: count over all captures):', dict(sorted(rows_total.items())))
