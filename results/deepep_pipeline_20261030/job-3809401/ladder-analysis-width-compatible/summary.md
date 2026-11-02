# Public-GIN transport ladder

Qualified cases only; first 5 iterations excluded. This is a prepacked transport probe, not complete EP.

Snapshot: `source-ladder-v2`.

| Variant | Tokens/rank | Row bytes | Contexts | Coalesced | Batch limit / signal / publication interval | Rank-max median ms | Effective payload GB/s |
|---|---:|---:|---:|---|---|---:|---:|
| threshold | 4096 | 4320 | 129 | True | 0 / 0 / 0 | 0.9094 | 19.457 |
| threshold | 4096 | 4320 | 257 | True | 0 / 0 / 0 | 0.8944 | 19.785 |
| threshold | 4096 | 4320 | 129 | False | 0 / 0 / 0 | 2.3170 | 7.637 |
| threshold | 4096 | 4320 | 257 | False | 0 / 0 / 0 | 2.2576 | 7.838 |
| threshold | 4096 | 4320 | 129 | False | 0 / 3 / 0 | 2.6598 | 6.653 |
| threshold | 4096 | 4320 | 257 | False | 0 / 3 / 0 | 2.5863 | 6.842 |
| threshold | 4096 | 4320 | 129 | False | 0 / 8 / 0 | 2.4572 | 7.201 |
| threshold | 4096 | 4320 | 257 | False | 0 / 8 / 0 | 2.4278 | 7.288 |
| threshold | 4096 | 4320 | 129 | False | 0 / 16 / 0 | 2.3857 | 7.417 |
| threshold | 4096 | 4320 | 257 | False | 0 / 16 / 0 | 2.3208 | 7.624 |
| threshold | 16384 | 4320 | 129 | True | 0 / 0 / 0 | 3.3295 | 21.258 |
| threshold | 16384 | 4320 | 257 | True | 0 / 0 / 0 | 3.2940 | 21.487 |
| threshold | 16384 | 4320 | 129 | False | 0 / 0 / 0 | 9.0675 | 7.806 |
| threshold | 16384 | 4320 | 257 | False | 0 / 0 / 0 | 8.9577 | 7.901 |
| threshold | 16384 | 4320 | 129 | False | 0 / 3 / 0 | 10.3129 | 6.863 |
| threshold | 16384 | 4320 | 257 | False | 0 / 3 / 0 | 10.3399 | 6.845 |
| threshold | 16384 | 4320 | 129 | False | 0 / 8 / 0 | 9.7418 | 7.265 |
| threshold | 16384 | 4320 | 257 | False | 0 / 8 / 0 | 9.7107 | 7.289 |
| threshold | 16384 | 4320 | 129 | False | 0 / 16 / 0 | 9.4141 | 7.518 |
| threshold | 16384 | 4320 | 257 | False | 0 / 16 / 0 | 9.4175 | 7.516 |

CUDA events include the initial GPU readiness exchange and transfer-kernel boundaries. Preparation, host collective and payload verification are outside.
Batch limit0 means all channel rows when coalescing is enabled, otherwise one row per PUT. Signal interval0 means only the final strong signal; publication interval0 leaves payload PUTs aggregated. Nonzero intervals split PUTs at every requested boundary.
Per-channel submission includes periodic signal/completion work. Final completion includes the final readiness signal and flush. These are GPU-observed software intervals, not wire timestamps.
Local channel intervals overlap. The CSV selects each rank’s latest-finishing channel; do not sum these medians into the overall latency. No cross-node clock equality is assumed.
Cases present: 20/20. Missing or failed cases are not evidence of success.

## All-channel local boundaries

Medians over each rank/iteration, normalized to that rank’s first ready channel. Readiness spread is latest-ready minus first-ready. Submission span ends when every producer has returned from its payload-PUT/periodic-signal loop. AggregateRequests may still defer publication. The remaining tail includes final signal publication, flush/completion and peer readiness; it is not isolated network time. Intervals from different channels overlap; medians of adjacent spans need not add to a median total. These are local envelopes, not a clock-aligned cross-rank trace.

| Step | Ready spread ms | All-submission span ms | Tail after last submission ms | Tail after last flush ms |
|---|---:|---:|---:|---:|
| 21-ladder-coalesced-4096 / q129 | 0.0364 | 0.4587 | 0.4285 | 0.0009 |
| 21-ladder-coalesced-4096 / q257 | 0.0112 | 0.0247 | 0.8386 | 0.0011 |
| 22-ladder-rows-final-4096 / q129 | 0.0372 | 1.5598 | 0.6475 | 0.2142 |
| 22-ladder-rows-final-4096 / q257 | 0.0112 | 0.2090 | 1.9656 | 0.2515 |
| 23-ladder-signals3-4096 / q129 | 0.0362 | 2.3027 | 0.1971 | 0.0524 |
| 23-ladder-signals3-4096 / q257 | 0.0111 | 2.1831 | 0.3256 | 0.2646 |
| 24-ladder-signals8-4096 / q129 | 0.0365 | 2.1834 | 0.0994 | 0.0294 |
| 24-ladder-signals8-4096 / q257 | 0.0112 | 2.0338 | 0.3239 | 0.2493 |
| 25-ladder-signals16-4096 / q129 | 0.0374 | 2.0256 | 0.3220 | 0.1920 |
| 25-ladder-signals16-4096 / q257 | 0.0112 | 1.9703 | 0.3491 | 0.2385 |
| 26-ladder-coalesced-16384 / q129 | 0.0364 | 1.3739 | 1.9392 | 0.0154 |
| 26-ladder-coalesced-16384 / q257 | 0.0112 | 0.0248 | 3.2366 | 0.0013 |
| 27-ladder-rows-final-16384 / q129 | 0.0364 | 6.1015 | 2.4201 | 0.3408 |
| 27-ladder-rows-final-16384 / q257 | 0.0112 | 0.7453 | 7.9066 | 1.1199 |
| 28-ladder-signals3-16384 / q129 | 0.0363 | 8.9088 | 1.0432 | 0.9593 |
| 28-ladder-signals3-16384 / q257 | 0.0111 | 8.8807 | 1.2892 | 1.2337 |
| 29-ladder-signals8-16384 / q129 | 0.0368 | 8.5173 | 0.9522 | 0.8894 |
| 29-ladder-signals8-16384 / q257 | 0.0111 | 8.3776 | 1.1889 | 1.1390 |
| 30-ladder-signals16-16384 / q129 | 0.0354 | 8.3139 | 0.7234 | 0.6361 |
| 30-ladder-signals16-16384 / q257 | 0.0112 | 8.2119 | 0.9319 | 0.8788 |
