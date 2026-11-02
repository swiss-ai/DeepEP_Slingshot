#!/usr/bin/env python3
"""Report validated EP samples, keeping useful payload and MAC bytes separate."""
import argparse
import csv
import json
from pathlib import Path
import statistics


def records(root, pattern):
    return [json.loads(line) for path in sorted(root.glob(pattern))
            for line in path.read_text().splitlines() if line]


def write_csv(path, rows):
    if rows:
        with path.open('w', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('root', type=Path)
    args = parser.parse_args()
    latency, nic_rates, runs = [], [], []
    for manifest_path in sorted(args.root.glob('leases/*/results/*/*/ep/manifest-rank0.jsonl')):
        root = manifest_path.parent
        run = str(root.relative_to(args.root))
        validation = root / 'validation.json'
        if not validation.exists():
            runs.append({'run': run, 'status': 'INCOMPLETE_OR_FAILED'})
            continue
        status = json.loads(validation.read_text())
        if status.get('status') != 'PASS' or status.get('ep') != 8:
            runs.append({'run': run, 'status': 'UNQUALIFIED', 'validation': status})
            continue
        checks = records(root, 'correctness-rank*.jsonl')
        assert len(checks) == status['correctness_records']
        assert all(check['status'] == 'PASS' for check in checks)
        manifests = records(root, 'manifest-rank*.jsonl')
        assert len(manifests) == 8 and all((root / f'DONE-rank{i}').exists() for i in range(8))
        types = {m['environment']['NCCL_GIN_TYPE'] for m in manifests}
        assert len(types) == 1
        gin_type = types.pop()
        assert gin_type in ('2', '6')
        transport = 'direct_cxi' if gin_type == '6' else 'proxy_ofi_cxi'
        cases = {}
        for check in checks:
            key = tuple(check[field] for field in ('seed', 'model', 'tokens_per_gpu', 'dispatch_dtype', 'routing'))
            cases.setdefault(key, []).append(check)
        for row in csv.DictReader((root / 'summary.csv').open()):
            key = (int(row['seed']), row['model'], int(row['tokens_per_gpu']), row['dispatch_dtype'], row['routing'])
            group = cases[key]
            assert len(group) == 8 and len({x['actual_sms'] for x in group}) == 1
            assert len({x['qps'] for x in group}) == 1
            median = float(row['median_rank_max_us'])
            op = row['operation']
            payload_bytes = None
            if op in ('dispatch_fresh', 'dispatch_cached', 'combine'):
                element_bytes = 2 if op == 'combine' or row['dispatch_dtype'] == 'bf16' else 1
                # Pinned hybrid EP sends one activation copy per remote node,
                # through the matching local rail; reverse combine reduces the
                # remote-node contributions before returning them on that rail.
                payload_bytes = max(x['unique_remote_node_rows'] * x['hidden'] * element_bytes for x in group)
            latency.append(dict(run=run, transport=transport, gin_type=gin_type,
                model=row['model'], tokens_per_gpu=row['tokens_per_gpu'], seed=row['seed'],
                routing=row['routing'], dispatch_dtype=row['dispatch_dtype'], operation=op,
                actual_sms=group[0]['actual_sms'], qps=group[0]['qps'],
                median_rank_max_us=median, p95_rank_max_us=float(row['p95_rank_max_us']),
                max_rail_activation_payload_bytes=payload_bytes,
                ideal_activation_only_25GBps_us=payload_bytes / 25000 if payload_bytes is not None else None,
                useful_activation_GBps=payload_bytes / (median * 1000) if payload_bytes is not None else None,
                max_process_cpu_core_equivalents=row['max_process_cpu_core_equivalents']))
        for window in records(root, 'nic-node*.jsonl'):
            for counter, rate in window['rates'].items():
                nic_rates.append(dict(run=run, transport=transport, hostname=window['hostname'],
                    counter=counter, model=window['model'], tokens_per_gpu=window['tokens_per_gpu'],
                    routing=window['routing'], dispatch_dtype=window['dispatch_dtype'],
                    operation=window['operation'], **rate,
                    fraction_nominal_25GBps=rate['GBps'] / 25))
        runs.append({'run': run, 'status': 'PASS', 'transport': transport, 'validation': status})
    destination = args.root / 'performance'
    destination.mkdir(exist_ok=True)
    write_csv(destination / 'latency_payload.csv', latency)
    write_csv(destination / 'nic_mac_rates.csv', nic_rates)
    (destination / 'status.json').write_text(json.dumps(runs, indent=2) + '\n')
    notes = '''# Direct CXI GIN performance evidence

Only complete eight-rank EP runs with passing correctness/summary validation
enter these tables. API-only transport probes are excluded. A run can still be
a short diagnostic; use its manifest to check warmups, repeats and timed samples.

`latency_payload.csv` reports per-iteration rank-max latency summaries and the
maximum rail's useful activation bytes. Its ideal floor assumes 25 GB/s in one
direction per NIC and the pinned hybrid algorithm's remote-node deduplication.
It excludes scales, routing metadata, packet headers, acknowledgements, NVLink,
packing, synchronization and launch costs. It is a payload-only lower bound,
not a predicted achievable latency or a measured NIC ceiling.

`nic_mac_rates.csv` contains separately sampled TX/RX MAC-counter window rates,
including synchronization/control traffic and gaps between iterations. Do not
add TX and RX and compare that sum with a single-direction 25 GB/s rating.
Useful activation bandwidth and MAC counter bandwidth have different byte counts.

Fresh dispatch is the primary serving comparison. Cached dispatch is diagnostic.
Process CPU core-equivalents include launches and synchronization; they do not
identify a NIC progress thread. Trace-backed kernel costs and unprofiled timing
samples must remain separate. None of these communication-only results is TTFT.

Before forming a proxy/direct speedup, match model, tokens, dtype, routing, seed,
SM/QP count, source snapshot, warmups, iterations, and route/input hashes. Prefer
the same allocation/node pair. A proxy control is not proof of the best possible
CPU-proxy performance without an independent proxy-tuning sweep.
'''
    (destination / 'README.md').write_text(notes)
    print(json.dumps({'validated_runs': sum(r['status'] == 'PASS' for r in runs),
                      'latency_rows': len(latency), 'nic_rows': len(nic_rates),
                      'output': str(destination)}))


if __name__ == '__main__':
    main()
