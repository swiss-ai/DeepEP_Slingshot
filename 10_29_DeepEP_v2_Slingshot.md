# DeepEP v2 direct GIN on Slingshot: GDAKI-inspired asynchronous CXI backend

Date: 2026-10-29

## Target and scope

Develop a correct, efficient **GPU-initiated CXI transport for DeepEP v2 on
Clariden GH200**, using queue-management principles similar to the existing
GDAKI/MLX5 implementation. Keep the CPU out of steady-state submission,
doorbell and completion progress; CPU initialization and resource management
remain allowed. Ultimately validate cross-node dispatch/combine through SGLang.

Keep DeepEP baseline **bd1e1669**. No upstream upgrade is required for this
campaign. Preserve DeepEP's routing, packing, deduplication and NVLink relay
algorithm while improving the transport backend below the GIN interface.
The current private CXI backend is type **6**; MLX5 GDAKI type **3** is not
a switch that enables Cassini support.

Primary hardware/workload: **EP8, two GH200 nodes, four GPU ranks per node,
4096 tokens per GPU (16,384 per node)**. All eight ranks participate in one EP
group. Start with the recorded V4 Flash geometry and fresh FP8 dispatch;
then validate combine and the recorded Qwen3-235B and MiniMax 2.7 geometries.
Use existing benchmark manifests for exact dimensions, routing, dtypes and
payload definitions. Synthetic geometry benchmarks are not full model runs.

This document records the design and execution gates. Creating it does not
mean these optimizations have been implemented or validated on GPUs, and it
does not establish the current scheduler status of previously submitted jobs.

## Architectural decision

Reuse **GDAKI's asynchronous queue-management principles**, translated into
**CXI/Cassini queue and ordering semantics**. Reuse HPE's native queue logic
as the reference for Cassini-specific details.

```text
DeepEP dispatch/combine and NVLink relay
                    |
           GIN put / signal / flush
                    |
    GPU-side asynchronous CXI queue management
                    |
       Cassini descriptors and doorbells
                    |
          NIC DMA / network / completion
```

GPU and NIC execute independently, but the GPU transport code must obey the
NIC's descriptor, visibility, ordering and completion contract. The reusable
algorithm is reserve -> construct -> publish -> submit -> retire. Descriptor
layout conversion alone is insufficient.

`libcxi` and the CXI driver provide the resource and hardware interfaces;
host library functions are not automatically CUDA-callable. Our backend already
maps command queues, doorbells and completion writeback for GPU access.
HPE's `write_bw.c` enqueues multiple commands, rings once, then waits for ACKs:
CXI batching is supported. That host example does not by itself establish
safe concurrent GPU publication or payload-before-signal visibility.

## Evidence motivating the change

Existing job **3790547**, V4 Flash, 4096 tokens/GPU, fresh FP8 dispatch:

| Measurement | Median |
| --- | ---: |
| Dispatch without tracing | 3.430 ms |
| Dispatch with tracing | 3.572 ms |
| Tracing overhead | 4.12% |
| Latest-finishing sender's context-lock waits | 1.641 ms |
| Same sender's command-consumption waits | 0.869 ms |
| Same sender's completion flushes | 0.279 ms |
| Payload-only RDMA lower bound at 25 GB/s | approximately 0.70 ms |

These are separate medians across 24 rank/capture records. Overlapping sender
and forwarder intervals must not be summed into dispatch wall time.

The replay attributes **96.7% of accumulated context-lock waiter duration**
to another caller's confirmed ownership of that context; **82.3%** overlaps
that owner's command-consumption or completion-flush waits. These are
parallel waiter-time percentages, not dispatch wall-time percentages.

The inspected baseline backend deliberately holds a context lock while
`emit()` waits for command consumption. `add_locked()` flushes preceding
context transfers before signaling, including conservative handling of weak
signals. Its `FlushAsync` implementation performs a blocking flush. These
choices simplify bring-up; they are not established requirements of Slingshot.

The traces identify serialization around NIC waits. They do not establish
that the NIC is idle during all waits, that all waiting is avoidable, or that
removing waits will achieve the payload-only lower bound. Command consumption
is not payload completion; multiple payload operations may already be in flight.

Replay artifacts: [interactive timeline](results/ep_direct_replay_20261029/overview.html),
[PDF](results/ep_direct_replay_20261029/eight_rank_replay.pdf),
[validation](results/ep_direct_replay_20261029/validation.json).
All 32,275 remote-token puts per capture match relay processing, across three
captures. Older traces lack final-receiver token IDs and physical NIC timestamps.
Cross-rank alignment remains approximate; use local-clock correlations where
possible. The replay covers dispatch only.

## Semantics that must remain distinct

1. **Command consumption:** permits queue storage reuse according to CXI rules.
2. **Transfer completion:** establishes the completion condition of the operation;
   interpret the exact counter/event semantics before using it as a guarantee.
3. **Receiver visibility and signaling:** the receiver must not observe a ready
   signal and read stale payload. Submission order alone is not proof.

Queue-slot credits and outstanding-transfer accounting require separate state.
Also distinguish reusable command storage from reusable payload buffers.
Bounded queues must handle wraparound, initial status, backpressure, errors
and timeouts. Concurrent producers must never publish an uninitialized hole.
Preserve any context/state-command dependency across peers and signals.

## Staged implementation and validation

Each stage produces a source manifest, correctness outcome and measurement.
Keep the working baseline available; introduce one independently measurable
change at a time. Inspect existing experimental variants before duplicating work.

| Stage | Implementation target | Required evidence / exit gate |
| --- | --- | --- |
| 0. Freeze baseline | Pin DeepEP/NCCL/backend, image, driver/libcxi versions and job parameters; inspect existing `cq_credit_v1` prototype and any collected results. | Reproducible baseline and explicit list of tested versus untested changes. |
| 1. Establish CXI contract | Map slot units, reserved area, producer/consumer updates, wraparound, doorbell rules, counter semantics and state-command ordering to installed headers and HPE examples. | Document each invariant with source references; unresolved ordering assumptions stay conservative. |
| 2. Bounded asynchronous submit | Replace unconditional per-command consumption polling with credit-based capacity checks. Initially retain serialized publication and conservative signal flushes. | Queue arithmetic tests plus two-node GPU tests covering empty/full/wrapped queues, backpressure, payload integrity and repeated reuse. No overwrite, missing or duplicate operation. |
| 3. Reduce lock duration | Move capacity/completion waiting outside shared ownership where safe; reserve and publish commands without exposing holes. Consider single-producer queue ownership if it is simpler than concurrent publication. | Multi-warp contention tests, correct state-command sequencing, no deadlock/starvation, reduced lock-owner wait time. Re-check state after reacquiring locks. |
| 4. Aggregate submissions | Publish several ready commands per doorbell; bound batch size and latency. | Fewer doorbells per payload byte, correctness across partial batches and wraparound, timing comparison over batch sizes. |
| 5. Asynchronous completion | Separate submission from completion tracking; implement a genuine asynchronous flush/request lifecycle if required by the API. Reduce counter-query overhead without losing errors. | Correct completion snapshots and buffer lifetime; no claim of completion before the required event. |
| 6. Optimize signaling | Replace full context flushes only with a demonstrated CXI guarantee that satisfies the requested GIN signal semantics. Preserve conservative fallback. | Stress payload -> signal -> receiver validation across peers, contexts, iterations and concurrency. No stale reads or premature notification. |
| 7. EP8 dispatch/combine | Integrate validated transport variants with unchanged DeepEP algorithm and recorded model geometries. | Correct payload/scales/routing/weights and combine outputs; tracing-disabled improvement with repeatability and all-rank coverage. |
| 8. SGLang integration | Use the validated backend in the intended serving configuration; confirm actual backend selection and synchronization behavior. | Correct outputs, stable repeated execution, cross-node dispatch/combine performance and serving measurements with exact configuration recorded. |

Stages 3–6 should be split into separate patches/variants, not one combined
rewrite. If a CXI ordering guarantee cannot be established, retain the flush
and report its cost. Do not delete synchronization solely because a short
test happened to pass.

## Benchmark protocol and acceptance criteria

- First isolate the transport on two nodes: GPU-initiated put, signal, completion
  and queue-pressure probes. Include approximately 4.3 KB token payloads,
  larger aggregated payloads, and many outstanding operations. Sweep queue
  depth, batch size and concurrent callers while holding other settings fixed.
- Then run EP8 with the same token count **per rank** as EP4; total EP8 tokens
  are twice EP4. Keep placement, message sizes, routing seeds, communication
  SM allocation and timing boundaries fixed across backend variants.
- Time fresh dispatch and combine separately. State whether allocation,
  layout/notification, packing, synchronization and copy epilogue are included.
  Treat initialization separately from steady state.
- Use tracing-disabled timing as the performance result, with warm-up and
  repeated trials. Report spread and group completion, not only the fastest
  rank. Collect matching traced runs and quantify instrumentation overhead.
- Trace context acquisition/release, capacity wait, command publication,
  doorbell, completion query/observation, signal and receiver/relay progress.
  Preserve request/token IDs where possible. Keep NIC wire time distinct from
  software submission-to-completion observations.
- Validate payloads, scales, routing, weights, token counts and combine results
  with dtype-appropriate tolerances, plus stress repeated buffers and wraparound.
  Require zero trace overflow for trace-based conclusions.
- Confirm CPU-free steady-state progress through source/configuration and
  runtime evidence; GPU-originated requests alone do not prove CPU-free NIC
  submission. CPU setup is compatible with this objective.

Performance objective: materially close the gap to the measured transport
ceiling while maintaining correctness. **80% of nominal 25 GB/s = 20 GB/s**
is an aspirational transport target, not an existing result or guaranteed
full-dispatch target. Measure the usable ceiling on the same nodes.

For the recorded V4 Flash dispatch, approximately 17.4 MB per outgoing rail
gives about 0.70 ms at 25 GB/s, or 0.87 ms at 20 GB/s, for payload service
alone. Use the maximum loaded rail for the group lower bound. Full dispatch
also includes packing, signaling, relay and synchronization; overlap matters.
Report byte definitions explicitly: payload effective throughput is not
physical NIC utilization. Use operation-specific bytes for combine.

Success requires: (1) verified direct GPU progress, (2) correct sustained
operation, (3) reproducible improvement over the pinned direct-CXI baseline,
(4) a measured explanation of remaining waits, and (5) SGLang validation.
These are separate gates; runnable code alone does not satisfy the final target.

## Sources and implementation entry points

- Prior campaign and history: [10_26_DeepEP_v2_Slingshot.md](10_26_DeepEP_v2_Slingshot.md).
- DeepEP baseline: `DeepEP/`; patched integration: `tools/cxi_gin/DeepEP-cxi-dev/`.
- GDAKI adapter: `tools/cxi_gin/nccl-cxi-dev/src/include/nccl_device/gin/gdaki/gin_gdaki.h`.
- GDAKI queue reservation/publication/doorbell reference:
  `tools/cxi_gin/nccl-cxi-dev/src/transport/net_ib/gdaki/doca-gpunetio/include/device/doca_gpunetio_dev_verbs_qp.cuh`.
- Current CXI GPU primitives: [cxi_primitives.cuh](tools/cxi_gin/backend/device/cxi_primitives.cuh).
- GIN adapter: [gin_cxi.cuh](tools/cxi_gin/backend/device/gin_cxi.cuh).
- Host mappings/resources: [cxi_resources.cc](tools/cxi_gin/backend/host/cxi_resources.cc).
- Existing queue-credit experiment: `tools/cxi_gin/experiments/cq_credit_v1/`.
  Its presence is not evidence of GPU validation or deployment.
- HPE local reference: [libcxi.h](tools/cxi_gin/reference/shs-libcxi/include/libcxi.h),
  [write_bw.c](tools/cxi_gin/reference/shs-libcxi/utils/write_bw.c).
- [HPE libcxi upstream](https://github.com/HewlettPackard/shs-libcxi).
- [NVIDIA GDAKI programming model](https://developer.nvidia.com/blog/doca-gpunetio-gda-ki-unified-gpu-networking/).

## Allocation and source-isolation plan

Live Slurm check on **2026-10-29 at 21:16 CET**:

| Job | Workload | Partition | Status | Requested duration |
| --- | --- | --- | --- | --- |
| 3792104 | Apertus UCCL CPU-proxy request trace | debug | PENDING, Priority | 30 minutes |
| 3792106 | DeepEP CPU-proxy GIN request trace | normal | PENDING, Priority | 30 minutes |
| 3792108 | DeepEP direct-CXI GIN request trace | normal | PENDING, Priority | 30 minutes |

Tentative starts at that check: UCCL Oct29 23:45; DeepEP proxy Oct30 05:59;
DeepEP direct Oct30 08:00 CET. These are scheduler estimates, not reservations.

Existing request-chain jobs use staged `sources/v4` inputs under
`/iopsstor/scratch/cscs/zyu/ep8-request-chain-20261029/`, with source-manifest
verification and per-job extraction/build directories. Local edits alone do
not affect those remote inputs. Do not overwrite the snapshot or the shared
NCCL build prefix/runtime dependencies used by these jobs. Slurm saves the
batch script, but does not freeze every externally referenced file.

For new variants, create distinct source snapshots, build/install prefixes,
JIT caches and output directories. CUDA/header changes require rebuilding
the consuming kernels/extensions; updating source files does not update an
already running process. Each attempt launches fresh processes against its
explicit build and records the manifest.

Use a **reusable two-node normal-partition development allocation** for the
optimization campaign. A four-hour initial request is a proposed balance;
choose the requested duration before submission based on the prepared work.
Live partition limits are debug **01:30:00**, normal **12:00:00**. Account/QoS
and scheduler eligibility still apply. The debug QoS currently permits one
running and two submitted jobs per user, so extra debug requests can also
wait behind the user's existing jobs.

The development controller should:

1. Keep the batch allocation alive across sequential, bounded `srun` attempts.
2. Accept a new immutable source/build variant between attempts, without
   modifying binaries used by an active test.
3. Save stdout/stderr, source identity, correctness results and timings per
   attempt, and retrieve them while the allocation remains active.
4. After a test failure, terminate and drain the entire failed step, record
   failure and prohibit dependent tests. Permit an explicitly submitted
   corrected attempt if node health and remaining walltime allow it.
5. Enforce timeouts, a cleanup reserve, STOP control and a bounded idle period.
   Exit when work is complete or the allocation deadline approaches.

The older `backend/tools/lease.sbatch` / `lease_driver.py` is a starting point,
not yet this controller: it caps itself at one hour, exits after ten idle
minutes and stops on a failed request. Adapt these behaviors explicitly and
test cleanup before using it for the new campaign.

This preserves the allocated window **within the granted walltime**, even
if individual test processes fail. It cannot keep nodes indefinitely until
the research target is achieved. If the window expires, another allocation
must queue; requeueing does not guarantee retaining the nodes or immediate
restart. A Slurm job hold keeps a pending job from starting; it is not how
to retain a running debugging allocation.

No new job was submitted in this status check. Existing jobs were not changed.

## First implementation and submitted allocation — 2026-10-29 21:27 CET

**Job 3795952** submitted: `normal`, two nodes / eight GPUs, four hours,
job name `deepep-cxi-async-dev`. Verified **PENDING (Priority)** at 21:27 CET;
Slurm did not yet provide an estimated start. The earlier three request-chain
jobs and their staged inputs were not modified.

Implemented the first bounded-asynchronous-TX variant in
`backend/device/cxi_primitives.cuh`, with new `cxi_queue_credit.h`, and mirrored
these headers into the local NCCL development tree. `emit()` checks usable
command slots against the NIC read pointer before publishing; it no longer
waits for every newly published command to be consumed. Invalid queue metadata
is rejected. The arithmetic follows Clariden's installed
`__cxi_cq_free_slots_check`, including reserved status space and an empty slot
to distinguish full/empty after wraparound.

This is **stage 2**, not completion of the entire design: capacity waiting
still holds the context lock, each command still rings the doorbell, and
completion flushes and signaling remain conservative. No predicted speedup
or GPU qualification is asserted. The earlier unqualified `cq_credit_v1`
prototype supplied the starting point; metadata checks and validation were
strengthened for this campaign.

Isolated campaign root:
`/iopsstor/scratch/cscs/zyu/deepep-async-20261029`.
Submitted snapshot: `sources/source-v3`, mirrored locally under
`results/deepep_async_20261029/source-v3`. Both runtime prefixes copy the
hash-verified existing NCCL library; only the candidate device headers differ.
The host ABI is unchanged. DeepEP native extensions and test kernels are
rebuilt separately for each variant/node, with per-attempt JIT caches. This
is a device-header experiment, not a rebuilt candidate NCCL shared library.

The single allocation contains **16 sequential gated attempts**:

1. Baseline public GIN correctness with 1/4/129 contexts.
2. Candidate burst/wrap/source-reuse probe: four epochs, 4096 payload commands
   per epoch per rank, a small requested command queue, exact data checks.
3. Candidate public GIN, reset, self-signal and negative/recovery checks.
4. Bounds rejection.
5. Shared-context producer stress, 1/2/8 CTAs and 512 rounds.
6. Small EP8 BF16/FP8 dispatch/combine correctness and timings.
7. Six paired V4 Flash 4096/GPU FP8 attempts (three per variant), alternating
   execution order across trials, with fresh dispatch/cached dispatch/combine
   reported separately by the benchmark.
8. Two wider geometry sweeps (one per variant): V4 Flash, Qwen3 and MiniMax,
   4096/GPU, BF16/FP8.
9. Empty-receiver routing case.
10. SGLang dispatcher/scatter-gather integration with exact dispatch reference;
    this is not a full serving or expert-GEMM qualification.

Validation before submission:

- CPU ring model PASS: 1,044,160 states, 478,906 writes, 321,094 backpressure
  observations and 33,620 wraps, with delayed consumer writeback.
- Two controller/gate unit tests PASS, covering failed/unqualified dependencies
  and missing/incorrect burst completion evidence.
- Python/shell syntax, snapshot hashes and 16-step dependency chain PASS.
- CUDA SM90 compilation PASS for baseline/candidate smoke, producer and GIN
  API probes, plus the candidate burst probe. Initial burst compile exposed
  duplicate ABI-header inclusion; the include paths were corrected before
  the submitted snapshot and successful preflight.
- GPU correctness, EP8 performance and SGLang gates: **NOT RUN yet**.

Runner and operating instructions:
[async_v1/README.md](tools/cxi_gin/experiments/async_v1/README.md).
The controller pauses after a failed attempt, records evidence, and accepts
an explicit corrected request/resume after a two-node GPU health check.
Failed dependencies cannot run. It remains available for up to **45 idle
minutes**, with a cleanup reserve and the four-hour Slurm deadline enforced.
It is not an unattended code-writing or automatic repair agent.

Detached read-only monitor PID **4045668** was verified alive. It polls every
30 seconds and retrieves intermediate logs/results while the job runs:

- [Live status](results/deepep_async_20261029/job-3795952/latest.txt)
- [Submission record](results/deepep_async_20261029/submitted.json)
- [Local validation](results/deepep_async_20261029/local-validation.json)

The monitor does not extend allocations or change code. Further optimization
of lock ownership, doorbell aggregation and signal ordering remains gated on
this candidate's GPU results.

## Update log

### Results checked 2026-10-30 09:58 CET

Live Slurm reports no pending/running jobs for the user. Development job
**3795952 COMPLETED (0:0)**, Oct30 05:47:17–06:49:12 CET. All **16 gates PASS**,
including burst wrap/source reuse, public GIN, bounds, multi-producer stress,
EP8 dispatch/combine and SGLang dispatcher/scatter-gather. The SGLang check
does not include real expert GEMMs or full serving. The final gate finished
at 06:04:08 CET; the controller then released the allocation after its configured
45-minute idle window. No allocation is currently held. Terminal-job monitors
have exited after collecting results.

V4 Flash, EP8, 4096/GPU, FP8 dispatch: median of three trial medians, each
using the per-iteration maximum across all ranks, tracing disabled:

| Operation | Baseline | Asynchronous TX | Latency change |
| --- | ---: | ---: | ---: |
| Fresh dispatch | 3.474 ms | 3.158 ms | -9.1% |
| Combine | 4.553 ms | 5.709 ms | +25.4% |

The candidate passes the exercised correctness gates but is **not an overall
performance improvement**. Do not promote it as the preferred backend:
the combine regression requires investigation. No claim of network saturation
or completion of the final optimization target is supported by these results.

The three older request-chain tracing jobs failed independently of this
candidate campaign:

- **3792104 UCCL:** FAILED (1:0), after 1m15s, Oct29 23:08 CET. Initial
  correctness passed on all eight ranks; GPU trace decoding rejected `(0,0,0)`.
- **3792106 DeepEP proxy:** FAILED (1:0), after 1m54s, Oct30 02:41:55 CET.
  Initial correctness passed on all eight ranks; `ncclEpTraceStop()` returned
  nonzero during the CPU-trace warm-up. This is a different immediate failure
  from the GPU decoder assertion; the underlying writer failure needs analysis.
- **3792108 DeepEP direct:** FAILED (1:0), after 2m02s, Oct30 02:42:56 CET.
  Initial correctness passed on all eight ranks; GPU trace decoding rejected
  `(0,0,0)`.

These failed jobs do not supply a validated complete request-chain trace.
The immediate failures are in trace handling, not evidence of a failed initial
payload correctness check. This status check did not resubmit or modify jobs.

- 2026-10-29: Established this target and staged plan from local source review
  and the existing eight-rank replay. This update changes documentation only;
  it does not submit jobs, modify transport code or assert new GPU test results.
- 2026-10-29 21:16 CET: Confirmed the three request-chain jobs remain pending;
  recorded source isolation and the reusable-allocation workflow and limits.
- 2026-10-29 21:27 CET: Patched bounded asynchronous TX, completed CPU/compile
  checks, submitted single development job 3795952, and started its live monitor.
