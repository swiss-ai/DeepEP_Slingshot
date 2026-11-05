#!/usr/bin/env python3
"""Comparison table of the apples-to-apples job: DeepEP v2 direct-CXI GIN vs UCCL-EP CPU proxy, same benchmark.

usage: compare_ucclcmp_1105.py results/deepep_pipeline_20261101/job-<id>/results/results [--md] [--all-ops]

Reads every PASS gate's summary.csv (direct/ep or uccl/ep). For each (backend, model, routing, operation) it
reports the median over gates and seeds of the harness headline (median_rank_max_us: median over iterations of
the per-iteration maximum across the eight ranks) and of the wall time per iteration of the slowest rank
(max_host_us_per_iteration), the effective per-rail payload rate for dispatch and combine against the 22.5 GB/s
bidirectional ceiling, and the ratio UCCL / direct. NIC octet rates from nic-node*.jsonl are listed when present.
"""
import argparse, collections, csv, json, statistics as st
from pathlib import Path
HIDDEN = {'v4flash': 4096, 'qwen3': 4096, 'minimax': 3072}
# bytes per token row on the NIC, DeepEP v2 layout: FP8 dispatch = hidden + hidden/128 scales (4 B) + 96 B metadata
# (4320 for hidden 4096), BF16 dispatch = 2*hidden + 96 (8288), BF16 combine = 2*hidden + 64 (8256); one row per token.
def row_bytes(model, dtype, op):
    h = HIDDEN[model]
    if op.startswith('dispatch'): return (h + 4 * (h // 128) + 96) if dtype == 'fp8' else (2 * h + 96)
    if op == 'combine': return 2 * h + 64
    return None
CEILING_GBPS = 22.5
def payload_bytes(model, dtype, op, tokens):
    per_row = row_bytes(model, dtype, op)
    return per_row * tokens if per_row else None
ap = argparse.ArgumentParser(); ap.add_argument('results', type=Path); ap.add_argument('--md', action='store_true'); ap.add_argument('--all-ops', action='store_true')
a = ap.parse_args()
samples = collections.defaultdict(lambda: collections.defaultdict(list)); gates = collections.defaultdict(set); nic = collections.defaultdict(list)
for gate in sorted(a.results.iterdir()):
    fin = gate / 'FINISHED.json'
    if not fin.is_file(): continue
    d = json.loads(fin.read_text())
    if d.get('qualification', {}).get('status') != 'PASS': print('skip', gate.name, d.get('qualification', {}).get('status'), 'rc', d.get('returncode')); continue
    for sub in ('direct/ep', 'uccl/ep'):
        f = gate / sub / 'summary.csv'
        if not f.is_file(): continue
        for r in csv.DictReader(open(f)):
            k = (r['backend'], r['model'], int(r['tokens_per_gpu']), r['dispatch_dtype'], r['routing'], r['operation'])
            samples[k]['headline'].append(float(r['median_rank_max_us'])); samples[k]['wall'].append(float(r['max_host_us_per_iteration']))
            samples[k]['cpu'].append(float(r['max_process_cpu_core_equivalents'])); gates[k].add(gate.name)
        for nf in sorted((gate / sub).glob('nic-node*.jsonl')):
            for line in open(nf):
                rec = json.loads(line); rates = rec.get('rates', {})
                for key, v in rates.items():
                    nic[(rec['backend'], rec['model'], rec['routing'], rec['operation'], key.split('/')[1])].append(v['GBps'])
ops = ('dispatch_fresh', 'combine', 'cycle') + (('dispatch_cached',) if a.all_ops else ())
def med(v): return st.median(v) if v else float('nan')
rows = []
for (backend, model, tokens, dtype, routing, op) in sorted(samples, key=lambda k: (k[1], k[4], ops.index(k[5]) if k[5] in ops else 9, k[0])):
    if op not in ops: continue
    s = samples[(backend, model, tokens, dtype, routing, op)]
    pb = payload_bytes(model, dtype, op, tokens); wall = med(s['wall'])
    eff = pb / wall / 1e3 if pb else None  # bytes / us -> GB/s
    rows.append(dict(backend=backend, model=model, dtype=dtype, routing=routing, op=op, n=len(s['wall']), headline=med(s['headline']) / 1000, wall=wall / 1000,
                     eff=eff, bound=(pb / CEILING_GBPS / 1e6) if pb else None, cpu=med(s['cpu']), gates=sorted(gates[(backend, model, tokens, dtype, routing, op)])))
by = {(r['backend'], r['model'], r['dtype'], r['routing'], r['op']): r for r in rows}
hdr = ['model', 'dtype', 'routing', 'operation', 'direct wall ms', 'direct headline', 'UCCL wall ms', 'UCCL headline', 'UCCL / direct (wall)', 'bound ms', 'direct eff GB/s', 'UCCL eff GB/s', 'n direct / UCCL', 'CPU cores direct / UCCL']
out = []
for (model, dtype, routing, op) in sorted({(r['model'], r['dtype'], r['routing'], r['op']) for r in rows}, key=lambda k: (k[0], k[1], k[2], ops.index(k[3]))):
    dd = by.get(('deepep', model, dtype, routing, op)); uu = by.get(('uccl', model, dtype, routing, op))
    f = lambda r, k, fmt='%.3f': (fmt % r[k]) if r and r.get(k) is not None else '—'
    ratio = ('%.2f' % (uu['wall'] / dd['wall'])) if dd and uu else '—'
    out.append([model, dtype, routing, op, f(dd, 'wall'), f(dd, 'headline'), f(uu, 'wall'), f(uu, 'headline'), ratio, f(dd or uu, 'bound'), f(dd, 'eff', '%.1f'), f(uu, 'eff', '%.1f'),
                '%s / %s' % (dd['n'] if dd else 0, uu['n'] if uu else 0), '%s / %s' % (f(dd, 'cpu', '%.1f'), f(uu, 'cpu', '%.1f'))])
if a.md:
    print('| ' + ' | '.join(hdr) + ' |'); print('|' + '|'.join('---' for _ in hdr) + '|')
    for r in out: print('| ' + ' | '.join(r) + ' |')
else:
    w = [max(len(h), *(len(r[i]) for r in out)) for i, h in enumerate(hdr)] if out else [len(h) for h in hdr]
    print('  '.join(h.ljust(w[i]) for i, h in enumerate(hdr)))
    for r in out: print('  '.join(c.ljust(w[i]) for i, c in enumerate(r)))
if nic:
    print('\nNIC octet rates (GB/s per NIC, window of the repeated operation incl. control traffic; median over nodes/NICs/gates):')
    agg = collections.defaultdict(list)
    for (backend, model, routing, op, counter), v in nic.items(): agg[(backend, model, routing, op, counter)] = v
    for k in sorted(agg):
        if k[3] in ops: print('  %-7s %-8s %-8s %-15s %-22s %.2f (min %.2f, n=%d)' % (*k, med(agg[k]), min(agg[k]), len(agg[k])))
print('\ngates used:', sorted({g for k in gates for g in gates[k]}))
