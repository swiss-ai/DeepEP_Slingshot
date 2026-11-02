"""Keep transport candidates, context counts and progress intervals separate."""
import argparse
import csv
import json
import itertools
import math
import re
import statistics
from collections import defaultdict
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('job', type=Path)
    args = parser.parse_args()
    rows, excluded = [], []
    for path in sorted((args.job / 'results/results').glob('*-repeat*/FINISHED.json')):
        record = json.loads(path.read_text())
        spec = record['spec']
        env = spec['environment']
        match = re.search(r'-repeat([123])$', spec['name'])
        if not match or spec['qualification'] != 'ep' or env.get('CXI_DEVICE_TRACE', '0') != '0':
            continue
        if record.get('returncode') != 0 or record.get('qualification', {}).get('status') != 'PASS':
            excluded.append(path.parent.name + ': failed/incomplete')
            continue
        interval = env.get('CXI_EP_UPDATE_INTERVAL', '3')
        reports = list((path.parent / 'compiler-reports').rglob('*.txt'))
        if not reports or not all('-DCXI_EP_UPDATE_INTERVAL=' + interval + ' ' in p.read_text()
                                  for p in reports):
            excluded.append(path.parent.name + ': compiler setting missing/mismatched')
            continue
        summary = path.parent / 'direct/ep/summary.csv'
        if not summary.is_file():
            excluded.append(path.parent.name + ': summary not collected yet')
            continue
        with summary.open() as file:
            values = list(csv.DictReader(file))
        operations = ('dispatch_fresh', 'dispatch_cached', 'combine')
        expected = set(itertools.product(env['CXI_EP_MODELS'].split(), env['CXI_EP_TOKENS'].split(),
            env['CXI_EP_DTYPES'].split(), env['CXI_EP_ROUTING'].split(), env['CXI_EP_SEEDS'].split(), operations))
        selected = [v for v in values if v.get('operation') in operations]
        try:
            observed = [(v['model'], v['tokens_per_gpu'], v['dispatch_dtype'], v['routing'], v['seed'], v['operation']) for v in selected]
            complete = (set(observed) == expected and len(observed) == len(expected) and
                        all(math.isfinite(float(v['median_rank_max_us'])) and float(v['median_rank_max_us']) > 0 for v in selected))
        except (KeyError, TypeError, ValueError):
            complete = False
        if not complete:
            excluded.append(path.parent.name + ': collected summary incomplete or malformed')
            continue
        try:
            for rank in range(8):
                cases = [json.loads(line) for line in
                    (path.parent / 'direct/ep' / ('correctness-rank%d.jsonl' % rank)).read_text().splitlines()]
                assert len(cases) * len(operations) == len(expected)
                assert all(case['rank'] == rank and case['status'] == 'PASS' and
                    case['allocated_contexts'] == int(env['CXI_EP_CONTEXTS']) and
                    case['qps'] == int(env['CXI_EP_CONTEXTS']) and
                    case['actual_sms'] == int(env['CXI_EP_SMS']) and
                    case['progress_update_interval'] == int(interval) and
                    ('CXI_EP_MERGE_FINAL_TAIL' not in env or
                     case.get('merged_final_tail') is bool(int(env['CXI_EP_MERGE_FINAL_TAIL']))) and
                    case.get('forward_chunk', 3) == int(env.get('CXI_EP_FORWARD_CHUNK', '3'))
                    for case in cases)
        except (OSError, ValueError, KeyError, AssertionError):
            excluded.append(path.parent.name + ': actual per-rank context/settings evidence missing or mismatched')
            continue
        for value in selected:
            family = re.sub(r'^[0-9][0-9a-z]*-', '', re.sub(r'-repeat[123]$', '', spec['name']))
            rows.append(dict(snapshot=Path(spec['snapshot']).name, variant=env['CXI_VARIANT'],
                experiment=family,
                contexts=int(env['CXI_EP_CONTEXTS']), sms=int(env['CXI_EP_SMS']), interval=int(interval),
                repeat=int(match[1]), model=value['model'], tokens=int(value['tokens_per_gpu']),
                dtype=value.get('dispatch_dtype', env['CXI_EP_DTYPES']),
                routing=value.get('routing', env['CXI_EP_ROUTING']), operation=value['operation'],
                median_ms=float(value['median_rank_max_us']) / 1000,
                p95_ms=float(value['p95_rank_max_us']) / 1000, gate=path.parent.name))
    out = args.job / 'variant-analysis'
    out.mkdir(exist_ok=True)
    if rows:
        with (out / 'repeats.csv').open('w') as file:
            writer = csv.DictWriter(file, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    elif (out / 'repeats.csv').exists():
        (out / 'repeats.csv').unlink()
    groups = defaultdict(list)
    keys = ('snapshot', 'variant', 'experiment', 'contexts', 'sms', 'interval', 'model', 'tokens', 'dtype', 'routing', 'operation')
    for row in rows:
        groups[tuple(row[k] for k in keys)].append(row)
    text = ['# Qualified untraced results', '',
            'Medians of per-iteration rank-max latency. Three repeats are required per configuration; '
            'pending groups are not inferred from completed groups. Same node pair; not cross-allocation replication.', '',
            '| Snapshot / variant | Experiment | Contexts / SMs / interval | Model / tokens / dtype / routing | Operation | Repeats | Median ms | Range ms |',
            '|---|---|---|---|---|---:|---:|---|']
    for key, values in sorted(groups.items()):
        assert len({v['repeat'] for v in values}) == len(values), 'duplicate repeat in one configuration'
        snapshot, variant, experiment, contexts, sms, interval, model, tokens, dtype, routing, operation = key
        times = [v['median_ms'] for v in values]
        text.append('| %s / %s | %s | %d / %d / %d | %s / %d / %s / %s | %s | %d/3 | %.4f | %.4f–%.4f |' %
                    (snapshot, variant, experiment, contexts, sms, interval, model, tokens, dtype, routing, operation,
                     len(values), statistics.median(times), min(times), max(times)))
    if excluded:
        text += ['', 'Excluded:', ''] + ['- ' + item for item in excluded]
    (out / 'summary.md').write_text('\n'.join(text) + '\n')
    print(out / 'summary.md')


if __name__ == '__main__':
    main()
