# Qualified local trace analysis

Recording-disabled timings come from the instrumented build. Compare ordinary-build results separately. Enabled timings contain recording overhead; none of these intervals is an isolated wire timestamp.

| Operation | Disabled before ms | Disabled after ms | Enabled ms | Enabled / disabled |
|---|---:|---:|---:|---:|
| v4flash / 4096 / combine | 3.4168 | 3.4006 | 3.4975 | 1.03 |
| v4flash / 4096 / dispatch_fresh | 1.1472 | 1.1374 | 1.3796 | 1.21 |

The critical-role CSV selects the latest-finishing warp for each role on each rank. Each wait category is clipped to that same warp and role interval; the combined wait union removes overlap. Category unions still overlap each other and must not be added. The critical-role-stages CSV clips every instrumented stage to that same selected warp; it does not mix a sender’s wait with a different producer’s publication interval. The stage CSV includes parallel work across all warps; sum-lane durations are not wall-clock latency. Remaining role time is unclassified work, not proven pure computation or network transfer. Cross-rank clocks are not aligned.
