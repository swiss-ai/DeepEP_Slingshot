# Public-GIN transport ladder

Qualified cases only; first 5 iterations excluded. This is a prepacked transport probe, not complete EP.

Snapshot: `source-delivery-ladder-v1`.

| Variant | Tokens/rank | Contexts | Coalesced | Signal interval (0=final only) | Rank-max median ms | Effective payload GB/s |
|---|---:|---:|---|---:|---:|---:|
| delivery-control | 4096 | 129 | True | 0 | 0.9243 | 19.144 |
| delivery-batched | 4096 | 129 | True | 0 | 0.9313 | 19.000 |
| delivery-control | 4096 | 129 | False | 0 | 2.4042 | 7.360 |
| delivery-batched | 4096 | 129 | False | 0 | 2.2658 | 7.809 |
| delivery-control | 4096 | 129 | False | 3 | 2.7713 | 6.385 |
| delivery-batched | 4096 | 129 | False | 3 | 2.8262 | 6.261 |
| delivery-control | 16384 | 129 | True | 0 | 3.3221 | 21.305 |
| delivery-batched | 16384 | 129 | True | 0 | 3.3315 | 21.246 |
| delivery-control | 16384 | 129 | False | 0 | 9.1130 | 7.767 |
| delivery-batched | 16384 | 129 | False | 0 | 8.7980 | 8.045 |
| delivery-control | 16384 | 129 | False | 3 | 10.4962 | 6.743 |
| delivery-batched | 16384 | 129 | False | 3 | 10.6722 | 6.632 |

CUDA events include the initial GPU readiness exchange and transfer-kernel boundaries. Preparation, host collective and payload verification are outside.
Per-channel submission includes periodic signal/completion work. Final completion includes the final readiness signal and flush. These are GPU-observed software intervals, not wire timestamps.
Local channel intervals overlap. The CSV selects each rank’s latest-finishing channel; do not sum these medians into the overall latency. No cross-node clock equality is assumed.
Cases present: 12/12. Missing or failed cases are not evidence of success.
