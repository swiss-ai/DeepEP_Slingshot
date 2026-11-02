# Public-GIN transport ladder

Qualified cases only; first 5 iterations excluded. This is a prepacked transport probe, not complete EP.

Snapshot: `source-ladder-v2`.

| Variant | Tokens/rank | Contexts | Coalesced | Signal interval (0=final only) | Rank-max median ms | Effective payload GB/s |
|---|---:|---:|---|---:|---:|---:|
| threshold | 4096 | 129 | True | 0 | 0.9094 | 19.457 |
| threshold | 4096 | 257 | True | 0 | 0.8944 | 19.785 |
| threshold | 4096 | 129 | False | 0 | 2.3170 | 7.637 |
| threshold | 4096 | 257 | False | 0 | 2.2576 | 7.838 |
| threshold | 4096 | 129 | False | 3 | 2.6598 | 6.653 |
| threshold | 4096 | 257 | False | 3 | 2.5863 | 6.842 |
| threshold | 4096 | 129 | False | 8 | 2.4572 | 7.201 |
| threshold | 4096 | 257 | False | 8 | 2.4278 | 7.288 |
| threshold | 4096 | 129 | False | 16 | 2.3857 | 7.417 |
| threshold | 4096 | 257 | False | 16 | 2.3208 | 7.624 |
| threshold | 16384 | 129 | True | 0 | 3.3295 | 21.258 |
| threshold | 16384 | 257 | True | 0 | 3.2940 | 21.487 |
| threshold | 16384 | 129 | False | 0 | 9.0675 | 7.806 |
| threshold | 16384 | 257 | False | 0 | 8.9577 | 7.901 |
| threshold | 16384 | 129 | False | 3 | 10.3129 | 6.863 |
| threshold | 16384 | 257 | False | 3 | 10.3399 | 6.845 |
| threshold | 16384 | 129 | False | 8 | 9.7418 | 7.265 |
| threshold | 16384 | 257 | False | 8 | 9.7107 | 7.289 |
| threshold | 16384 | 129 | False | 16 | 9.4141 | 7.518 |
| threshold | 16384 | 257 | False | 16 | 9.4175 | 7.516 |

CUDA events include the initial GPU readiness exchange and transfer-kernel boundaries. Preparation, host collective and payload verification are outside.
Per-channel submission includes periodic signal/completion work. Final completion includes the final readiness signal and flush. These are GPU-observed software intervals, not wire timestamps.
Local channel intervals overlap. The CSV selects each rank’s latest-finishing channel; do not sum these medians into the overall latency. No cross-node clock equality is assumed.
Cases present: 20/20. Missing or failed cases are not evidence of success.

## All-channel local boundaries

Medians over each rank/iteration, normalized to that rank’s first ready channel. Readiness spread is latest-ready minus first-ready. Submission span ends when every producer has returned from its payload-PUT/periodic-signal loop. AggregateRequests may still defer publication. The remaining tail includes final signal publication, flush/completion and peer readiness; it is not isolated network time. Intervals from different channels overlap; medians of adjacent spans need not add to a median total. These are local envelopes, not a clock-aligned cross-rank trace.

| Variant / tokens / coalesced / interval | Ready spread ms | All-submission span ms | Tail after last submission ms | Tail after last flush ms |
|---|---:|---:|---:|---:|
| threshold / 4096 / True / 0 | 0.0364 | 0.4587 | 0.4285 | 0.0009 |
| threshold / 4096 / True / 0 | 0.0112 | 0.0247 | 0.8386 | 0.0011 |
| threshold / 4096 / False / 0 | 0.0372 | 1.5598 | 0.6475 | 0.2142 |
| threshold / 4096 / False / 0 | 0.0112 | 0.2090 | 1.9656 | 0.2515 |
| threshold / 4096 / False / 3 | 0.0362 | 2.3027 | 0.1971 | 0.0524 |
| threshold / 4096 / False / 3 | 0.0111 | 2.1831 | 0.3256 | 0.2646 |
| threshold / 4096 / False / 8 | 0.0365 | 2.1834 | 0.0994 | 0.0294 |
| threshold / 4096 / False / 8 | 0.0112 | 2.0338 | 0.3239 | 0.2493 |
| threshold / 4096 / False / 16 | 0.0374 | 2.0256 | 0.3220 | 0.1920 |
| threshold / 4096 / False / 16 | 0.0112 | 1.9703 | 0.3491 | 0.2385 |
| threshold / 16384 / True / 0 | 0.0364 | 1.3739 | 1.9392 | 0.0154 |
| threshold / 16384 / True / 0 | 0.0112 | 0.0248 | 3.2366 | 0.0013 |
| threshold / 16384 / False / 0 | 0.0364 | 6.1015 | 2.4201 | 0.3408 |
| threshold / 16384 / False / 0 | 0.0112 | 0.7453 | 7.9066 | 1.1199 |
| threshold / 16384 / False / 3 | 0.0363 | 8.9088 | 1.0432 | 0.9593 |
| threshold / 16384 / False / 3 | 0.0111 | 8.8807 | 1.2892 | 1.2337 |
| threshold / 16384 / False / 8 | 0.0368 | 8.5173 | 0.9522 | 0.8894 |
| threshold / 16384 / False / 8 | 0.0111 | 8.3776 | 1.1889 | 1.1390 |
| threshold / 16384 / False / 16 | 0.0354 | 8.3139 | 0.7234 | 0.6361 |
| threshold / 16384 / False / 16 | 0.0112 | 8.2119 | 0.9319 | 0.8788 |
