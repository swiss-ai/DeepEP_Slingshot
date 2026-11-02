# Matched delivery completion experiment

Untraced, 3 counterbalanced repeats on one node pair; 20 warmups and 100 timed calls per repeat. Each call uses the maximum duration across eight ranks. All correctness gates passed.

| Tokens/rank | Operation | Per-PUT DC control ms | Batched DC ms | Reduction |
|---:|---|---:|---:|---:|
| 4096 | dispatch_fresh | 2.8420 | 2.8458 | -0.14% |
| 4096 | dispatch_cached | 2.8303 | 2.8363 | -0.21% |
| 4096 | combine | 3.8562 | 3.3436 | 13.29% |
| 16384 | dispatch_fresh | 10.7061 | 10.6006 | 0.99% |
| 16384 | dispatch_cached | 10.7026 | 10.5911 | 1.04% |
| 16384 | combine | 14.7360 | 12.8534 | 12.78% |

Status: COMPLETE

Both variants use batch-8 TX publication and the same private ABI. The candidate changes payload completion to CT_SEND plus a same-endpoint DC marker; it still blocks before each strong signal. These are full communication timings, not isolated NIC wire times.

Fresh dispatch remains near 2.85 ms at 4K. The previous prepacked coalesced probe reached about 0.90 ms for comparable rail payload, so a fixed 7 GB/s NIC limit does not explain this result. The native-CQ-fence candidate tests moving notification ordering from GPU polling to the NIC queue.
