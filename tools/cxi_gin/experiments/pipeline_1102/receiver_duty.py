#!/usr/bin/env python3
"""Dispatch receiver duty cycle from the private device traces: per receiver warp, the role scope (104)
against the summed wait-for-data scopes (105, 'Wait for this rank to have data (or finish)'). What is
not waiting is processing (copying the arrived chunk into the scale-up path). Medians over warps and
captures; also the per-rank receiver processing throughput (remote bytes / total processing time of
all receiver warps) as an upper bound on how fast the receivers could consume if the data were there.

usage: receiver_duty.py GATE_DIR [GATE_DIR ...]
"""
import collections, gzip, json, statistics, sys
from pathlib import Path
ROW = 4320
for gate in sys.argv[1:]:
    gate = Path(gate); root = gate / 'direct/ep/device-traces'
    fr, proc_rate, waits, procs, counts, ends = [], [], [], [], [], []
    for path in sorted(root.glob('*-dispatch_fresh-rank*-iteration*.json.gz')):
        with gzip.open(str(path), 'rt') as f: r = json.load(f)
        ev = r['events']; o = min(e['start_ns'] for e in ev); own = r['rank'] // 4
        role = {}; wait = collections.defaultdict(int); n = collections.Counter()
        for e in ev:
            k = (e['block'], e['thread'])
            if e['event'] == 104: role[k] = (e['start_ns'] - o, e['end_ns'] - o)
            elif e['event'] == 105 and (e['aux1'] & 0xffffffff) != own:
                wait[k] += e['end_ns'] - e['start_ns']; n[k] += 1
        remote_rows = sum((e['aux1'] & 0xffffffff) for e in ev if e['event'] == 113)
        total_proc = 0
        for k, (s, t) in role.items():
            d = t - s
            if d <= 0: continue
            w = min(wait.get(k, 0), d); fr.append(w / d); waits.append(w / 1e6); procs.append((d - w) / 1e6); counts.append(n.get(k, 0)); ends.append(t / 1e6)
            total_proc += d - w
        if total_proc: proc_rate.append(remote_rows * ROW / total_proc)
    print('## %s dispatch receivers: %d warps over %d captures' % (gate.name, len(fr), len(proc_rate)))
    for name, v in [('wait fraction of role', fr), ('wait ms per warp', waits), ('processing ms per warp', procs), ('remote wait scopes per warp', counts), ('role end ms', ends)]:
        print('  %-28s median %8.3f  p10 %8.3f  p90 %8.3f' % (name, statistics.median(v), sorted(v)[len(v) // 10], sorted(v)[len(v) * 9 // 10]))
    print('  %-28s median %8.1f GB/s (remote bytes / summed receiver processing time, per rank)' % ('receiver processing rate', statistics.median(proc_rate)))
