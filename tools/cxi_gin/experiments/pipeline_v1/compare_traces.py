"""Compare all five qualified trace captures with separate ordinary timings."""
import argparse
import csv
import json
import statistics
from pathlib import Path

VARIANTS = [
    ('09c2-delivery-control-trace-decoder', 'source-delivery-v3', 'delivery-control', 'Delivery\ncontrol'),
    ('09d2-delivery-batched-trace-decoder', 'source-delivery-v3', 'delivery-batched', 'Batched\ndelivery'),
    ('09e2-fence-control-trace-decoder', 'source-hw-fence-v3', 'fence-control', 'Fence\ncontrol'),
    ('09f3-fence-dc-trace-decoder-validated', 'source-hw-fence-v3', 'fence-dc', 'Native\nfence'),
    ('09g3-fence-batched-trace-decoder-validated', 'source-hw-fence-v3', 'fence-batched', 'Fence +\nbatching'),
]


def read(path):
    with path.open() as file:
        return list(csv.DictReader(file))


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('job', type=Path)
    args = parser.parse_args(); root = args.job
    ordinary = read(root / 'variant-analysis/repeats.csv')
    records = []
    for gate, snapshot, variant, label in VARIANTS:
        path = root / 'results/results' / gate
        finished = json.loads((path / 'FINISHED.json').read_text())
        assert finished['returncode'] == 0 and finished['qualification']['status'] == 'PASS'
        assert finished['qualification']['device_traces'] == 'PASS'
        analysis = path / 'trace-analysis'
        timings, roles, stages = (read(analysis / name) for name in
                                  ['timing.csv', 'critical-role-waits.csv', 'critical-role-stages.csv'])
        assert len(timings) == 2 and len(roles) == 96
        for operation in ['dispatch_fresh', 'combine']:
            chosen = [r for r in ordinary if r['snapshot'] == snapshot and r['variant'] == variant
                      and r['operation'] == operation and r['tokens'] == '4096' and r['model'] == 'v4flash'
                      and r['dtype'] == 'fp8' and r['routing'] == 'mixed' and r['contexts'] == '129'
                      and r['interval'] == '3']
            assert len(chosen) == 3 and {r['repeat'] for r in chosen} == {'1', '2', '3'}
            timing = next(r for r in timings if r['operation'] == operation)
            role = 'dispatch_sender' if operation == 'dispatch_fresh' else 'combine_forwarder'
            selected = [r for r in roles if r['operation'] == operation and r['role'] == role]
            keys = {(r['rank'], r['iteration']) for r in selected}
            assert keys == {(str(rank), str(i)) for rank in range(8) for i in range(3)}
            def stage_median(event, selected_role=role):
                values = {(r['rank'], r['iteration']): float(r['clipped_union_ms']) for r in stages
                          if r['operation'] == operation and r['role'] == selected_role and int(r['event']) == event}
                assert set(values) <= keys
                return statistics.median(values.get(key, 0.) for key in keys)
            record = dict(gate=gate, variant=variant, label=label, operation=operation,
                ordinary_ms=statistics.median(float(r['median_ms']) for r in chosen),
                disabled_ms=(float(timing['disabled_before_ms']) + float(timing['disabled_after_ms'])) / 2,
                enabled_ms=float(timing['enabled_ms']),
                role_duration_ms=statistics.median(float(r['duration_ms']) for r in selected),
                wait_union_ms=statistics.median(float(r['wait_union_ms']) for r in selected),
                lock_ms=stage_median(200), ct_wait_ms=stage_median(207), publication_ms=stage_median(209),
                packing_ms=stage_median(112), contributor_wait_ms=stage_median(134),
                remote_tail_wait_ms=stage_median(138),
                forwarder_arrival_wait_ms=stage_median(105, 'dispatch_forwarder') if operation == 'dispatch_fresh' else 0.)
            records.append(record)
    output = root / 'trace-comparison'; output.mkdir(exist_ok=True)
    with (output / 'summary.csv').open('w') as file:
        writer = csv.DictWriter(file, fieldnames=list(records[0])); writer.writeheader(); writer.writerows(records)
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import numpy as np
    for operation in ['dispatch_fresh', 'combine']:
        rows = [r for r in records if r['operation'] == operation]
        figure, (top, bottom) = plt.subplots(2, 1, figsize=(11, 8), gridspec_kw={'height_ratios': [1, 1.4]})
        x = np.arange(len(rows)); width = .23
        for index, (key, label, color) in enumerate([
            ('ordinary_ms', 'Ordinary build: 3 repeats', '#68737d'),
            ('disabled_ms', 'Instrumented: recording disabled', '#248c9c'),
            ('enabled_ms', 'Instrumented: recording enabled', '#dd9951')]):
            bars = top.bar(x + (index - 1) * width, [r[key] for r in rows], width, label=label, color=color)
            top.bar_label(bars, fmt='%.2f', fontsize=8, padding=2)
        top.set_xticks(x, [r['label'] for r in rows]); top.set_ylabel('Rank-max latency (ms)')
        top.set_ylim(0, max(r[k] for r in rows for k in ['ordinary_ms', 'disabled_ms', 'enabled_ms']) * 1.25)
        top.legend(fontsize=8, ncol=3, loc='upper center'); top.spines[['top', 'right']].set_visible(False)
        columns = [('role_duration_ms', 'Role\nlifetime'), ('wait_union_ms', 'Wait\nunion'),
                   ('lock_ms', 'Context\nlock'), ('ct_wait_ms', 'CT\nwriteback'), ('publication_ms', 'TX\npublication')]
        columns += ([('packing_ms', 'Pack'), ('forwarder_arrival_wait_ms', 'Forwarder\narrival wait')]
                    if operation == 'dispatch_fresh' else
                    [('contributor_wait_ms', 'Local\ncontributors'), ('remote_tail_wait_ms', 'Remote\ntail')])
        data = np.array([[r[key] for key, _ in columns] for r in rows])
        heat = bottom.imshow(data, aspect='auto', cmap='Blues', vmin=0)
        for i in range(len(rows)):
            for j in range(len(columns)):
                bottom.text(j, i, '%.3f' % data[i, j], ha='center', va='center', fontsize=9,
                            color='white' if data[i, j] > data.max() * .6 else 'black')
        bottom.set_xticks(range(len(columns)), [label for _, label in columns], fontsize=9)
        bottom.set_yticks(range(len(rows)), [r['label'].replace('\n', ' ') for r in rows], fontsize=9)
        figure.colorbar(heat, ax=bottom, label='Local median ms', fraction=.025, pad=.02)
        title = 'Dispatch sender' if operation == 'dispatch_fresh' else 'Combine forwarder'
        bottom.set_title(title + ': latest-finishing warp on each rank; 24 observations', fontsize=11)
        figure.suptitle('V4 Flash EP8, 4096 tokens/GPU: ' + operation.replace('_', ' '), fontsize=14)
        figure.text(.5, .02, 'Heatmap scopes overlap: do not add columns. Dispatch arrival wait belongs to the forwarder.\n'
                    'Local GPU observations, not NIC wire time. Enabled captures are perturbed by tracing.', ha='center', fontsize=9)
        figure.tight_layout(rect=[0, .065, 1, .96])
        for extension in ['pdf', 'png']:
            figure.savefig(output / (operation + '-trace-comparison.' + extension), dpi=170)
        plt.close(figure)
    (output / 'README.md').write_text(
        'Five qualified captures, each eight ranks and three iterations per operation. Ordinary latency uses three '
        'separate timing repeats. Disabled and enabled results use instrumented builds. Heatmap values are '
        'medians of intervals clipped to the latest-finishing role warp on each rank. Missing stage events '
        'contribute zero; overlapping categories are not additive. Arrival wait is the dispatch forwarder, '
        'while the other dispatch columns describe the sender. No cross-node clock alignment or NIC wire '
        'duration is assumed. See source gate trace-analysis directories for all per-rank observations.\n')
    print(output)


if __name__ == '__main__':
    main()
