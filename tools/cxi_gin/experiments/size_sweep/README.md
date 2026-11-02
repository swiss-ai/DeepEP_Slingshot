# EP8 warmed FP8 dispatch size sweep

V4 Flash geometry (hidden 4096, 256 experts, top-k 6), DeepEP bd1e1669, private
CXI direct GIN threshold-completion transport already qualified in job 3801971.
Two GH200 nodes, four ranks/node; all eight ranks participate in one group.

- Tokens/rank: 2048, 4096, 6144, 8192, 10240, 12288, 14336, 16384.
- Three separate process-group runs: ascending, descending, then permuted size order.
- Same routing seed 1 and synthetic `mixed` routing as the previous 4K experiment.
  This is controlled two-destination-rank routing, not a captured production router.
- Fixed 64 SMs, 129 contexts, FP8 dispatch with FP32 scale factors, BF16 combine.
- Every size/repeat checks payload, scales, routing, weights and reduction correctness.
- 20 warmup calls and 100 measured calls per operation. Main statistic: median of
  per-iteration maximum CUDA-event latency over all eight ranks, with p95 and repeat
  range. Fresh dispatch is the primary measurement; cached dispatch/combine/cycle
  are controls. Buffer setup, JIT compilation and input quantization are excluded.
- No device tracing or CUDA profiler. NIC telemetry windows cover every size and
  operation, with one shared iteration count chosen for >=2.5 seconds based on the
  preceding latency measurements, and at least 600 iterations.

The benchmark records actual scale dimensions and aligned TokenLayout bytes.
For this V4 FP8 input: 4096 hidden bytes + 128 scale bytes + 96 metadata bytes =
4320 bytes per unique remotely dispatched token. The controlled routing makes every
source token reach the remote node once; 4K therefore serializes 17.69472 MB per rail,
or 0.7077888 ms at 25 GB/s. These are data-command bytes, not wire bytes including
protocol traffic. TX and RX are not added together for the one-direction bound.

Postprocessing writes CSV, PDF, PNG and a Markdown report. It fits warmed full-call
latency T = alpha + beta * per-rail payload MB and reports residuals/R² and per-repeat
fits. Alpha is an extrapolated per-call intercept, not cold initialization; beta
includes token packing, signaling, queueing and NIC time, so 1/beta is incremental
end-to-end payload throughput, not intrinsic NIC bandwidth. Negative or unstable
intercepts and nonlinear residuals should invalidate a simple fixed-overhead story.

One two-hour normal allocation runs the public GIN gate and three full sweeps.
It retains the allocation on failure for runtime debugging, and releases after all
scheduled sweeps finish. The read-only live collector runs local postprocessing only
when all three sweeps have passed; incomplete runs are labeled, not fitted as complete.
