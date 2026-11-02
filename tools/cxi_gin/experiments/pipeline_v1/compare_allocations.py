"""Compare complete matched ordinary repeats on two distinct node pairs."""
import argparse
import csv
import itertools
import json
from pathlib import Path
import statistics
import subprocess
import sys


def jsonlines(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('previous', type=Path)
    p.add_argument('current', type=Path)
    p.add_argument('--families', nargs=2, default=['packed-i16', 'allocation2-packed-i16'])
    a = p.parse_args()
    gathered, provenance = [], []
    reference = {}
    for job, family in zip([a.previous, a.current], a.families):
        subprocess.run([sys.executable, str(Path(__file__).with_name('analyze_variants.py')), str(job)], check=True)
        with (job / 'variant-analysis/repeats.csv').open() as f:
            values = [v for v in csv.DictReader(f) if v['experiment'] in [family + '-q129', family + '-q257']]
        expected = set(itertools.product(['129', '257'], ['4096', '16384'],
            ['dispatch_fresh', 'dispatch_cached', 'combine'], ['1', '2', '3']))
        assert len(values) == len(expected) and {
            (v['contexts'], v['tokens'], v['operation'], v['repeat']) for v in values} == expected, 'Need all three qualified repeats in both jobs'
        assert all(v['snapshot'] == 'source-zero-packed-v7' and v['variant'] == 'marker-zero' and
            v['sms'] == '64' and v['interval'] == '16' and v['model'] == 'v4flash' and
            v['dtype'] == 'fp8' and v['routing'] == 'mixed' for v in values)
        nodes, source_hashes = set(), set()
        for name in sorted({v['gate'] for v in values}):
            gate = job / 'results/results' / name
            finish = json.loads((gate / 'FINISHED.json').read_text())
            env = finish['spec']['environment']
            assert env['CXI_DEVICE_TRACE'] == '0' and env['CXI_EP_PACK_ROWS'] == '1'
            contexts = env['CXI_EP_CONTEXTS']
            for rank in range(8):
                records = jsonlines(gate / 'direct/ep' / ('manifest-rank%d.jsonl' % rank))
                assert len(records) == 1
                record = records[0]
                assert record['rank'] == rank and record['ep'] == 8
                nodes.add(record['hostname']); source_hashes.add(record['deployed_source_sha256'])
                args = {k: v for k, v in record['args'].items() if k != 'output'}
                settings = dict(args=args, scripts=record['script_hashes'],
                    source=record['deployed_source_sha256'], torch=record['torch'], cuda=record['cuda'])
                key = ('settings', contexts, rank)
                assert settings == reference.setdefault(key, settings), 'Source/harness/settings differ'
                for case in jsonlines(gate / 'direct/ep' / ('correctness-rank%d.jsonl' % rank)):
                    key = ('payload', contexts, rank, case['tokens_per_gpu'])
                    data = {k: case[k] for k in ['hidden', 'experts', 'topk', 'seed', 'route_sha256',
                        'input_sha256', 'unique_remote_node_rows', 'packed_remote_rows', 'forward_chunk']}
                    assert data == reference.setdefault(key, data), 'Model/routing/input differs'
                    assert case['packed_remote_rows'] is True and case['forward_chunk'] == 3
        assert len(nodes) == 2 and len(source_hashes) == 1
        provenance.append(dict(job=job.name, nodes=sorted(nodes), source_sha256=next(iter(source_hashes))))
        gathered.append(values)
    assert not set(provenance[0]['nodes']) & set(provenance[1]['nodes']), 'Node pairs are not disjoint'
    rows = []
    for contexts, tokens, operation in itertools.product(['129', '257'], ['4096', '16384'],
                                                        ['dispatch_fresh', 'dispatch_cached', 'combine']):
        row = dict(contexts=int(contexts), tokens=int(tokens), operation=operation)
        for label, values in zip(['previous', 'current'], gathered):
            times = [float(v['median_ms']) for v in values if
                (v['contexts'], v['tokens'], v['operation']) == (contexts, tokens, operation)]
            row[label + '_ms'] = statistics.median(times)
            row[label + '_min_ms'], row[label + '_max_ms'] = min(times), max(times)
        row['change_percent'] = 100 * (row['current_ms'] / row['previous_ms'] - 1)
        rows.append(row)
    output = a.current / 'allocation-comparison'
    output.mkdir(exist_ok=True)
    (output / 'provenance.json').write_text(json.dumps(provenance, indent=2) + '\n')
    with (output / 'comparison.csv').open('w') as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0])); writer.writeheader(); writer.writerows(rows)
    text = ['# Two-node-pair reproduction', '',
        'Three ordinary repeats per configuration; matched deployed source, harness, payload and routing. '
        'Values are medians of repeat medians of per-iteration rank-max CUDA latency. '
        'Differences include node-pair and time-of-run variation; this is not a population confidence interval.', '',
        '| Contexts | Tokens/GPU | Operation | Previous ms | Current ms | Change |',
        '|---:|---:|---|---:|---:|---:|']
    text += ['| {contexts} | {tokens} | {operation} | {previous_ms:.4f} | {current_ms:.4f} | {change_percent:+.2f}% |'.format(**r) for r in rows]
    (output / 'summary.md').write_text('\n'.join(text) + '\n')
    print(output)


if __name__ == '__main__':
    main()
