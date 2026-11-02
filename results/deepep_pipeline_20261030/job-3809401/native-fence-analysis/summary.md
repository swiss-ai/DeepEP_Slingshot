# Matched native CQ-fence results

Three counterbalanced ordinary repeats per variant, on the same two GH200 nodes. Each value is the median of three per-run medians of rank-max CUDA-event latency. Ranges describe repeat variation, not confidence intervals. All declared correctness gates passed. No tracing is enabled; this is not cross-allocation replication.

All variants use 129 contexts, 64 SMs, progress interval 3, and bounded TX publication of 8 commands. Control waits on GPU CT observation before signals; fence-dc uses a native NIC CQ fence with per-PUT delivery completion; fence-batched additionally batches delivery completion.

| Tokens/GPU | Operation | Variant | Median ms | Repeat range ms | Reduction vs control |
|---:|---|---|---:|---|---:|
| 4096 | dispatch_fresh | fence-control | 2.8413 | 2.8398–2.8464 | 0.00% |
| 4096 | dispatch_fresh | fence-dc | 2.6804 | 2.6726–2.6849 | 5.66% |
| 4096 | dispatch_fresh | fence-batched | 2.8181 | 2.8156–2.8182 | 0.82% |
| 4096 | dispatch_cached | fence-control | 2.8357 | 2.8346–2.8373 | 0.00% |
| 4096 | dispatch_cached | fence-dc | 2.6811 | 2.6808–2.6815 | 5.45% |
| 4096 | dispatch_cached | fence-batched | 2.8147 | 2.8074–2.8216 | 0.74% |
| 4096 | combine | fence-control | 3.8485 | 3.8345–3.8613 | 0.00% |
| 4096 | combine | fence-dc | 3.8456 | 3.8096–3.8464 | 0.08% |
| 4096 | combine | fence-batched | 3.3324 | 3.3316–3.3354 | 13.41% |
| 16384 | dispatch_fresh | fence-control | 10.7233 | 10.7222–10.7235 | 0.00% |
| 16384 | dispatch_fresh | fence-dc | 10.4547 | 10.4538–10.4829 | 2.51% |
| 16384 | dispatch_fresh | fence-batched | 10.5982 | 10.5896–10.6463 | 1.17% |
| 16384 | dispatch_cached | fence-control | 10.7168 | 10.7094–10.7177 | 0.00% |
| 16384 | dispatch_cached | fence-dc | 10.4864 | 10.4732–10.5672 | 2.15% |
| 16384 | dispatch_cached | fence-batched | 10.6139 | 10.6039–10.6255 | 0.96% |
| 16384 | combine | fence-control | 14.7341 | 14.7044–14.8658 | 0.00% |
| 16384 | combine | fence-dc | 14.8342 | 14.8279–14.9590 | -0.68% |
| 16384 | combine | fence-batched | 12.8814 | 12.8538–12.9656 | 12.57% |

The 4K V4 FP8 rail-payload serialization bound is 0.7077888 ms (4096 × 4320 bytes / 25 GB/s). It excludes packing, notifications, forwarding and synchronization. None of these complete-EP measurements reaches that bound.

Independent repeated-operation NIC telemetry is in `../nic-analysis/`; its measurement window and byte accounting differ from the CUDA-event samples above. Source records and compiler evidence are under each listed gate in `../results/results/`.
