# Public-GIN transport ladder

Qualified cases only; first 5 iterations excluded. This is a prepacked transport probe, not complete EP.

Snapshot: `source-credit-cache-v2`.

| Variant | Tokens/rank | Contexts | Coalesced | Signal interval (0=final only) | Rank-max median ms | Effective payload GB/s |
|---|---:|---:|---|---:|---:|---:|
| credit-control | 4096 | 129 | True | 0 | 0.9320 | 18.985 |
| credit-cached | 4096 | 129 | True | 0 | 0.9296 | 19.035 |
| credit-control | 4096 | 129 | False | 0 | 2.2436 | 7.887 |
| credit-cached | 4096 | 129 | False | 0 | 2.2329 | 7.925 |
| credit-control | 4096 | 129 | False | 3 | 2.8644 | 6.177 |
| credit-cached | 4096 | 129 | False | 3 | 2.8253 | 6.263 |
| credit-control | 16384 | 129 | True | 0 | 3.3429 | 21.173 |
| credit-cached | 16384 | 129 | True | 0 | 3.3367 | 21.212 |
| credit-control | 16384 | 129 | False | 0 | 8.8542 | 7.994 |
| credit-cached | 16384 | 129 | False | 0 | 8.7396 | 8.099 |
| credit-control | 16384 | 129 | False | 3 | 10.6995 | 6.615 |
| credit-cached | 16384 | 129 | False | 3 | 10.6544 | 6.643 |

CUDA events include the initial GPU readiness exchange and transfer-kernel boundaries. Preparation, host collective and payload verification are outside.
Per-channel submission includes periodic signal/completion work. Final completion includes the final readiness signal and flush. These are GPU-observed software intervals, not wire timestamps.
Local channel intervals overlap. The CSV selects each rank’s latest-finishing channel; do not sum these medians into the overall latency. No cross-node clock equality is assumed.
Cases present: 12/12. Missing or failed cases are not evidence of success.

## All-channel local boundaries

Medians over each rank/iteration, normalized to that rank’s first ready channel. Readiness spread is latest-ready minus first-ready. Submission span ends when every producer has returned from its payload-PUT/periodic-signal loop. AggregateRequests may still defer publication. The remaining tail includes final signal publication, flush/completion and peer readiness; it is not isolated network time. Intervals from different channels overlap; medians of adjacent spans need not add to a median total. These are local envelopes, not a clock-aligned cross-rank trace.

| Variant / tokens / coalesced / interval | Ready spread ms | All-submission span ms | Tail after last submission ms | Tail after last flush ms |
|---|---:|---:|---:|---:|
| credit-control / 4096 / True / 0 | 0.0425 | 0.1933 | 0.7044 | 0.0007 |
| credit-cached / 4096 / True / 0 | 0.0422 | 0.3349 | 0.5594 | 0.0007 |
| credit-control / 4096 / False / 0 | 0.0418 | 1.8274 | 0.3331 | 0.0007 |
| credit-cached / 4096 / False / 0 | 0.0408 | 1.8372 | 0.3086 | 0.0007 |
| credit-control / 4096 / False / 3 | 0.0424 | 2.5955 | 0.1152 | 0.0118 |
| credit-cached / 4096 / False / 3 | 0.0410 | 2.5310 | 0.1647 | 0.0258 |
| credit-control / 16384 / True / 0 | 0.0429 | 0.4170 | 2.8634 | 0.0074 |
| credit-cached / 16384 / True / 0 | 0.0422 | 0.5004 | 2.8022 | 0.0451 |
| credit-control / 16384 / False / 0 | 0.0422 | 7.3279 | 0.9094 | 0.0007 |
| credit-cached / 16384 / False / 0 | 0.0406 | 7.8332 | 0.6664 | 0.0008 |
| credit-control / 16384 / False / 3 | 0.0428 | 10.0885 | 0.1376 | 0.0452 |
| credit-cached / 16384 / False / 3 | 0.0407 | 10.0050 | 0.1794 | 0.0608 |
