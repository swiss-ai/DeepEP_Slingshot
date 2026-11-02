# DeepEP direct-CXI queue/completion campaign, 2026-10-30

Pinned DeepEP `bd1e1669`, EP8, two GH200 nodes; 4096 input tokens/GPU.
Private backend ID 6, `needsProxyProgress=0`. These are experimental variants,
not upstream GDAKI/type 3, and are not GPU-qualified until the gates pass.

Changes under test:

- `baseline`: original per-command NIC-consumption wait.
- `async`: previous credit-based command reuse, unlimited up to physical capacity.
- `cap1`, `cap2`, `cap4`, `cap8`: cap unconsumed 64-byte commands per context.
  This controls command pacing, not outstanding RDMA completions.
- `threshold`: credit-based reuse plus blocking `C_CMD_CT_TRIG_EVENT` writeback
  instead of repeated CT GET commands, using the native libcxi example recipe.
- `threshold-cap4`: the two changes together.

All variants retain per-context locking, per-command doorbells, source lifetime
rules and flush-before-signal. The threshold wait holds the lock until *all*
currently posted transfers complete. Later commands cannot satisfy an earlier
threshold. Only one CT trigger/writeback is outstanding. Lock splitting, NIC
triggered AMOs and doorbell batching require separate correctness work.

`package.py OUTPUT` produces immutable ordinary and instrumented DeepEP archives,
backend/tests/runner, hashes, variants and the gate sequence. `launch.py OUTPUT`
requires working Clariden SSH, stages a new source/prefix, compiles SM90 probes on
the login node, submits once, records the job ID, and starts a detached read-only
30-second collector. A submission record prevents accidental duplicate jobs.

The four-hour normal allocation stays open after the sequence or a failure, until
`STOP` or the allocation deadline (180 seconds reserved for shutdown). Controller
states and immutable request records follow `async_v1`. No automatic allocation
extension is possible. On failure the controller pauses; to debug, inspect logs,
prepare a **new snapshot and private runtime**, atomically add new requests, then
write `RESUME.json` with a reason. A GPU-health check precedes resume. The collector
collects evidence; it does not itself invent or apply fixes.

The campaign validates public GIN, reset/self/negative cases, burst wrap and source
reuse, multi-producer contention for threshold variants, then measures matched
fresh/cached FP8 dispatch and BF16 combine. Two reversed-order trials control for
run order; model geometries are V4 Flash, Qwen3-235B, MiniMax. No expert GEMM is timed.
The ordinary benchmark has **no trace hooks**. Four separate traced builds record
both operations on all eight ranks, with disabled-before/after timers and three
captures. Trace results must also pass payload/scale/routing/reduction checks.

Traces record GPU globaltimer intervals for context acquisition, TX capacity (or
baseline consumption), publication, CT writeback, CT command consumption, dispatch
packing/relay/arrival waits, combine contributor waits/reduction/TMA/final remote
wait, barriers and epilogues. Host dispatch boundaries and CPU/CUDA profiler traces
identify launch and CPU count-sync time. Combine host detail comes from CPU/CUDA
profiling; GPU stages have explicit hooks. GPU/host and cross-node clocks have
measurement bounds, not assumed exact synchronization. `analysis/` records local
rank stage intervals and non-double-counted wait unions for the latest-finishing
role; inclusive/parallel durations must not be summed into wall time.

These timestamps expose software issue and GPU completion observation, **not NIC
wire start/end**. NIC telemetry is collected over repeated untraced operations.
Queue allocations and ptxas register/spill reports are retained. The approximately
0.70-ms V4 Flash dispatch RDMA bound is payload serialization on a 25-GB/s rail;
metadata, local staging and synchronization can keep the complete call above it.
A successful qualification is not evidence of reaching that bound.
