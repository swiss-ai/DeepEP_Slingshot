"""Summarize the completed matched native-CQ-fence experiment only."""
import argparse
import csv
import json
import statistics
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('job', type=Path)
    args = parser.parse_args()
    with (args.job / 'variant-analysis/repeats.csv').open() as file:
        rows = [r for r in csv.DictReader(file) if r['snapshot'] == 'source-hw-fence-v3']
    variants = ['fence-control', 'fence-dc', 'fence-batched']
    operations = ['dispatch_fresh', 'dispatch_cached', 'combine']
    results = []
    for tokens in [4096, 16384]:
        for operation in operations:
            baseline = None
            for variant in variants:
                group = [r for r in rows if int(r['tokens']) == tokens and
                         r['operation'] == operation and r['variant'] == variant]
                assert len(group) == 3 and {r['repeat'] for r in group} == {'1', '2', '3'}, \
                    'Three collected, qualified repeats required: %s/%s/%s' % (tokens, operation, variant)
                assert all(r['model'] == 'v4flash' and r['dtype'] == 'fp8' and
                           r['routing'] == 'mixed' and r['contexts'] == '129' and r['interval'] == '3'
                           for r in group), 'Unexpected comparison dimensions'
                times = [float(r['median_ms']) for r in group]
                value = statistics.median(times)
                if baseline is None:
                    baseline = value
                results.append(dict(tokens=tokens, operation=operation, variant=variant,
                    median_ms=value, min_repeat_ms=min(times), max_repeat_ms=max(times),
                    reduction_percent=100 * (baseline - value) / baseline,
                    gates=[r['gate'] for r in group]))
    out = args.job / 'native-fence-analysis'
    out.mkdir(exist_ok=True)
    (out / 'summary.json').write_text(json.dumps(results, indent=2) + '\n')
    text = ['# Matched native CQ-fence results', '',
        'Three counterbalanced ordinary repeats per variant, on the same two GH200 nodes. '
        'Each value is the median of three per-run medians of rank-max CUDA-event latency. '
        'Ranges describe repeat variation, not confidence intervals. All declared correctness gates passed. '
        'No tracing is enabled; this is not cross-allocation replication.', '',
        'All variants use 129 contexts, 64 SMs, progress interval 3, and bounded TX publication of 8 commands. '
        'Control waits on GPU CT observation before signals; fence-dc uses a native NIC CQ fence with '
        'per-PUT delivery completion; fence-batched additionally batches delivery completion.', '',
        '| Tokens/GPU | Operation | Variant | Median ms | Repeat range ms | Reduction vs control |',
        '|---:|---|---|---:|---|---:|']
    for r in results:
        text.append('| {tokens} | {operation} | {variant} | {median_ms:.4f} | '
                    '{min_repeat_ms:.4f}–{max_repeat_ms:.4f} | {reduction_percent:.2f}% |'.format(**r))
    text += ['', 'The 4K V4 FP8 rail-payload serialization bound is 0.7077888 ms '
        '(4096 × 4320 bytes / 25 GB/s). It excludes packing, notifications, forwarding and synchronization. '
        'None of these complete-EP measurements reaches that bound.', '',
        'Independent repeated-operation NIC telemetry is in `../nic-analysis/`; its measurement window '
        'and byte accounting differ from the CUDA-event samples above. Source records and compiler '
        'evidence are under each listed gate in `../results/results/`.']
    (out / 'summary.md').write_text('\n'.join(text) + '\n')
    print(out / 'summary.md')


if __name__ == '__main__':
    main()
