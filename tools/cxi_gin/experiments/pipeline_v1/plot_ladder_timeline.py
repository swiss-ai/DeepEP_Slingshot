"""Plot one measured iteration per intervention, with independent rank clocks."""
import argparse
import json
import statistics
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Patch


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('job', type=Path)
    args = parser.parse_args()
    cases = [('21-ladder-coalesced-4096', 'Coalesced PUTs; final signal'),
             ('22-ladder-rows-final-4096', 'Row PUTs; final signal'),
             ('23-ladder-signals3-4096', 'Row PUTs; progress every 3')]
    colors = ['#cccccc', '#377eb8', '#ff9d32', '#68a86b']
    labels = ['Delay until this channel is ready', 'Submit (includes periodic signaling)',
              'Final signal + completion flush', 'Wait for remote readiness']
    figure, axes = plt.subplots(1, 3, figsize=(13.5, 5.4), sharey=True)
    evidence = []
    for axis, (name, title) in zip(axes, cases):
        directory = args.job / 'results/results' / name
        record = json.loads((directory / 'FINISHED.json').read_text())
        assert record['qualification']['status'] == 'PASS'
        ranks = []
        times = {}
        for rank in range(8):
            rows = [json.loads(line) for line in
                    (directory / 'direct/smoke' / ('contexts129-rank%d.jsonl' % rank)).read_text().splitlines()]
            ranks.append(rows)
            for row in rows:
                if 'cuda_ms' in row and row['iteration'] >= 5:
                    times.setdefault(row['iteration'], []).append(row['cuda_ms'])
        maxima = {i: max(values) for i, values in times.items()}
        assert all(len(values) == 8 for values in times.values())
        median = statistics.median(maxima.values())
        iteration = min(maxima, key=lambda i: (abs(maxima[i] - median), i))
        for rank, rows in enumerate(ranks):
            stamps = [r for r in rows if r.get('iteration') == iteration and 'channel' in r]
            assert len(stamps) == 256
            last = max(stamps, key=lambda r: r['received_ns'])
            first = min(r['ready_ns'] for r in stamps)
            points = [first] + [last[k] for k in ['ready_ns', 'submitted_ns', 'flushed_ns', 'received_ns']]
            for index, (start, stop) in enumerate(zip(points, points[1:])):
                axis.barh(rank, (stop-start)/1e6, left=(start-first)/1e6,
                          color=colors[index], height=0.64)
            evidence.append(dict(step=name, iteration=iteration, rank=rank, channel=last['channel'],
                                 first_ready_ns=first, **{k: last[k] for k in
                                 ['ready_ns', 'submitted_ns', 'flushed_ns', 'received_ns']}))
        axis.set_title(title + '\niteration %d; CUDA rank-max %.3f ms' % (iteration, maxima[iteration]), fontsize=11)
        axis.set_xlabel('ms from this rank’s first ready channel')
        axis.set_xlim(0, 2.9)
        axis.set_yticks(range(8), ['rank %d' % r for r in range(8)])
        axis.grid(axis='x', alpha=.2)
        axis.set_axisbelow(True)
    axes[0].invert_yaxis()
    figure.suptitle('Prepacked direct GIN probe: latest-finishing channel on each rank\n'
                   '4K rows/rank, 4,320 bytes/row, 129 contexts; measured timestamps', fontsize=13)
    figure.legend([Patch(color=color) for color in colors], labels, loc='lower center',
                  ncol=2, bbox_to_anchor=(.5, .07), frameon=False, fontsize=9)
    figure.text(.5, .015, 'Each row uses its own rank-local clock origin. Colored intervals are sequential on the selected channel; '
                'other channels overlap.\nCompletion includes transfer progress; it is not isolated NIC wire time. '
                'No NVLink relay, expert work, or initial readiness exchange is shown.',
                ha='center', fontsize=8.5)
    figure.tight_layout(rect=[0, .19, 1, .88])
    out = args.job / 'ladder-analysis'
    for suffix in ['pdf', 'png']:
        figure.savefig(out / ('transport-local-timeline.' + suffix), dpi=180)
    (out / 'transport-local-timeline-evidence.json').write_text(json.dumps(evidence, indent=2) + '\n')
    print(out / 'transport-local-timeline.pdf')


if __name__ == '__main__':
    main()
