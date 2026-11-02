# Qualified local trace analysis

Recording-disabled timings come from the instrumented build. Compare ordinary-build results separately. Enabled timings contain recording overhead; none of these intervals is an isolated wire timestamp.

| Operation | Disabled before ms | Disabled after ms | Enabled ms | Enabled / disabled |
|---|---:|---:|---:|---:|
| v4flash / 4096 / combine | 4.4586 | 4.4621 | 4.4715 | 1.00 |
| v4flash / 4096 / dispatch_fresh | 3.4819 | 3.4856 | 3.5944 | 1.03 |

The critical-role CSV selects the latest-finishing warp for each role on each rank. Each wait category is clipped to that same warp and role interval; the combined wait union removes overlap. Category unions still overlap each other and must not be added. The stage CSV includes parallel work across all warps; sum-lane durations are not wall-clock latency. Remaining role time is unclassified work, not proven pure computation or network transfer. Cross-rank clocks are not aligned.
