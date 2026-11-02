#!/usr/bin/env python3
"""Least-squares fit T = alpha + beta * MB over the size-sweep gates (median across sweeps per size).

usage: fit_size_sweep.py RESULTS_DIR GATE_REGEX [--rate 21.5]

Payload per rail: dispatch 4320 B/token (V4 Flash FP8 rows as reported by the harness), combine
8256 B/token (BF16 rows). Prints per-size medians, the bound at --rate GB/s and the ratio, then the
fit (alpha in ms, beta in ms/MB, implied GB/s, R^2). Medians of the harness's per-gate medians; no
other processing.
"""
import argparse, collections, json, re, statistics
from pathlib import Path
ap = argparse.ArgumentParser(); ap.add_argument('results_dir'); ap.add_argument('gate_regex'); ap.add_argument('--rate', type=float, default=21.5)
a = ap.parse_args(); pat = re.compile(a.gate_regex)
BYTES = {'dispatch_fresh': 4320, 'dispatch_cached': 4320, 'combine': 8256}
samples = collections.defaultdict(lambda: collections.defaultdict(list)); gates = []
for g in sorted(Path(a.results_dir).iterdir()):
    if not pat.search(g.name): continue
    fin = g / 'FINISHED.json'; rep = g / 'direct/ep/repeatability.json'
    if not (fin.exists() and rep.exists()): continue
    if json.loads(fin.read_text()).get('qualification', {}).get('status') != 'PASS': print('# skipping', g.name); continue
    gates.append(g.name)
    for r in json.loads(rep.read_text()):
        if r['operation'] in BYTES: samples[r['operation']][r['tokens_per_gpu']].append(r['repeat_median_us'] / 1000)
print('# gates:', gates)
for op, by_tok in samples.items():
    xs, ys = [], []
    print(f'\n## {op} ({BYTES[op]} B/token, bound at {a.rate} GB/s)')
    print('| tokens | MB | median ms | spread | bound ms | ratio |'); print('|---:|---:|---:|---:|---:|---:|')
    for tok in sorted(by_tok):
        v = by_tok[tok]; med = statistics.median(v); mb = tok * BYTES[op] / 1e6; bound = mb / a.rate
        spread = (max(v) - min(v)) / med * 100 if len(v) > 1 else 0.0
        print(f'| {tok} | {mb:.2f} | {med:.4f} | ±{spread:.1f}% | {bound:.4f} | {med / bound:.3f} |')
        xs.append(mb); ys.append(med)
    n = len(xs); mx = sum(xs) / n; my = sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs); sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    beta = sxy / sxx; alpha = my - beta * mx
    ss_res = sum((y - (alpha + beta * x)) ** 2 for x, y in zip(xs, ys)); ss_tot = sum((y - my) ** 2 for y in ys)
    print(f'fit: alpha = {alpha:.3f} ms, beta = {beta:.4f} ms/MB -> {1 / beta:.1f} GB/s incremental, R^2 = {1 - ss_res / ss_tot:.4f}')
