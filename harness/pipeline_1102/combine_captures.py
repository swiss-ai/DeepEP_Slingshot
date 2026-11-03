#!/usr/bin/env python3
"""Per-capture combine timeline from the private device traces: for every (rank, iteration) capture the
entry barrier end (131), first local token (134), first PUT emitted (116 end), last PUT emitted, first and
last remote-tail arrival (138), kernel end (130) and the derived wire phase (kernel end - first PUT
emitted). Shows whether an earlier first emission moves the end (wire phase constant) or not (wire phase
stretches). Medians per gate at the bottom.

usage: combine_captures.py GATE_DIR [GATE_DIR ...] [--all]
"""
import collections, glob, gzip, json, statistics, sys
from pathlib import Path
show_all = '--all' in sys.argv
for gate in [a for a in sys.argv[1:] if a != '--all']:
    gate = Path(gate); rows = []
    for p in sorted(glob.glob(str(gate / 'direct/ep/device-traces/*-combine-rank*-iteration*.json.gz'))):
        name = Path(p).name; rank = int(name.split('-rank')[1].split('-')[0]); it = int(name.split('-iteration')[1].split('.')[0])
        r = json.load(gzip.open(p, 'rt')); ev = r['events']; o = min(e['start_ns'] for e in ev)
        g = collections.defaultdict(list)
        for e in ev: g[e['event']].append(e)
        def first(k, key='start_ns'): return (min(e[key] for e in g[k]) - o) / 1e6 if g[k] else float('nan')
        def last(k, key='end_ns'): return (max(e[key] for e in g[k]) - o) / 1e6 if g[k] else float('nan')
        row = dict(rank=rank, it=it, barrier=last(131), first_local=first(134, 'end_ns'), first_put=first(116, 'end_ns'),
                   last_put=last(116), tail_first=first(138, 'end_ns'), tail_last=last(138), end=last(130))
        row['wire'] = row['end'] - row['first_put']; row['prewire'] = row['first_put'] - row['barrier']
        rows.append(row)
    print('## %s (%d captures)' % (gate.name, len(rows)))
    if not rows:
        print('  no combine traces'); continue
    keys = ['barrier', 'first_local', 'first_put', 'last_put', 'tail_first', 'tail_last', 'end', 'prewire', 'wire']
    if show_all:
        print('  rank it  ' + ' '.join('%10s' % k for k in keys))
        for row in sorted(rows, key=lambda x: (x['it'], x['rank'])):
            print('  %4d %2d  ' % (row['rank'], row['it']) + ' '.join('%10.3f' % row[k] for k in keys))
    med = {k: statistics.median(r[k] for r in rows) for k in keys}
    lo = {k: min(r[k] for r in rows) for k in keys}; hi = {k: max(r[k] for r in rows) for k in keys}
    print('  median   ' + ' '.join('%10.3f' % med[k] for k in keys))
    print('  min      ' + ' '.join('%10.3f' % lo[k] for k in keys))
    print('  max      ' + ' '.join('%10.3f' % hi[k] for k in keys))
    print('  (columns: ' + ' '.join(keys) + ')')
