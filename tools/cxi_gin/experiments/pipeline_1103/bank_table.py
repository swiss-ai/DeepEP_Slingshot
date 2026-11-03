#!/usr/bin/env python3
"""Per-case table of the EP8 bank-routing gates: wall time per iteration (slowest rank) of dispatch_fresh,
dispatch_cached and combine, the traffic statistics recorded with the case (NIC rows per source, rows per
destination, per-pair maximum), and the wire bound from the pair maximum at 22.5 GB/s per direction
(FP8 dispatch row 4320 B, BF16 dispatch row 8288 B, BF16 combine row 8256 B).

usage: bank_table.py RESULTS_DIR GATE [GATE ...] [--dtype fp8]
"""
import json, statistics, sys
from pathlib import Path
ROW = {('fp8', 'dispatch'): 4320, ('bf16', 'dispatch'): 8288, ('fp8', 'combine'): 8256, ('bf16', 'combine'): 8256}
GBPS = 22.5e9
args = sys.argv[1:]; dtype = 'fp8'
if '--dtype' in args: dtype = args[args.index('--dtype') + 1]; del args[args.index('--dtype'):args.index('--dtype') + 2]
root = Path(args[0])
for gate in args[1:]:
    rows = {}
    for rank in range(8):
        p = root / gate / ('direct/ep/timings-rank%d.jsonl' % rank)
        if not p.exists(): continue
        for line in open(p):
            r = json.loads(line)
            if r['dispatch_dtype'] != dtype or r['operation'] not in ('dispatch_fresh', 'dispatch_cached', 'combine'): continue
            d = rows.setdefault(r['routing'], {'bank': r.get('bank'), 'wall': {}, 'cuda_med': {}})
            d['wall'][r['operation']] = max(d['wall'].get(r['operation'], 0), r['host_us_per_iteration'])
            d['cuda_med'].setdefault(r['operation'], []).append(statistics.median(r['cuda_event_us']))
    print('## %s (%s dispatch)' % (gate, dtype))
    print('| case | NIC rows mean / max | pair max | dest rows max/mean | dispatch_fresh ms (bound) | dispatch_cached ms | combine ms (bound) | combine / bound |')
    print('|---|---|---:|---:|---:|---:|---:|---:|')
    for name in sorted(rows, key=lambda n: (n.startswith('bank'), n)):
        d = rows[name]; b = d.get('bank'); w = d['wall']
        if b:
            nic = b['nic_rows']; pair = max(b['pair_rows']); nic_s = '%.0f / %d' % (sum(nic) / len(nic), max(nic)); dest = '%.2f' % b['dest_rows_max_over_mean']
        else:
            pair = 4096; nic_s = '4096 / 4096 (synthetic)'; dest = '1.00'
        bd = pair * ROW[(dtype, 'dispatch')] / GBPS * 1e3; bc = pair * ROW[(dtype, 'combine')] / GBPS * 1e3
        print('| %s | %s | %d | %s | %.3f (%.3f) | %.3f | %.3f (%.3f) | %.2f |' % (
            name, nic_s, pair, dest, w.get('dispatch_fresh', 0) / 1e3, bd, w.get('dispatch_cached', 0) / 1e3, w.get('combine', 0) / 1e3, bc, w.get('combine', 0) / 1e3 / bc))
    print()
