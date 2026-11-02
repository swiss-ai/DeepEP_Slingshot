#!/usr/bin/env python3
"""Report all-rank SGLang wrapper timings, excluding cold/warmup iterations.

Smoke results remain correctness evidence. A performance table requires >=10
warmups and >=30 measured iterations on all eight ranks for every requested case.
"""
import argparse
import csv
import json
import math
from pathlib import Path
import statistics

from validate_gate import qualify


def summarize(result):
    result = Path(result)
    finished = json.loads((result / 'FINISHED.json').read_text())
    if finished.get('returncode') != 0 or finished.get('error'):
        raise ValueError('The SGLang request did not complete successfully')
    spec = finished['spec']
    if spec.get('qualification') != 'sglang':
        raise ValueError('This is not a SGLang qualification request')
    verdict = qualify(result, spec)
    ranks = [json.loads((result / verdict['transport'] / 'smoke' / ('rank%d.json' % r)).read_text()) for r in range(8)]
    env = spec.get('environment', {})
    warmup, iterations = int(env.get('CXI_SGLANG_WARMUP', '0')), int(env.get('CXI_SGLANG_ROUNDS', '3'))
    if warmup < 10 or iterations < 30:
        return {'status': 'CORRECTNESS_ONLY', 'reason': 'requires >=10 warmups and >=30 measured iterations',
                'qualification': verdict}, []
    if any(r.get('warmup_iterations') != warmup or r.get('timed_iterations') != iterations for r in ranks):
        raise ValueError('Rank timing schedule differs from the submitted request')
    matrix = [{(c['dtype'], c['tokens'], c['step']): c for c in r['cases']} for r in ranks]
    cases = sorted({(c['dtype'], c['tokens']) for c in ranks[0]['cases']})
    rows = []
    for dtype, tokens in cases:
        for operation in ['dispatch', 'combine']:
            maxima, walls = [], []
            for step in range(warmup, warmup + iterations):
                group = [m[dtype, tokens, step] for m in matrix]
                values = [c[operation + '_cuda_us'] for c in group]
                host = [c[operation + '_wrapper_ms'] * 1000 for c in group]
                if not all(math.isfinite(v) and v > 0 for v in values + host):
                    raise ValueError('Invalid timing sample')
                maxima.append(max(values)); walls.append(max(host))
            ordered = sorted(maxima)
            rows.append({'model_geometry': verdict['model_geometry'], 'ep': 8,
                         'transport': verdict['transport'], 'gin_type': verdict['gin_type'],
                         'tokens_per_gpu': tokens, 'dispatch_dtype': dtype, 'combine_dtype': 'bf16',
                         'operation': operation, 'warmup_iterations': warmup, 'measured_iterations': iterations,
                         'median_rank_max_cuda_us': statistics.median(maxima),
                         'p95_rank_max_cuda_us': ordered[math.ceil(0.95 * len(ordered)) - 1],
                         'min_rank_max_cuda_us': min(maxima), 'max_rank_max_cuda_us': max(maxima),
                         'median_rank_max_wrapper_us': statistics.median(walls),
                         'actual_scatter_gather': verdict['actual_scatter_gather'],
                         'actual_expert_kernels': verdict['actual_expert_kernels'],
                         'routing': ranks[0]['routing'],
                         'scope': 'SGLang synchronized wrapper; dispatch includes quantization; expert computation excluded; not TTFT'})
    return {'status': 'PASS', 'qualification': verdict, 'timing_rows': len(rows)}, rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('result', type=Path)
    args = parser.parse_args()
    status, rows = summarize(args.result)
    (args.result / 'sglang-timing-validation.json').write_text(json.dumps(status, indent=2) + '\n')
    if rows:
        with (args.result / 'sglang-wrapper-timings.csv').open('w', newline='') as file:
            writer = csv.DictWriter(file, fieldnames=list(rows[0])); writer.writeheader(); writer.writerows(rows)
    print(json.dumps(status, indent=2))


if __name__ == '__main__':
    main()
