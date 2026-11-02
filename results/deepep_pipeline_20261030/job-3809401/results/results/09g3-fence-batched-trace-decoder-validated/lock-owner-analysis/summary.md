# Same-GPU context ownership overlap

For each latest-finishing role warp, intersect its lock-acquisition wait with instrumented lock-held work by a different warp on the same context pointer. Clocks are local to one GPU. Overlapping categories are not additive; unclassified time includes uninstrumented ownership and acquisition/publication gaps. This is not a claim that removing the lock removes the delay.

| Operation / role | Lock wait ms | Overlap with known owner ms | Owner CT wait ms | Owner publication ms | Unclassified ms |
|---|---:|---:|---:|---:|---:|
| combine / combine_NVLink_sender | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 |
| combine / combine_forwarder | 2.2788 | 2.2411 | 2.0821 | 0.0308 | 0.0383 |
| dispatch_fresh / dispatch_sender | 0.4699 | 0.4260 | 0.0000 | 0.0647 | 0.0440 |
| dispatch_fresh / dispatch_forwarder | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 |
