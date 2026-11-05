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
    lean_fence = bool(definitions.get('CXI_LEAN_FENCE', 0)); lean_cstate = bool(definitions.get('CXI_LEAN_CSTATE', 0))
    skip_combine_flush = bool(int(env.get('CXI_EP_SKIP_COMBINE_FLUSH', '0')))
    counts = {'combine_flush_scopes': 0, 'cstate_submissions': 0, 'fence_submissions': 0}
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
        required = {200, 201, 202, 204, 205, 206, 209, 213, 214}
        # CXI_LEAN_CSTATE re-emits CSTATE only when the (index_ext, write_lac) key changes.
        if not lean_cstate:
            required.add(212)
        counts['cstate_submissions'] += sum(e['event'] == 212 for e in events)
        counts['fence_submissions'] += sum(e['event'] == 211 for e in events)
        if row['operation'] == 'combine':
            counts['combine_flush_scopes'] += sum(e['event'] == 203 for e in events)
        if row['operation'] == 'dispatch_fresh':
            required |= {114, 115}
            if int(env.get('CXI_EP_PACK_ROWS', '0')):
                required.add(113)
        if row['operation'] == 'combine' and int(env.get('CXI_EP_PACK_COMBINE', '0')):
            required.add(116)
        required |= ({100, 103, 104, 105} if row['operation'] == 'dispatch_fresh'
                     else {130, 132, 133, 134, 138})
        # Native fencing removes the sender's GPU flush before dispatch signals.
        # Combine still has an explicit flush/counter completion path.
        # CXI_EP_SKIP_COMBINE_FLUSH removes the combine's only GPU flush before its end signal.
        if not native or (row['operation'] == 'combine' and not skip_combine_flush):
            required |= {203, 207}
        # CXI_LEAN_FENCE elides the CQ fence when nothing was posted since the last fence.
        if native and not lean_fence:
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
                  batched_delivery=batch, lean_fence=lean_fence, lean_cstate=lean_cstate,
                  skip_combine_flush=skip_combine_flush, **counts, validator_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    return result
