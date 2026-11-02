"""Trace requirements follow the compiled native-fence/delivery configuration."""
import gzip
import hashlib
import json
from pathlib import Path


def qualify_trace(destination, spec, qualify_ep):
    destination = Path(destination)
    env = spec['environment']; source = Path(spec['snapshot'])
    definitions = json.loads((source / 'variants.json').read_text())[env['CXI_VARIANT']]
    native = bool(definitions.get('CXI_HW_SIGNAL_FENCE', 0))
    batch = bool(definitions.get('CXI_BATCH_DELIVERY', 0))
    result = qualify_ep(destination, dict(spec, qualification='ep'))
    root = destination / 'direct/ep/device-traces'
    captures = int(env['CXI_TRACE_CAPTURES']); observed = set()
    for path in root.glob('*-iteration*.json.gz'):
        with gzip.open(str(path), 'rt') as file:
            row = json.load(file)
        key = (row['rank'], row['operation'], row['iteration'])
        assert key not in observed; observed.add(key)
        assert row['correctness'] == 'PASS' and row['stats']['overflow'] == 0
        events = row['events']; assert events and len(events) == row['stats']['records']
        assert all(e['end_ns'] >= e['start_ns'] > 0 for e in events)
        kinds = {e['event'] for e in events}
        required = {200, 201, 202, 204, 205, 206, 209}
        required |= ({100, 103, 104, 105} if row['operation'] == 'dispatch_fresh'
                     else {130, 132, 133, 134, 138})
        # Native fencing removes the sender's GPU flush before dispatch signals.
        # Combine still has an explicit flush/counter completion path.
        if not native or row['operation'] == 'combine':
            required |= {203, 207}
        if native:
            required.add(211)
        if batch:
            required.add(210)
        assert required <= kinds, ('missing configuration-required events', sorted(required - kinds), key)
    assert observed == {(rank, operation, iteration) for rank in range(8)
                        for operation in ['dispatch_fresh', 'combine'] for iteration in range(captures)}
    summaries = list(root.glob('*-summary.json')); assert len(summaries) == 16
    seen = set()
    for path in summaries:
        row = json.loads(path.read_text()); seen.add((row['rank'], row['operation']))
        assert len(row['captures']) == captures
        assert all(c['overflow'] == 0 for c in row['captures'])
        for phase in ['disabled_before', 'disabled_after']:
            assert len(row[phase]['cuda_event_us']) == int(env['CXI_EP_ITERS'])
    assert seen == {(rank, op) for rank in range(8) for op in ['dispatch_fresh', 'combine']}
    result.update(device_traces='PASS', trace_validation='configuration-aware', native_fence=native,
                  batched_delivery=batch, validator_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    return result
