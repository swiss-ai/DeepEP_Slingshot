#!/usr/bin/env python3
"""Wire-phase profile of the private device traces: when do the remote bytes leave the sender and
when does the receiver see them, as cumulative curves per capture, summarised across captures.

usage: wire_curve.py GATE_DIR [GATE_DIR ...] [--op dispatch_fresh|combine] [--bin-us 100] [--per-capture]

Dispatch: sender submissions are the packed PUT scopes (113, aux1 low word = rows), receiver arrivals
are the tail observations (115, aux1 = consumed_tail<<32 | available_tail, rows = difference) of the
remote scale-out rank. Combine: sender submissions are the packed combine PUT scopes (116, rows =
last_j - first_j + 1 of the channel-major slot); arrival milestones are the per-channel remote tail
completions (138) because the combine's reducer does not record per-row arrivals. Bytes use the
FP8 dispatch row (4320) and the BF16 combine row (8256). Times are relative to the first traced
event of the capture (same origin as trace_timeline.py). Rates are GB/s = bytes / ns.
"""
import argparse, collections, gzip, json, statistics
from pathlib import Path

ap = argparse.ArgumentParser()
ap.add_argument('gates', nargs='+'); ap.add_argument('--op', default='dispatch_fresh')
ap.add_argument('--bin-us', type=float, default=100.0); ap.add_argument('--per-capture', action='store_true')
args = ap.parse_args()
ROW = {'dispatch_fresh': 4320, 'combine': 8256}[args.op]

def curves(r):
    ev = r['events']; o = min(e['start_ns'] for e in ev); own = r['rank'] // 4
    g = collections.defaultdict(list)
    for e in ev: g[e['event']].append(e)
    if args.op == 'dispatch_fresh':
        sends = sorted(((e['start_ns'] - o), (e['aux1'] & 0xffffffff) * ROW) for e in g[113])
        # Arrival = growth of the highest available tail seen per (channel, source rank); successive
        # observations of the same pending rows are not counted twice.
        arr = []; seen = {}
        for e in sorted(g[115], key=lambda e: e['end_ns']):
            src = e['aux0'] & 0xffffffff
            if src == own: continue
            key = (e['aux0'] >> 32, src); avail = e['aux1'] & 0xffffffff
            grow = avail - seen.get(key, 0)
            if grow > 0: seen[key] = avail; arr.append((e['end_ns'] - o, grow * ROW))
    else:
        sends = sorted(((e['start_ns'] - o), ((e['aux1'] & 0xffffffff) - (e['aux1'] >> 32) + 1) * ROW) for e in g[116])
        arr = sorted(((e['end_ns'] - o), 1) for e in g[138])  # channel completions, unit weight
    return sends, arr

def quantile_time(curve, frac):
    total = sum(w for _, w in curve); acc = 0
    for t, w in curve:
        acc += w
        if acc >= frac * total: return t
    return curve[-1][0] if curve else None

def summarise(curve, bins_ns):
    total = sum(w for _, w in curve)
    hist = collections.Counter()
    for t, w in curve: hist[int(t // bins_ns)] += w
    return total, hist

results = collections.defaultdict(list)
for gate in args.gates:
    gate = Path(gate); root = gate / 'direct/ep/device-traces'
    rows = []
    for path in sorted(root.glob('*-%s-rank*-iteration*.json.gz' % args.op)):
        with gzip.open(str(path), 'rt') as f: r = json.load(f)
        sends, arr = curves(r)
        if not sends or not arr: continue
        sb = sum(w for _, w in sends); ab = sum(w for _, w in arr); o = min(e['start_ns'] for e in r['events'])
        m = dict(send_first=sends[0][0] / 1e6, send_50=quantile_time(sends, .5) / 1e6, send_last=sends[-1][0] / 1e6, role_b_end=(max(e['end_ns'] for e in r['events'] if e['event'] in (104, 133)) - o) / 1e6,
                 arr_first=arr[0][0] / 1e6, arr_10=quantile_time(arr, .1) / 1e6, arr_50=quantile_time(arr, .5) / 1e6,
                 arr_90=quantile_time(arr, .9) / 1e6, arr_last=arr[-1][0] / 1e6, send_bytes_MB=sb / 1e6, n_sends=len(sends))
        if args.op == 'dispatch_fresh':
            m['arr_bytes_MB'] = ab / 1e6
            m['rate_first_put_to_last_obs'] = ab / (arr[-1][0] - sends[0][0])
            t10, t90 = quantile_time(arr, .1), quantile_time(arr, .9)
            m['rate_10_90'] = 0.8 * ab / (t90 - t10) if t90 > t10 else float('nan')
            m['rate_last_put_to_last_obs'] = None
        else:
            m['rate_first_put_to_last_obs'] = sb / (arr[-1][0] - sends[0][0])
        m['_arr_hist'] = summarise(arr, args.bin_us * 1e3)[1]; m['_send_hist'] = summarise(sends, args.bin_us * 1e3)[1]
        m['_key'] = (r['rank'], r['iteration'])
        rows.append(m)
    print('## %s %s %d captures (median across captures; ms, MB, GB/s)' % (gate.name, args.op, len(rows)))
    if not rows: continue
    keys = [k for k in rows[0] if not k.startswith('_') and rows[0][k] is not None]
    for k in keys:
        vals = [m[k] for m in rows if m[k] is not None]
        print('  %-28s median %9.3f  min %9.3f  max %9.3f' % (k, statistics.median(vals), min(vals), max(vals)))
    nb = max(max(m['_arr_hist']) for m in rows) + 1
    unit = ROW if args.op == 'dispatch_fresh' else 1
    print('  arrival per %d us bin (median across captures; %s):' % (args.bin_us, 'GB/s' if args.op == 'dispatch_fresh' else 'channels completed'))
    line = []
    for b in range(nb):
        v = statistics.median(m['_arr_hist'].get(b, 0) for m in rows)
        line.append('%5.1f' % (v / (args.bin_us * 1e3)) if args.op == 'dispatch_fresh' else '%3d' % v)
    print('   ', ' '.join(line))
    print('  submission per %d us bin (median across captures; GB/s):' % args.bin_us)
    nb2 = max(max(m['_send_hist']) for m in rows) + 1
    print('   ', ' '.join('%5.1f' % (statistics.median(m['_send_hist'].get(b, 0) for m in rows) / (args.bin_us * 1e3)) for b in range(nb2)))
    if args.per_capture:
        for m in rows:
            print('   ', m['_key'], {k: round(m[k], 3) for k in keys if m[k] is not None})
