"""Attribute observed lock waits to overlapping work on the same GPU/context.

Owner scopes below execute while holding the context lock in the pinned backend.
This is local overlap evidence, not NIC wire timing or recoverable-latency proof.
"""
import argparse
import csv
import gzip
import json
import statistics
from collections import defaultdict
from pathlib import Path
from analyze_trace import union

OWNER_EVENTS = {201, 202, 203, 204, 205, 207, 208, 209, 210, 211, 212, 213, 214}


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('gate', type=Path)
    gate = parser.parse_args().gate
    finished = json.loads((gate / 'FINISHED.json').read_text())
    assert finished['returncode'] == 0 and finished['qualification']['device_traces'] == 'PASS'
    rows, pairs = [], []
    for path in sorted((gate / 'direct/ep/device-traces').glob('*-iteration*.json.gz')):
        with gzip.open(path, 'rt') as file:
            capture = json.load(file)
        assert capture['correctness'] == 'PASS' and capture['stats']['overflow'] == 0
        events = capture['events']; owners = defaultdict(list)
        for event in events:
            if event['event'] in OWNER_EVENTS:
                owners[event['aux0']].append(event)
        for role in ([103, 104] if capture['operation'] == 'dispatch_fresh' else [132, 133]):
            selected = max((e for e in events if e['event'] == role), key=lambda e: e['end_ns'])
            waiter = (selected['block'], selected['thread'] // 32)
            waits = []
            category = defaultdict(list); by_pair = defaultdict(list)
            for wait in events:
                if wait['event'] != 200 or (wait['block'], wait['thread'] // 32) != waiter:
                    continue
                start, end = max(wait['start_ns'], selected['start_ns']), min(wait['end_ns'], selected['end_ns'])
                if end <= start:
                    continue
                waits.append((start, end))
                for owner in owners[wait['aux0']]:
                    owner_warp = (owner['block'], owner['thread'] // 32)
                    if owner_warp == waiter:
                        continue
                    a, b = max(start, owner['start_ns']), min(end, owner['end_ns'])
                    if b > a:
                        category[owner['event']].append((a, b))
                        by_pair[(wait['aux0'], owner_warp, owner['event'])].append((a, b))
            total = union(waits)
            covered = union([interval for spans in category.values() for interval in spans])
            assert 0 <= covered <= total
            base = dict(rank=capture['rank'], iteration=capture['iteration'], operation=capture['operation'],
                        role=role, waiter_block=waiter[0], waiter_warp=waiter[1])
            row = dict(**base, lock_wait_ms=total / 1e6, known_other_owner_ms=covered / 1e6,
                       unclassified_lock_wait_ms=(total - covered) / 1e6)
            for event in sorted(OWNER_EVENTS):
                row['owner_event_%d_ms' % event] = union(category[event]) / 1e6
            rows.append(row)
            for (context, owner, event), spans in by_pair.items():
                pairs.append(dict(**base, context_hex=hex(context), owner_block=owner[0], owner_warp=owner[1],
                                  owner_event=event, overlap_union_ms=union(spans) / 1e6))
    captures = int(finished['spec']['environment']['CXI_TRACE_CAPTURES'])
    assert len(rows) == 8 * captures * 2 * 2
    keys = {(r['rank'], r['iteration'], r['operation'], r['role']) for r in rows}
    assert len(keys) == len(rows)
    # Independent consistency with the existing clipped wait analysis.
    with (gate / 'trace-analysis/critical-role-waits.csv').open() as file:
        reference = list(csv.DictReader(file))
    names = {103: 'dispatch_sender', 104: 'dispatch_forwarder', 132: 'combine_NVLink_sender', 133: 'combine_forwarder'}
    for row in rows:
        ref = next(r for r in reference if int(r['rank']) == row['rank'] and int(r['iteration']) == row['iteration']
                   and r['operation'] == row['operation'] and r['role'] == names[row['role']])
        assert abs(float(ref['event_200_union_ms']) - row['lock_wait_ms']) < 1e-10
    output = gate / 'lock-owner-analysis'; output.mkdir(exist_ok=True)
    for name, values in [('critical-lock-owners.csv', rows), ('waiter-owner-pairs.csv', pairs)]:
        with (output / name).open('w') as file:
            # Exclusive channel contexts can legitimately have no overlapping
            # owner pairs. Preserve an empty, schema-bearing table in that case.
            fields = list(values[0]) if values else [
                'rank','iteration','operation','role','waiter_block','waiter_warp',
                'context_hex','owner_block','owner_warp','owner_event','overlap_union_ms']
            writer = csv.DictWriter(file, fieldnames=fields); writer.writeheader(); writer.writerows(values)
    text = ['# Same-GPU context ownership overlap', '',
            'For each latest-finishing role warp, intersect its lock-acquisition wait with instrumented '
            'lock-held work by a different warp on the same context pointer. Clocks are local to one GPU. '
            'Overlapping categories are not additive; unclassified time includes uninstrumented ownership '
            'and acquisition/publication gaps. This is not a claim that removing the lock removes the delay.', '',
            '| Operation / role | Lock wait ms | Overlap with known owner ms | Owner CT wait ms | Owner publication ms | Unclassified ms |',
            '|---|---:|---:|---:|---:|---:|']
    for operation, role in sorted({(r['operation'], r['role']) for r in rows}):
        selected = [r for r in rows if r['operation'] == operation and r['role'] == role]
        values = [statistics.median(r[k] for r in selected) for k in
                  ['lock_wait_ms', 'known_other_owner_ms', 'owner_event_207_ms', 'owner_event_209_ms', 'unclassified_lock_wait_ms']]
        text.append('| %s / %s | %.4f | %.4f | %.4f | %.4f | %.4f |' % ((operation, names[role]) + tuple(values)))
    (output / 'summary.md').write_text('\n'.join(text) + '\n')
    print(output)


if __name__ == '__main__':
    main()
