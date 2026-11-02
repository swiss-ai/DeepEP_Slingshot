#!/usr/bin/env python3
"""Compare only validated, identically configured SGLang direct/proxy runs."""
import argparse
import csv
import json
from pathlib import Path

from summarize_sglang import summarize


def match_rank(direct, proxy):
    fields = ['rank', 'hostname', 'job', 'cpu_affinity', 'source', 'test_sha256',
              'native_extension_sha256', 'nccl_sha256', 'model_geometry', 'hidden',
              'experts', 'topk', 'routing', 'warmup_iterations', 'timed_iterations',
              'actual_sglang_scatter_gather', 'actual_sglang_expert_kernels']
    for key in fields:
        if key not in direct or key not in proxy or direct[key] != proxy[key]:
            raise ValueError('Unmatched/missing rank field: ' + key)
    for key in ['original_dispatcher_sha256', 'patched_dispatcher_sha256', 'adapter_sha256']:
        if direct['overlay_manifest'][key] != proxy['overlay_manifest'][key]:
            raise ValueError('Unmatched SGLang source: ' + key)
    key = lambda c: (c['dtype'], c['tokens'], c['step'])
    a, b = [{key(c): c for c in record['cases']} for record in [direct, proxy]]
    if a.keys() != b.keys():
        raise ValueError('Unmatched case matrix')
    for case in a:
        for field in ['input_sha256', 'route_sha256', 'weights_sha256', 'received_tokens',
                      'warmup', 'exact_dispatch_reference']:
            if field not in a[case] or field not in b[case] or a[case][field] != b[case][field]:
                raise ValueError('Unmatched/missing case field: ' + field)
        if a[case]['exact_dispatch_reference'] != 'PASS':
            raise ValueError('Exact dispatch validation did not pass')


def compare(direct, proxy):
    direct, proxy = Path(direct), Path(proxy)
    summaries = [summarize(p) for p in [direct, proxy]]
    if any(status['status'] != 'PASS' for status, _ in summaries):
        raise ValueError('Both runs require warmed performance qualification')
    if [s[0]['qualification']['transport'] for s in summaries] != ['direct', 'proxy']:
        raise ValueError('Expected direct followed by explicit proxy control')
    specs = [json.loads((p / 'FINISHED.json').read_text())['spec'] for p in [direct, proxy]]
    envs = [{k: v for k, v in s['environment'].items()
             if k not in ('CXI_TRANSPORT', 'CXI_TEST_TIMEOUT')} for s in specs]
    if envs[0] != envs[1]:
        raise ValueError('Unmatched submitted configuration')
    for rank in range(8):
        records = [json.loads((p / transport / 'smoke' / ('rank%d.json' % rank)).read_text())
                   for p, transport in [(direct, 'direct'), (proxy, 'proxy')]]
        match_rank(*records)
    key = lambda r: (r['model_geometry'], r['tokens_per_gpu'], r['dispatch_dtype'], r['operation'])
    tables = [{key(row): row for row in rows} for _, rows in summaries]
    if tables[0].keys() != tables[1].keys():
        raise ValueError('Unmatched timing rows')
    rows = []
    for k in sorted(tables[0]):
        a, b = [t[k] for t in tables]
        rows.append(dict(model_geometry=k[0], tokens_per_gpu=k[1], dispatch_dtype=k[2],
                         operation=k[3], direct_median_rank_max_cuda_us=a['median_rank_max_cuda_us'],
                         proxy_median_rank_max_cuda_us=b['median_rank_max_cuda_us'],
                         speedup=b['median_rank_max_cuda_us'] / a['median_rank_max_cuda_us'],
                         direct_p95_rank_max_cuda_us=a['p95_rank_max_cuda_us'],
                         proxy_p95_rank_max_cuda_us=b['p95_rank_max_cuda_us'],
                         scope=a['scope']))
    return {'status': 'PASS', 'ranks_matched': 8, 'rows': len(rows),
            'direct': str(direct), 'proxy': str(proxy),
            'scope': 'same allocation, input/route/weight hashes, source/binary hashes and submitted configuration'}, rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('direct', type=Path)
    parser.add_argument('proxy', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    status, rows = compare(args.direct, args.proxy)
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / 'validation.json').write_text(json.dumps(status, indent=2) + '\n')
    with (args.output / 'comparison.csv').open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader(); writer.writerows(rows)
    print(json.dumps(status, indent=2))


if __name__ == '__main__':
    main()
