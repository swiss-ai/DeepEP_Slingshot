#!/usr/bin/env python3
"""Analyze separate instrumented EP traces; never turn them into latency claims.

GPU kernel intervals are merged across streams to avoid double counting. Their
envelope includes between-iteration gaps, and host API durations can overlap
GPU execution. Neither is an attribution of time inside a persistent kernel.
"""
import argparse
from collections import defaultdict
import csv
import json
import math
from pathlib import Path
import statistics

from validate_gate import qualify


def interval_stats(intervals):
    if not intervals:
        return dict(span_us=0, union_us=0, gap_us=0, overlap_us=0)
    merged = []
    total = 0
    for start, end in sorted(intervals):
        if not all(math.isfinite(v) for v in (start, end)) or end < start:
            raise ValueError('Invalid trace interval')
        total += end - start
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(end, merged[-1][1])
        else:
            merged.append([start, end])
    span = merged[-1][1] - merged[0][0]
    union = sum(end - start for start, end in merged)
    return dict(span_us=span, union_us=union, gap_us=span - union,
                overlap_us=total - union)


def analyze_events(events, operation, iterations):
    complete = [e for e in events if e.get('ph') == 'X' and 'dur' in e]
    kernels = [e for e in complete if 'kernel' in e.get('cat', '').lower()]
    if not kernels:
        raise ValueError('No GPU kernel activity; CPU-only traces are insufficient')
    prefix = 'ep4k/' + operation + '/iteration'
    markers = [e['name'] for e in complete if e.get('name', '').startswith(prefix)]
    if sorted(markers) != sorted(prefix + str(i) for i in range(iterations)):
        raise ValueError('Missing or duplicate profiled iteration markers')
    # These categories reflect Kineto Chrome traces, not trace displayTimeUnit:
    # complete-event ts/dur values use Chrome trace microseconds.
    calls = [e for e in complete if e.get('cat') in ('cuda_runtime', 'cuda_driver')]
    waits = [e for e in calls if any(word in e.get('name', '').lower()
                                   for word in ('synchronize', 'waitevent'))]
    groups = defaultdict(list)
    for event in kernels:
        groups[event['name']].append(event['dur'])
    result = {'kernel_count': len(kernels), 'cuda_api_count': len(calls),
              'sync_api_count': len(waits), 'profiled_iterations': iterations}
    for name, subset in [('kernel', kernels), ('cuda_api', calls), ('sync_api', waits)]:
        values = interval_stats([(e['ts'], e['ts'] + e['dur']) for e in subset])
        result.update({name + '_' + k: v for k, v in values.items()})
    names = [dict(kernel=k, count=len(v), total_us=sum(v), median_us=statistics.median(v))
             for k, v in sorted(groups.items())]
    return result, names


def analyze(result):
    result = Path(result)
    finished = json.loads((result / 'FINISHED.json').read_text())
    if finished.get('returncode') != 0 or finished.get('error'):
        raise ValueError('Request did not finish successfully')
    spec = finished['spec']
    if spec.get('qualification') != 'ep':
        raise ValueError('Expected standalone EP qualification')
    verdict = qualify(result, spec)
    env = spec['environment']
    steps = int(env.get('CXI_EP_PROFILE_STEPS', '0'))
    if steps <= 0 or '4096' not in env.get('CXI_EP_TOKENS', '').split() or 'fp8' not in env.get('CXI_EP_DTYPES', '').split():
        raise ValueError('Request did not schedule the supported profiling cases')
    transport = env.get('CXI_TRANSPORT', 'direct')
    ep = result / transport / 'ep'
    seed = int(env.get('CXI_EP_SEEDS', '1').split()[0])
    expected = {(model, routing, operation, rank)
                for model in env.get('CXI_EP_MODELS', 'v4flash').split()
                for routing in env.get('CXI_EP_ROUTING', 'mixed').split()
                for operation in ('dispatch_fresh', 'dispatch_cached', 'combine', 'cycle')
                for rank in range(8)}
    actual = set()
    rows, kernel_rows = [], []
    identity = ('model', 'routing', 'rank', 'seed', 'tokens_per_gpu', 'dispatch_dtype',
                'input_sha256', 'route_sha256', 'gin_type', 'actual_sms', 'qps')
    for sidecar in sorted((ep / 'profiles').glob('*-summary.json')):
        summary = json.loads(sidecar.read_text())
        case = summary['case']
        key = case['model'], case['routing'], summary['operation'], summary['rank']
        if key not in expected or key in actual:
            raise ValueError('Unexpected or duplicate trace: ' + str(sidecar))
        if summary['profiled_iterations'] != steps or case['seed'] != seed or case['tokens_per_gpu'] != 4096 or case['dispatch_dtype'] != 'fp8':
            raise ValueError('Trace case differs from profiling request')
        if case['rank'] != summary['rank']:
            raise ValueError('Trace rank mismatch')
        correctness = [json.loads(line) for line in (ep / ('correctness-rank%d.jsonl' % case['rank'])).read_text().splitlines() if line.strip()]
        matches = [c for c in correctness if all(c.get(k) == case.get(k) for k in identity)]
        if len(matches) != 1 or matches[0]['status'] != 'PASS':
            raise ValueError('Trace does not match a unique passing correctness case')
        trace = sidecar.with_name(sidecar.name.replace('-summary.json', '.json'))
        stats, names = analyze_events(json.loads(trace.read_text())['traceEvents'], summary['operation'], steps)
        common = dict(model=case['model'], routing=case['routing'], operation=summary['operation'],
                      rank=case['rank'], transport=transport, gin_type=case['gin_type'])
        rows.append(dict(common, **stats))
        kernel_rows.extend(dict(common, **name) for name in names)
        actual.add(key)
    if actual != expected:
        raise ValueError('Missing traces: ' + repr(sorted(expected - actual)))
    return dict(status='DIAGNOSTIC_ONLY', qualification=verdict, traces=len(rows),
                scope='Instrumented per-rank timelines; no cross-node clock alignment or within-kernel stall attribution. Kernel gaps include between-iteration gaps. Host/GPU intervals overlap; do not add them or use these traces as headline latency.'), rows, kernel_rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('result', type=Path)
    args = parser.parse_args()
    status, rows, kernels = analyze(args.result)
    for filename, records in [('profile-timelines.csv', rows), ('profile-kernels.csv', kernels)]:
        with (args.result / filename).open('w', newline='') as file:
            writer = csv.DictWriter(file, fieldnames=list(records[0]))
            writer.writeheader()
            writer.writerows(records)
    (args.result / 'profile-validation.json').write_text(json.dumps(status, indent=2) + '\n')
    print(json.dumps(status, indent=2))


if __name__ == '__main__':
    main()
