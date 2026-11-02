"""Qualified trace overhead and local critical-role wait envelopes.

Disabled measurements use the instrumented build with recording disabled. They
are not interchangeable with ordinary-build timings. No wire-time or exact
cross-node clock alignment is inferred.
"""
import argparse
import csv
import gzip
import json
import statistics
from collections import defaultdict
from pathlib import Path


WAIT_EVENTS = {200, 202, 207, 208, 105, 134, 136, 138}


def union(intervals):
    end = None
    total = 0
    for a, b in sorted(intervals):
        assert b >= a
        total += b - a if end is None or a > end else max(0, b - end)
        end = b if end is None else max(end, b)
    return total


def rank_max_median(samples):
    assert len(samples) == 8 and len({len(s) for s in samples}) == 1
    assert samples[0]
    return statistics.median(max(values) for values in zip(*samples)) / 1000


def analyze(gate):
    finished = json.loads((gate / 'FINISHED.json').read_text())
    assert finished['returncode'] == 0 and finished['qualification']['status'] == 'PASS'
    assert finished['spec']['qualification'] == 'ep_trace'
    captures = int(finished['spec']['environment']['CXI_TRACE_CAPTURES'])
    root = gate / 'direct/ep/device-traces'
    summaries = defaultdict(dict)
    for path in root.glob('*-summary.json'):
        row = json.loads(path.read_text())
        key = (row['case']['model'], row['case']['tokens_per_gpu'], row['operation'])
        assert row['rank'] not in summaries[key]
        summaries[key][row['rank']] = row
    assert summaries
    timing, roles, stages, role_stages = [], [], [], []
    for key, by_rank in sorted(summaries.items()):
        assert set(by_rank) == set(range(8))
        model, tokens, operation = key
        rows = [by_rank[rank] for rank in range(8)]
        assert all(len(row['captures']) == captures for row in rows)
        before = rank_max_median([r['disabled_before']['cuda_event_us'] for r in rows])
        after = rank_max_median([r['disabled_after']['cuda_event_us'] for r in rows])
        enabled = rank_max_median([[c['cuda_event_us'] for c in r['captures']] for r in rows])
        timing.append(dict(model=model, tokens=tokens, operation=operation,
                           disabled_before_ms=before, disabled_after_ms=after,
                           enabled_ms=enabled, enabled_vs_disabled_ratio=enabled / ((before + after) / 2)))
        observed = set()
        for path in sorted(root.glob('*-%s-rank*-iteration*.json.gz' % operation)):
            with gzip.open(path, 'rt') as file:
                row = json.load(file)
            if (row['case']['model'], row['case']['tokens_per_gpu'], row['operation']) != key:
                continue
            rank, iteration = row['rank'], row['iteration']
            assert (rank, iteration) not in observed
            observed.add((rank, iteration))
            assert row['correctness'] == 'PASS' and row['stats']['overflow'] == 0
            events = row['events']
            assert events and all(e['end_ns'] >= e['start_ns'] > 0 for e in events)
            names = by_rank[rank]['events']
            groups = defaultdict(list)
            for event in events:
                groups[event['event']].append(event)
            base = dict(model=model, tokens=tokens, operation=operation, rank=rank, iteration=iteration)
            for kind, group in sorted(groups.items()):
                stages.append(dict(**base, event=kind, name=names[str(kind)], count=len(group),
                    local_union_ms=union([(e['start_ns'], e['end_ns']) for e in group]) / 1e6,
                    sum_lane_ms=sum(e['end_ns'] - e['start_ns'] for e in group) / 1e6))
            for role in ([103, 104] if operation == 'dispatch_fresh' else [132, 133]):
                last = max(groups[role], key=lambda e: e['end_ns'])
                waits = defaultdict(list)
                local_stages = defaultdict(list)
                for event in events:
                    if (event['block'] == last['block'] and
                            event['thread'] // 32 == last['thread'] // 32):
                        a, b = max(last['start_ns'], event['start_ns']), min(last['end_ns'], event['end_ns'])
                        if b > a:
                            local_stages[event['event']].append((a, b))
                            if event['event'] in WAIT_EVENTS:
                                waits[event['event']].append((a, b))
                role_row = dict(**base, role=names[str(role)], block=last['block'], warp=last['thread'] // 32,
                    duration_ms=(last['end_ns'] - last['start_ns']) / 1e6,
                    wait_union_ms=union([interval for values in waits.values() for interval in values]) / 1e6)
                for kind in sorted(WAIT_EVENTS):
                    role_row['event_%d_union_ms' % kind] = union(waits[kind]) / 1e6
                roles.append(role_row)
                for kind, spans in sorted(local_stages.items()):
                    role_stages.append(dict(**base, role=names[str(role)], event=kind, name=names[str(kind)],
                        block=last['block'], warp=last['thread'] // 32, count=len(spans),
                        clipped_union_ms=union(spans) / 1e6, role_duration_ms=role_row['duration_ms']))
        assert observed == {(rank, iteration) for rank in range(8) for iteration in range(captures)}
    output = gate / 'trace-analysis'
    output.mkdir(exist_ok=True)
    for name, data in [('timing.csv', timing), ('critical-role-waits.csv', roles),
                       ('critical-role-stages.csv', role_stages), ('stage-observations.csv', stages)]:
        with (output / name).open('w') as file:
            writer = csv.DictWriter(file, fieldnames=list(data[0])); writer.writeheader(); writer.writerows(data)
    text = ['# Qualified local trace analysis', '',
        'Recording-disabled timings come from the instrumented build. Compare ordinary-build results separately. '
        'Enabled timings contain recording overhead; none of these intervals is an isolated wire timestamp.', '',
        '| Operation | Disabled before ms | Disabled after ms | Enabled ms | Enabled / disabled |',
        '|---|---:|---:|---:|---:|']
    for row in timing:
        text.append('| %s / %s / %s | %.4f | %.4f | %.4f | %.2f |' %
            (row['model'], row['tokens'], row['operation'], row['disabled_before_ms'],
             row['disabled_after_ms'], row['enabled_ms'], row['enabled_vs_disabled_ratio']))
    text += ['', 'The critical-role CSV selects the latest-finishing warp for each role on each rank. '
        'Each wait category is clipped to that same warp and role interval; the combined wait union removes '
        'overlap. Category unions still overlap each other and must not be added. '
        'The critical-role-stages CSV clips every instrumented stage to that same selected warp; it does '
        'not mix a sender’s wait with a different producer’s publication interval. The stage CSV includes '
        'parallel work across all warps; sum-lane durations are not wall-clock latency. Remaining role time '
        'is unclassified work, not proven pure computation or network transfer. Cross-rank clocks are not aligned.']
    (output / 'summary.md').write_text('\n'.join(text) + '\n')
    return output


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('gate', type=Path)
    print(analyze(parser.parse_args().gate))
