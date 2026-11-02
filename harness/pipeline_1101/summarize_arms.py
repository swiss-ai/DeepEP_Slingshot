#!/usr/bin/env python3
"""Per-arm medians across counterbalanced repeat gates.

usage: summarize_arms.py RESULTS_DIR GATE_REGEX [--ref ARM] [--ops OP,OP] [--md]

RESULTS_DIR holds one directory per gate with direct/ep/repeatability.json (the harness's
per-gate medians of the per-iteration rank maximum). GATE_REGEX selects the repeat gates
(for example '^85[456]\\d-' for F's 8540-8563). The arm is the second dash-separated field of
the gate name (8541-dfirst4-repeat1 -> dfirst4). For every (tokens, dtype, routing, operation)
the script reports the median over the selected gates of each arm, the spread across repeats,
and the change relative to --ref. Nothing is fitted or interpolated.
"""
import argparse, collections, json, re, statistics
from pathlib import Path

ap = argparse.ArgumentParser()
ap.add_argument('results_dir')
ap.add_argument('gate_regex')
ap.add_argument('--ref', default=None, help='arm used as the baseline for relative changes')
ap.add_argument('--ops', default='dispatch_fresh,dispatch_cached,combine',
                help='comma-separated operations to report (default: dispatch_fresh,dispatch_cached,combine)')
ap.add_argument('--md', action='store_true', help='emit a Markdown table instead of plain text')
args = ap.parse_args()

pattern = re.compile(args.gate_regex)
ops = args.ops.split(',')
samples = collections.defaultdict(lambda: collections.defaultdict(list))  # key -> arm -> [us,...]
gates_per_arm = collections.Counter()
for gate in sorted(Path(args.results_dir).iterdir()):
    if not pattern.search(gate.name):
        continue
    rep = gate / 'direct/ep/repeatability.json'
    fin = gate / 'FINISHED.json'
    if not rep.exists() or not fin.exists():
        continue
    record = json.loads(fin.read_text())
    if record.get('qualification', {}).get('status') != 'PASS':
        print(f'# skipping {gate.name}: qualification {record.get("qualification")}')
        continue
    arm = gate.name.split('-')[1]
    gates_per_arm[arm] += 1
    for r in json.loads(rep.read_text()):
        if r['operation'] not in ops:
            continue
        key = (r['tokens_per_gpu'], r['dispatch_dtype'], r['routing'], r['operation'])
        samples[key][arm].append(r['repeat_median_us'])

arms = sorted(gates_per_arm, key=lambda a: (a != args.ref, a))
ref = args.ref if args.ref in gates_per_arm else arms[0]
print('# gates per arm:', dict(gates_per_arm), '| reference:', ref)

def cell(values, base):
    med = statistics.median(values)
    spread = (max(values) - min(values)) / med * 100 if len(values) > 1 else 0.0
    rel = '' if base is None else f' ({(med / base - 1) * 100:+.1f} %)'
    return f'{med / 1000:.4f} ms ±{spread:.1f}%{rel}'

if args.md:
    print('| tokens | dtype | routing | operation | ' + ' | '.join(arms) + ' |')
    print('|---:|---|---|---|' + '---:|' * len(arms))
for key in sorted(samples):
    row = samples[key]
    base = statistics.median(row[ref]) if ref in row else None
    cells = [cell(row[a], None if a == ref else base) if a in row else '-' for a in arms]
    tokens, dtype, routing, op = key
    if args.md:
        print(f'| {tokens} | {dtype} | {routing} | {op} | ' + ' | '.join(cells) + ' |')
    else:
        print(f'{tokens:6d} {dtype:4s} {routing:8s} {op:15s} ' + '  '.join(f'{a}={c}' for a, c in zip(arms, cells)))
