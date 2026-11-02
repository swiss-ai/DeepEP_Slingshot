"""Static remote token-path request counts, not measured NIC traffic.

The all-remote fixture means every source token has at least one remote expert;
deduplication still sends one row per token. This excludes context0 metadata,
local NVLink operations, explicit flush/CT commands, barriers and error handling.
Shared contexts can merge delivery epochs, so marker counts are only upper
bounds; PUT and remote progress-signal counts follow the per-channel loop.
"""
import argparse
import json
from pathlib import Path


def budget(tokens, interval, channels=256):
    counts = [len(range(c, tokens, channels)) for c in range(channels)]
    puts = sum((n + interval - 1) // interval for n in counts)
    # update_scaleout_tail(true) always emits a finish signal, including when
    # the preceding regular notification already published the same token tail.
    signals = sum(n // interval + 1 for n in counts)
    return dict(tokens_per_gpu=tokens, channels=channels, interval=interval,
                original_row_puts=tokens, packed_row_puts=puts,
                remote_progress_signals=signals,
                original_delivery_markers_upper_bound=min(tokens, signals),
                packed_delivery_markers_upper_bound=min(puts, signals),
                cq_fence_cstate_atomic_commands=3 * signals,
                original_token_commands_upper_bound=tokens + min(tokens, signals) + 3 * signals,
                packed_token_commands_upper_bound=puts + min(puts, signals) + 3 * signals,
                payload_MB=tokens * 4320 / 1e6,
                payload_serialization_ms_at_25GBps=tokens * 4320 / 25e6)


def main():
    p = argparse.ArgumentParser(); p.add_argument('output', type=Path); args = p.parse_args()
    data = dict(scope=__doc__, cases=[budget(n, k) for n in [4096, 16384] for k in [3, 8, 16, 32]])
    args.output.write_text(json.dumps(data, indent=2) + '\n')
    for r in data['cases']:
        print('%5d tokens interval%2d: PUTs %5d -> %5d; signals %4d; token commands <= %5d -> %5d' % (
            r['tokens_per_gpu'], r['interval'], r['original_row_puts'], r['packed_row_puts'],
            r['remote_progress_signals'], r['original_token_commands_upper_bound'],
            r['packed_token_commands_upper_bound']))


if __name__ == '__main__':
    main()
