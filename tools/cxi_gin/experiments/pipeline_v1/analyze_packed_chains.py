"""Match EP8 packed batches to receiver availability with bounded clock mapping.

This is a submission/observation chain, not per-packet NIC completion timing.
Several batches may share one receiver observation. Absolute clock bounds assume
offset remains within the envelope of the pre/post calibration observations.
"""
import argparse
import csv
import gzip
import json
from collections import defaultdict
from pathlib import Path


def offset_bounds(pre, post):
    values = []
    for calibration in [pre, post]:
        host, gpu = calibration['host'], calibration['gpu']
        values.append((gpu['host_lower_ns']-gpu['gpu_ns']-host['offset_upper_ns'],
                       gpu['host_upper_ns']-gpu['gpu_ns']-host['offset_lower_ns']))
    return min(x[0] for x in values), max(x[1] for x in values)


def find_observation(events, channel, source_node, end_tail):
    matches = [event for event in events if event['event'] == 115
        and event['aux0'] >> 32 == channel and event['aux0'] & 0xffffffff == source_node
        and event['aux1'] >> 32 < end_tail <= event['aux1'] & 0xffffffff]
    return min(matches, key=lambda event: event['start_ns']) if matches else None


def validate_batches(rows, expected):
    channels = defaultdict(list)
    for row in rows:
        channels[row['channel']].append((row['old_tail'], row['end_tail']))
    total = 0
    for ranges in channels.values():
        cursor = 0
        for start, end in sorted(ranges):
            assert start == cursor and end > start, ('gap/overlap in batch tails', ranges)
            total += end-start
            cursor = end
    assert total == expected, ('trace batch rows differ from routing reference', total, expected)


def analyze(gate):
    finish = json.loads((gate/'FINISHED.json').read_text())
    assert finish['returncode'] == 0 and finish['qualification']['device_traces'] == 'PASS'
    env = finish['spec']['environment']
    assert env['CXI_EP_PACK_ROWS'] == '1'
    root = gate/'direct/ep/device-traces'
    summaries, posts, captures = {}, {}, {}
    for path in root.glob('*-summary.json'):
        value = json.loads(path.read_text())
        if value['operation'] == 'dispatch_fresh':
            assert value['rank'] not in summaries
            summaries[value['rank']] = value
    for path in root.glob('*-clock-post-rank*.json'):
        rank = int(path.stem.rsplit('rank', 1)[1])
        assert rank not in posts
        posts[rank] = json.loads(path.read_text())
    assert set(summaries) == set(posts) == set(range(8))
    bounds = {rank: offset_bounds(summaries[rank]['clock_pre'], posts[rank]) for rank in range(8)}
    for path in root.glob('*-dispatch_fresh-rank*-iteration*.json.gz'):
        with gzip.open(path, 'rt') as file:
            value = json.load(file)
        assert value['correctness'] == 'PASS' and value['stats']['overflow'] == 0
        key = (value['rank'], value['iteration'])
        assert key not in captures
        captures[key] = value['events']
    assert set(captures) == {(rank, i) for rank in range(8) for i in range(int(env['CXI_TRACE_CAPTURES']))}
    rows = []
    for (rank, iteration), events in sorted(captures.items()):
        for event in events:
            if event['event'] != 113:
                continue
            channel, destination_node = event['aux0'] >> 32, event['aux0'] & 0xffffffff
            old_tail, count = event['aux1'] >> 32, event['aux1'] & 0xffffffff
            assert count > 0 and destination_node == 1-rank//4
            receiver = 4*destination_node+rank%4
            end_tail = old_tail+count
            notification = [x for x in events if x['event'] == 114
                and x['aux0'] & 0xffff == channel
                and (x['aux0'] >> 16) & 0xffff == destination_node
                and x['aux1'] >> 32 == old_tail and x['aux1'] & 0xffffffff == end_tail]
            assert len(notification) == 1, (rank, iteration, channel, old_tail, end_tail)
            notification = notification[0]
            observed = find_observation(captures[receiver, iteration], channel, rank//4, end_tail)
            assert observed is not None, (rank, receiver, channel, old_tail, end_tail)
            lo = observed['start_ns']+bounds[receiver][0]
            hi = observed['end_ns']+bounds[receiver][1]
            rows.append(dict(rank=rank, receiver=receiver, iteration=iteration,
                channel=channel, old_tail=old_tail, end_tail=end_tail, rows=count,
                payload_submission_ns=event['end_ns']-event['start_ns'],
                notification_submission_ns=notification['end_ns']-notification['start_ns'],
                put_start_to_observation_lower_ns=lo-event['start_ns']-bounds[rank][1],
                put_start_to_observation_upper_ns=hi-event['start_ns']-bounds[rank][0],
                signal_return_to_observation_lower_ns=lo-notification['end_ns']-bounds[rank][1],
                signal_return_to_observation_upper_ns=hi-notification['end_ns']-bounds[rank][0],
                receiver_consumed=observed['aux1'] >> 32,
                receiver_available=observed['aux1'] & 0xffffffff,
                receiver_observation_ns=observed['start_ns']))
    assert rows
    for rank in range(8):
        references = [json.loads(line) for line in (gate/'direct/ep'/('correctness-rank%d.jsonl'%rank)).read_text().splitlines()]
        assert len(references) == 1 and references[0]['status'] == 'PASS'
        expected = references[0]['unique_remote_node_rows']
        for iteration in range(int(env['CXI_TRACE_CAPTURES'])):
            validate_batches([row for row in rows if row['rank'] == rank and row['iteration'] == iteration], expected)
    output = gate/'packed-chain-analysis'
    output.mkdir(exist_ok=True)
    with (output/'batches.csv').open('w') as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0]))
        writer.writeheader(); writer.writerows(rows)
    (output/'clock-bounds.json').write_text(json.dumps(bounds, indent=2)+'\n')
    (output/'README.md').write_text(
        'Packed batch submission → notification → receiver availability, matched by source rank, '
        'channel and cumulative tail. Receiver observations can cover several batches; they are '
        'not packet arrivals. Delay bounds include producer, transport and receiver scheduling. '
        'Negative signal-return gaps are possible because the receiver can observe before the '
        'sender returns. Clock mapping assumes offsets remain within the pre/post calibration '
        'envelope. These are perturbed trace measurements, not ordinary latency or wire time.\n')
    return output


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('gate', type=Path)
    print(analyze(parser.parse_args().gate))
