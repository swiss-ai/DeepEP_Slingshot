"""Summarize qualified untraced progress-batching repeats; label partial data."""
import argparse
import csv
import json
import re
import statistics
from collections import defaultdict
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('job', type=Path)
    job = parser.parse_args().job
    rows = []
    issues = []
    for finished in sorted((job / 'results/results').glob('*-repeat*/FINISHED.json')):
        if not re.fullmatch(r'\d+-interval(?:3|6|8|16)-repeat[123]', finished.parent.name):
            continue
        record = json.loads(finished.read_text())
        spec = record['spec']
        if record.get('returncode') != 0 or record.get('qualification', {}).get('status') != 'PASS':
            issues.append(finished.parent.name + ': incomplete or failed')
            continue
        env = spec['environment']
        assert env['CXI_EP_CONTEXTS'] == '129', 'interval analysis requires matched context count'
        interval = int(env['CXI_EP_UPDATE_INTERVAL'])
        repeat = int(spec['name'].rsplit('repeat', 1)[1])
        reports = list((finished.parent / 'compiler-reports').rglob('*.txt'))
        # Reject results whose compiler invocation does not prove the requested setting.
        if not reports or not all('-DCXI_EP_UPDATE_INTERVAL=' + str(interval) + ' ' in p.read_text()
                                  for p in reports):
            issues.append(finished.parent.name + ': missing/mismatched compiler defines')
            continue
        with (finished.parent / 'direct/ep/summary.csv').open() as file:
            for value in csv.DictReader(file):
                if value['operation'] not in ('dispatch_fresh', 'dispatch_cached', 'combine'):
                    continue
                rows.append(dict(interval=interval, repeat=repeat, model=value['model'],
                                 tokens=int(value['tokens_per_gpu']), operation=value['operation'],
                                 median_ms=float(value['median_rank_max_us']) / 1000,
                                 p95_ms=float(value['p95_rank_max_us']) / 1000,
                                 source=finished.parent.name))
    out = job / 'pipeline-analysis'
    out.mkdir(exist_ok=True)
    if rows:
        with (out / 'repeats.csv').open('w') as file:
            writer = csv.DictWriter(file, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    groups = defaultdict(list)
    for row in rows:
        groups[(row['tokens'], row['interval'], row['operation'])].append(row)
    complete = len(groups) == 24 and all({r['repeat'] for r in values} == {1, 2, 3}
                                       and len(values) == 3 for values in groups.values())
    text = ['# Progress batching: ' + ('complete' if complete and not issues else 'PARTIAL'), '',
            'Untraced median of per-iteration rank-max latency; repeats share one node pair.', '',
            '| Tokens/rank | Update interval | Operation | Repeats | Median ms | Repeat range ms |',
            '|---:|---:|---|---:|---:|---|']
    for (tokens, interval, op), values in sorted(groups.items()):
        times = [r['median_ms'] for r in values]
        text.append('| %d | %d | %s | %d | %.4f | %.4f–%.4f |' %
                    (tokens, interval, op, len(values), statistics.median(times), min(times), max(times)))
    text += ['', 'Do not add role intervals or infer NIC wire bandwidth from these end-to-end times.']
    if issues:
        text += ['', 'Excluded:', ''] + ['- ' + issue for issue in issues]
    (out / 'summary.md').write_text('\n'.join(text) + '\n')
    print(out / 'summary.md')


if __name__ == '__main__':
    main()
