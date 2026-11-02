# EP8 per-rank dispatch trace

Initial target: the recorded V4 Flash geometry, fresh FP8 dispatch, 4,096 tokens
per GPU, all eight ranks on two GH200 nodes. DeepEP stays pinned at bd1e1669;
private CXI GIN type 6 and existing ordering/completion semantics are retained.
This first campaign instruments dispatch, not combine. Extend coverage only
after the instrumentation passes correctness and overhead checks.

## Acceptance gates

1. Reconstruct source in an isolated snapshot; retain hashes and unchanged
   baseline. Compile actual instrumented JIT specializations before submission.
2. In the allocation, run the original uninstrumented benchmark control.
3. Build the isolated native extension with in-memory CPU boundary timestamps.
4. Validate source IDs, experts, FP8 payload, scales, weights and expert counts
   against the independent reference on all eight ranks.
5. Measure tracing-disabled latency before and after three full trace captures.
   Report enabled/disabled overhead, not just traced latency. Compare the
   disabled patched build with the original control as a separate check.
6. Require zero trace overflow and complete event/rank coverage; check the
   number of remote token puts against the recorded routing.
7. Export per-rank host intervals, GPU inclusive spans, Chrome/Perfetto trace,
   and NIC telemetry timestamp intervals. Missing/zero-resolution NIC telemetry
   must not be called proof of NIC utilization.

## Instrumentation

- CPU CLOCK_MONOTONIC: stream prologue, main launch, receive-count polling,
  output allocation, copy launch, stream epilogue and return boundaries.
- GPU globaltimer: per-warp kernel/role lifetimes, initial/final barriers,
  token packing/staging, arrival-tail waits, token forwarding, NVLink issue,
  RDMA token puts, tail signaling, epilogue dependency wait.
- CXI device functions: context-lock acquisition, command construction/issue,
  NIC command-consumption polling, completion flush, payload puts and signals.
- GPU records carry block/thread/SM, event, start/end and event-specific IDs.
  Source token IDs are retained at remote put/forwarding boundaries.
- Fixed bounded per-warp buffers; overflow is a failed diagnostic, never silently
  accepted. Trace pointer injected only into per-process isolated JIT caches.
  Host/device transport ABI and queue algorithm remain unchanged.

## Interpretation rules

Inclusive spans overlap. Sum across warps/threads measures work/wait exposure,
not elapsed critical-path time. GPU barriers can hide remote-rank delays. A
token-sized put's function duration is submission time, not raw network DMA
duration. Completion flushes concern batches, so they cannot be divided into
independent token transfer times without more hardware evidence.

CPU clocks are related to rank 0 using repeated Gloo timestamp exchanges with
asymmetric-delay bounds. GPU clocks are bracketed against each host before and
after captures. Trace visualization uses an estimated offset and retains a
calibration envelope; exact cross-node ordering below that uncertainty is not
claimed. The envelope is empirical, not a proof of bounded clock drift.

NIC telemetry is sampled during an isolated repeated-dispatch window. Retain
hardware timestamps to reveal caching/resolution; rates include control and
protocol bytes. This can test sustained link utilization, but does not establish
NIC-active occupancy within one 3.4 ms dispatch.

The original 17 MB per rail is thousands of ~4.3 KB puts. The current plugin
waits for per-command consumption and uses conservative completion/signaling.
These are suspects to measure, not conclusions about the dominant cost.

## Outputs

`captures/v4flash`: raw compressed events per rank/iteration, correctness
markers, manifests, timing controls, clock calibration and NIC samples.
`analysis/v4flash`: full Perfetto trace, GPU inclusive statistics, host stage
intervals, overhead and issue-window rates, NIC interval rates, validation.

Read `validation.json` and overhead before using the detailed trace to explain
baseline behavior. A correct instrumented run is not itself an optimized run.
