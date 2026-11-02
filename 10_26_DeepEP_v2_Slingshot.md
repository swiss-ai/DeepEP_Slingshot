# DeepEP v2 direct Slingshot GIN investigation — 2026-10-26

## Result audit — job 3781109, October 28

COMPLETED 0:0 in 5m02s on nid007583/nid007625. All four gates PASS,
independently revalidated after collection: twenty-cycle lifecycle, uniform
4K FP8, uniform 4K BF16, and local-only/remote-only FP8. Profile coverage
validated: 96 uniform traces + 192 routing-control traces across all eight ranks.

Standalone FP8 fresh-dispatch / BF16-combine rank-max median ms:
V4Flash 3.400 / 4.529; Qwen3 1.358 / 4.591; MiniMax 2.425 / 3.315.
Expert GEMM, quantization and SGLang layout are outside this standalone timer.

Initial profile finding: hybrid dispatch/combine kernels dominate GPU kernel
time. Median across ranks of per-rank profiled kernel medians: V4Flash hybrid
dispatch 3.444ms, copy epilogue 0.129ms; hybrid combine 4.353ms, reduction
epilogue 0.029ms. These instrumented durations are diagnostic; do not add
them to unprofiled latency or interpret them as pure NIC transmission time.
Internal command/credit/completion wait attribution remains outstanding.
Raw traces, validated kernel/timeline CSVs: `results/deepep_direct_10_26/tenhour/leases/3781109/`.

## EP8 latency profiling resubmission — 2026-10-28, 10:56 CET

Job **3781109** accepted on normal, two GH200 nodes/eight ranks, 30 minutes.
Debug rejected by QOSMaxSubmitJobPerUserLimit. No new result is claimed.
Source bundle: `results/deepep_direct_10_26/source-bundles/20261028-ep8-profile-v1`.

Corrected the validator to recognize the separately created four-context bank,
require its final release, and retain exact reuse, physical CT plateau and
teardown checks. All 57 regression tests PASS, including retained GPU logs and
negative resource-growth/unreleased-bank cases. Revalidation of job 3768857's
first stage passes all eight ranks; its original FINISHED record stays unchanged.
Clean DeepEP/NCCL source-patch reconstruction also PASS.

Four dependency-ordered gates: (1) persistent-window twenty-cycle lifecycle;
(2) 4K/GPU FP8 uniform routing, all three geometries, 10 warmups/50 samples,
NIC windows and separate five-iteration all-rank CUDA/CPU profiles;
(3) BF16 counterpart; (4) FP8 local-only/remote-only routing profiles.
Operations: fresh dispatch, cached dispatch, combine, complete cycle.
Profile postprocessing emits kernel durations, merged GPU-active intervals,
gaps and host CUDA/synchronization intervals without double-counting overlap.
These traces cannot isolate command-consumption/completion waits inside a fused
GPU kernel; targeted device instrumentation is a subsequent step if needed.
Standalone timing excludes quantization and expert layout/GEMM. These results
will not be labelled SGLang wrapper timing or full-model TTFT.

Remote source: `/iopsstor/scratch/cscs/zyu/deepep-direct-20261026/tenhour/sources/gate-20261028-ep8-profile-v1`.
Remote results: `.../tenhour/leases/3781109`.

## Overnight result audit — 2026-10-28, 09:47 CET

The agent goal remains **blocked**, not paused. It was marked blocked after
three allocation waits yesterday; the queued controller subsequently ran,
but no new agent debugging turn was triggered by the job's completion.
No DeepEP or UCCL campaign is currently queued/running.

Job **3768857 FAILED/1:0** after 57 seconds around 19:58 CET on October 27.
Its first GPU step itself exited **0**. All eight ranks completed twenty
129-context cycles, with two epochs of fourteen payload rounds per context,
zero recorded errors and successful teardown. A retrospective raw-record audit
confirms this across every rank/context/epoch.

The controller rejected the stage because the new validator assumed exactly
20 creation entries and 129 total physical channels. The logs contain an
additional initial four-context allocation, then the twenty requested tests.
All tested cycles retain **133 physical channels/CTs**, and the final reuse count
is **2451 per rank**. This is positive GPU evidence for the lifecycle fix; it is
not a pass for the complete campaign. The other fifteen gates never ran.
Do not rewrite the original failed FINISHED record. Retrospective evidence:
`leases/3768857/retrospective-lifecycle-audit.json`.

Next: correct the validator to distinguish the extra persistent context bank
from the tested bank, retaining all growth/teardown checks; rerun remaining
qualification. The independent lifecycle postprocessor has the same assumption
and needs the matching correction. No replacement job was submitted during
this status inquiry.

The independent UCCL job **3768476 FAILED** at 07:02 CET on October 28. Its
256-token/GPU FP8 correctness records pass on all eight ranks, but it aborts
at case teardown with `CUDA error: context is destroyed`. The exact teardown cause is not established. The source exposes a
`device_reset` helper, but the inspected buffer cleanup does not call it; do
not attribute this failure to that helper without further evidence.
The intended 4K/token-size sweep did not run; no new saturation result exists.


## Agent blocked on allocation; queued job preserved — 2026-10-27, 17:55 CET

The preceding turn was a verified wait. This third consecutive availability
check again confirms **3768857 PENDING/Priority**, zero runtime, no assigned
nodes or execution markers. Debug remains occupied by running 3768464 and
pending 3768876. Equivalent priority/start-estimate changes have not supplied
an allocation. Independent source, compilation, validation and follow-up
preparation is complete; further implementation decisions require GPU evidence.

The agent goal is now **blocked**, not complete. **Job 3768857 remains submitted
and eligible** with the same sixteen requests, fifteen-minute minimum and
sixty-minute maximum. Its controller runs automatically when Slurm admits it,
stops on failed validation, and reports an incomplete/failed campaign via a
nonzero batch exit. No source, request or other workload was modified.

On resumption inspect this same job first, collect its records, and run the
independent lifecycle-resource audit on both initial gates. Then inspect the
SGLang, routing/padding/profile/context and clean-build evidence. Do not submit
a competing lease or the queue-credit candidate before baseline qualification.
The resource-lifetime fix remains GPU-unverified until those records exist.


## Second availability wait — 2026-10-27, 17:54 CET

Previous turn was a verified wait. Repeated authoritative checks again find
3768857 PENDING/Priority, zero runtime, no assigned nodes and no execution
markers. Debug still has one running and one pending workload, occupying its
submitted-job limit. No duplicate, source change or modification of other
workloads was made. This is the second consecutive equivalent allocation
blocker after the latest progress; the goal remains active.


## Allocation wait verified — 2026-10-27, 17:53 CET

Previous turn made progress on the lifecycle evidence audit and backfill
minimum. This turn is a **verified wait**: repeated live `squeue`/`sacct`
checks confirm job 3768857 PENDING/Priority, zero runtime, no assigned nodes
and no execution markers. The provisional estimate was 18:49 CET at 17:52;
no start-time promise is inferred. This is the first consecutive availability
wait after the latest progress. The goal remains active. Existing requests,
source and other workloads are unchanged; no duplicate job was submitted.


## Lifecycle evidence audit and candidate refresh — 2026-10-27

The preceding goal turn was progress: CT-lifecycle source fix, native compile
and job 3768857 submission. The job remains PENDING/Priority; at 17:49 CET its
provisional start moved to **19:20 CET**. No allocation or GPU result yet. The estimate subsequently moved to 22:20 CET.
At **17:51 CET**, while confirmed pending, reduced this job's backfill minimum
from 20 to **15 minutes**, retaining its 60-minute maximum and all requests.
The first 570-second gate plus 30-second admission margin and 150-second
cleanup reserve needs 750 seconds; a 900-second allocation can admit it if
startup leaves enough time. The controller still enforces actual remaining
time. Slurm confirmed the change and cleared the start estimate pending
reevaluation. No queued source/request or other workload was changed.

Added a local-only `backend/tools/analyze_lifecycle.py` postprocessor. After
existing payload/teardown qualification, it requires all eight ranks to show:

- Persistent-MR test: twenty context cycles, one physical 129-channel bank,
  2451 channel reuses, non-growing actual CT usage, pooled channels after every
  close, and one final idle-LNI cleanup after releasing the held MR.
- Idle-MR test: twenty context cycles and twenty idle-LNI cleanup events;
  fresh per-LNI allocation counters rather than reuse disguised as cleanup.
  Report actual CT usage including any deferred driver reclamation.

Six focused tests cover valid reuse/reopen, hidden counter growth, missing
cleanup, reopen masquerading as reuse and missing-rank logs. All **56 local
regression tests PASS**. This postprocessor is separate from the immutable
queued snapshot and will independently audit collected evidence.

The older queue-credit performance snapshot predates the CT-lifecycle change.
Prepared a new **local-only, unqualified** candidate bundle
`source-bundles/20261027-credit-with-ct-reuse/`, retaining exactly the queued
host-plugin fix in both candidate and baseline controls. Its GPU change still
only replaces per-command consumption waits with bounded TX queue credits;
no candidate GPU result or bandwidth claim exists.

Prepared twelve ordered follow-up gates: baseline recovery/bounds regression,
candidate raw/public-GIN/bounds/concurrency, small/full EP8, matched baseline EP8,
and actual SGLang checks for all three geometries. Actual parser/dependency
validation passes. Requests are in
`queue-candidates/credit-v1/post-lifecycle/sequence.json`. They are **not
submitted** and must wait for baseline qualification and the lifecycle audit;
refresh them if GPU evidence requires a different host fix.


## Resumed: CT lifetime fix prepared — 2026-10-27

**Submitted job 3768857** on normal: two GH200 nodes, 20-minute backfill minimum,
60-minute maximum. At 17:46 CET it is PENDING/Priority, estimated 18:00 CET
(provisional). Snapshot `gate-20261027-ct-reuse-v1` uses complete source bundle
`20261027-ct-reuse-v3`. No existing job was modified. The agent goal is active.


Previous turn was **progress**: retrieved terminal job 3766440 and independently
qualified its first seven stages. The agent goal has now resumed. Source and
runtime evidence identify a concrete resource-lifetime mismatch: the public
CXI driver's `cxi_ct_free` moves CTs to an LNI cleanup list; `finalize_ct_cleanups`
returns IDs during LNI cleanup. The exact installed driver revision is not
established, but the observed 15 successful 129-context lifecycles followed by
failure after another 108 allocations is consistent with this behavior.
References: [CT lifecycle](https://github.com/HewlettPackard/shs-cxi-driver/blob/main/drivers/net/ethernet/hpe/ss1/cass_ct.c)
and [LNI cleanup](https://github.com/HewlettPackard/shs-cxi-driver/blob/main/drivers/net/ethernet/hpe/ss1/cass_lni.c).
Fetched source/blob identities and logs are retained in
`results/deepep_direct_10_26/ct-lifecycle-20261027/`.

Candidate host-plugin changes (no GPU ABI, datapath or pinned baseline change):

- Recycle healthy, quiesced channels within their owning LNI. Retain physical
  CT values, completion counts and GPU queue cursors together; never reset
  software counts against a live, nonzero hardware CT. Clear stale signal-MR
  references before assigning new per-context signal storage.
- Do not pool channels with diagnostics, an active lock or unfinished work.
  Preserve checked teardown for unhealthy/partial-setup paths.
- Once no registered MRs or device contexts remain, close the LNI and its pooled
  resources. Reopen lazily on the next registration. This releases other
  deferred IDs too; it is host setup/teardown, not CPU network progress.
- Record allocation/reuse/idle counts and actual service CT usage. Fail the
  persistent-window lifecycle gate if physical allocations or CT usage grow.

All **50 local regression tests PASS**. Fresh pinned DeepEP/NCCL patch
reconstruction also passes. Source bundle: `20261027-ct-reuse-v3`; earlier v1/v2
bundles are superseded preparation artifacts, not the submitted manifest.
Native aarch64 host-plugin and SM90 probe compilation **PASS** at 16:45:23 UTC.
All 62 staged backend hashes match; GPU execution is still pending.

The next immutable sequence has 16 gates: twenty 129-context cycles while
retaining an MR, twenty cycles allowing idle-LNI cleanup, then all fourteen
original gates including SGLang, routing/padding, profiling and clean builds.
The wrapper will now propagate incomplete/failed gates into the batch exit
status instead of reporting a successful Slurm batch for a stopped campaign.

### Newly qualified SGLang timings from job 3766440

Direct/proxy comparison validates all eight ranks, same allocation, code,
input/routing/weight hashes and submitted configuration. 4096 tokens/GPU,
10 warmups + 50 samples; rank-max medians in ms:

| Geometry | FP8 dispatch direct / proxy | BF16 combine direct / proxy |
|---|---:|---:|
| V4Flash | 3.440 / 6.660 | 4.196 / 6.162 |
| Qwen3 | 1.473 / 6.805 | 4.455 / 6.483 |
| MiniMax | 2.567 / 6.971 | 3.196 / 6.552 |

Scope: synchronized SGLang wrappers with actual scatter/gather; FP8 dispatch
includes quantization. Expert computation is excluded from these timings;
these are neither TTFT nor proof of network saturation. Pairing validation and
both FP8/BF16 CSVs are in `leases/3766440/comparisons/`.


## Status audit — 2026-10-27, 17:35 CET

The agent goal is **blocked**, and no DeepEP direct-GIN job is currently queued
or running. The former pending job **3766440 actually ran 14:33:35–14:43:53 CET**
on nid006137/nid006146. Its bounded controller has FINISHED and STOP markers.
Slurm reports COMPLETED/0:0 for the batch, but step .7 failed; this is not a
successful full campaign. No replacement was submitted during this status inquiry.
The previous scheduler-only status below is historical.

Collected the job records and independently revalidated the first seven gates:

- Gate 01 PASS: exact SGLang reference, actual scatter/gather and reduced real
  expert kernels, all eight ranks, V4Flash 32/4096, FP8/BF16. The previous
  source-stride reference fix is now GPU-validated.
- Gates 02–07 PASS: SGLang direct/proxy tests for Qwen3, MiniMax and V4Flash,
  4096 tokens/GPU, FP8/BF16, ten warmups and fifty measured iterations. All
  eight ranks and timing schedules pass the local validators. This does not
  yet assert a numeric speedup or model TTFT.
- Gate 08 FAILED: while constructing the V4Flash/local/seed2 ElasticBuffer,
  `cxil_alloc_ct(...)= -28` preceded NCCL's `GIN: DevComm setup failed on all
  available backends`. This indicates a CXI completion-counter allocation
  resource failure. The cause (limit, retained resources, deferred reclamation,
  or teardown issue) needs investigation; it is not established as corruption
  or an unsupported NIC.
- Gates 09–14 did not run. Profiling, remaining padding/context/clean-rebuild
  checks and the queue-credit candidate remain unfinished.

Evidence: `results/deepep_direct_10_26/tenhour/leases/3766440/`, including
`independent-revalidation.json`, per-gate FINISHED records and raw node logs.
The independent UCCL rebenchmark job 3768476 remains PENDING/Priority; it does
not resume this DeepEP investigation.


## Scheduler blocker revalidated — 2026-10-27, 11:54 UTC

Job **3766440 remains PENDING**, with zero runtime, no assigned nodes and no
execution/result markers. Both `sacct` and `squeue` confirmed this at
11:53:52 UTC. The latest estimated start is **18:30 CET**, but estimates have
changed repeatedly and are not a promise. The normal job keeps its ten-minute
backfill minimum, one-hour maximum and all fourteen immutable requests.

The debug alternative remains unavailable under the current per-user policy:
3765804 is running and 3766779 is queued, occupying the two submitted-job
slots. The earlier attempt to add debug eligibility was rejected by Slurm;
the original normal job was released and preserved. No other workload was
changed, cancelled or reprioritized.

Three consecutive monitoring turns after the backfill adjustment have verified
the same underlying blocker: no authorized two-node allocation is available
to execute the next GPU gate. Changes between Priority/QOSGrpNodeLimit and
shifting time estimates are equivalent availability conditions. Independent
preparation is complete: exact-reference fix, immutable requests, trace
analysis, clean-build inputs, and the isolated queue-credit prerequisite
experiment. No additional hardware result can be inferred from compilation
or further queue polling. The agent goal is blocked pending node allocation;
this is **not** a failed benchmark or a completed objective.

**Job 3766440 remains submitted and eligible.** Its bounded controller will
run the staged sequence automatically when admitted, stop on a failed gate,
and refuse any later gate whose timeout does not fit the allocation. Blocking
the agent does not cancel this Slurm job. On resumption, inspect this same job
and collect its per-request records before making any new submission. First
validate the fixed exact SGLang reference, then warmed direct/proxy timings,
routing/padding, profiling, contexts and the clean native rebuild/EP8 rerun.
The queue-credit experiment has not been submitted and has no GPU pass.

## Scheduler options checked; backfill minimum reduced — 2026-10-27, 11:45 UTC

The preceding turn was a verified wait. Job **3766440** remained pending with
reasons alternating between Priority and QOSGrpNodeLimit. At 11:42 UTC the
scheduler estimated 19:30 CET, so the available authorized debug/normal paths
were inspected rather than submitting a duplicate allocation.

Both partitions permit the job's QOS `normal`, and the two-node/one-hour shape
fits debug's size/time limits. However, while 3766440 was confirmed pending
and held, Slurm rejected `Partition=normal,debug` under its accounting/QOS
policy. The debug partition QOS permits **one running and two submitted jobs
per user**; another EP4 job was running and another queued. The hold was
released, and authoritative inspection confirmed 3766440 still pending on
normal, with no restart and no changes to the other workloads.

The job's backfill minimum was then reduced from **20 to 10 minutes**, retaining
the **60-minute maximum**, source snapshot, job ID and complete 14-stage
sequence. The first 420-second request fits a ten-minute allocation with the
controller's 90-second cleanup reserve and 30-second admission margin, provided
startup leaves sufficient time; the controller still checks the actual budget.
Later requests that do not fit are refused, not called completed. All unrun
requirements remain part of the goal and will need a subsequent allocation.

At 11:44:56 UTC, Slurm accepted `TimeMin=00:10:00` and estimated a start at
**12:57:35 CET**, with a scheduled node list but **no assigned nodes yet**.
This is a provisional scheduler estimate, not proof of admission or execution.
The job's immutable requests and binaries are unchanged. No scheduler policy
was bypassed and no competing allocation was added.

## Queue-credit prerequisite experiment staged — 2026-10-27, 11:35 UTC

The previous goal turn made progress by packaging complete pinned rebuild
inputs. Job **3766440** was rechecked repeatedly and remained
**PENDING/QOSGrpNodeLimit** through 11:34 UTC. Its immutable source and requests
are unchanged. No competing allocation has been submitted.

The separate queue-credit hypothesis is now executable through a prepared,
six-gate sequence, but **no candidate GPU test has run**:

1. Raw changing payload/source-reuse/guards, all eight GPUs.
2. Public GIN, 1/4/129 contexts, reset, negative-version/delayed-peer/self tests.
3. Concurrent producers, 1/2/8 CTAs, 128 rounds, depth 1024.
4. Small EP8, 128/512 tokens, BF16/FP8.
5. Three geometries at 4096/GPU, FP8, three seeds, warmed timings/NIC counters.
6. Matching unchanged direct-GIN baseline on the same allocated nodes.

The local request sequence and status are under
`results/deepep_direct_10_26/queue-candidates/credit-v1/prerequisites/`.
Submission waits for inspection of the baseline exact-SGLang, wider-routing
and profiling gates. It must use the new validator **after** the current lease
is terminal; the existing controller files have not been replaced.

Added fail-closed raw-dynamic and concurrent-producer acceptance checks so
these can be actual dependencies rather than merely zero-exit shell steps.
All **49** local regression tests pass. The historical raw baseline from
3758296 passes the new raw check. Historical producer rank JSON predates the
current `cycle`/`evidence` schema, so it is not claimed as a pass through the
new producer gate; that gate will use new candidate records without weakening
the schema.

Remote experimental source:
`tenhour/sources/credit-prerequisites-20261027-v2`.
Private prefix: `tenhour/experiments/credit-v1/runtime-v2`.
This copies the exact tested host library (unchanged ABI) and overlays only
the candidate device headers; it is **not** a rebuilt candidate NCCL release.
The raw source mirror and installed probe/JIT headers are hash-checked.
New node records retain installed device-header hashes in addition to library
hashes, since type 6 and an unchanged host binary alone cannot identify the
queue policy. The original tested prefix is untouched.

All three prerequisite CUDA probes compiled successfully for SM90 at
11:34:42 UTC on the login host, with no GPU execution. Logs and object hashes
were collected into `prerequisites/compile/`. The candidate still retains
one doorbell per command, transfer ACK accounting and conservative
flush-before-signal ordering; only the per-command consumption wait becomes
a bounded ring-credit check. No candidate latency or bandwidth claim yet.

At 11:36 UTC, an `squeue` query timed out at the Slurm socket. An independent
lease-directory check found no execution markers, and a subsequent bounded
`sacct` query confirmed **3766440 PENDING**, zero runtime and no assigned nodes.
This observation timeout was not treated as test failure or used to restart
the job.

## Complete rebuild inputs packaged — 2026-10-27, 11:30 UTC

The preceding goal turn made progress on trace analysis. This turn rechecked
Slurm: **3766440 is still PENDING/QOSGrpNodeLimit**, with no allocation or
executed request. Debug also has another workload running and queued behind
its per-user job limit; neither was changed. No duplicate job was submitted.

P14 audit found that the pinned NCCL base archive was in an older bundle,
separate from the newer DeepEP/fmt inputs. The NCCL rebuild script recorded
the archive hash but did not check it against a manifest before extraction.
The exporter now optionally packages all three archives, exporting DeepEP
and NCCL from their exact baseline Git objects and requiring the known fmt
archive hash. New build scripts check SHA256 and Git archive commit IDs
before extraction. The clean source patches and runtime implementation are
unchanged from the queued `gate-20261027-1120` snapshot.

New immutable local bundle:
`results/deepep_direct_10_26/source-bundles/20261027-complete-rebuild-inputs/`.
Both patches reconstructed successfully in fresh checkouts; all **62** backend
file hashes and all three archives verified. The NCCL archive SHA256 matches
the input recorded by the earlier successful clean build. Negative checks
reject an incorrect checksum, incorrect pinned commit and non-local archive
filename. Evidence is `archive-verification.json` within this bundle.

Added `backend/docs/reproduce.md` with the complete source/build procedure,
external CSCS environment dependencies, bounded GIN/native-DeepEP EP8 gate
settings, tested hardware scope and evidence requirements. The new input
verifier/build scripts have not replaced the immutable queued scripts, and
this packaging work is **not** a new binary build or GPU qualification.
The clean native DeepEP build and reconstructed NCCL GPU tests remain queued
behind the exact SGLang and communication gates.

## Trace analysis prepared while the corrected run waits — 2026-10-27, 11:26 UTC

The preceding status turn was a verified wait: SSH/Slurm confirmed job
**3766440 PENDING/QOSGrpNodeLimit**, with no allocation or executed gate. The
same job remains queued; it has not been restarted or replaced. The corrected
source-ID reference still needs GPU validation before dependent gates run.

Added local `tools/cxi_gin/backend/tools/analyze_profiles.py` for the separate
CUDA profiling gate. It requires a successful EP request, passing eight-rank
correctness, every requested model/routing/operation/rank trace, matching
input/route/settings identities, actual CUDA kernels, and the requested
iteration markers. It merges overlapping kernel intervals across streams and
reports their union, envelope and gaps, plus separate host CUDA API and
synchronization intervals and kernel-name statistics. CPU-only, incomplete or
mismatched traces are rejected. Seven regression tests pass, including
overlapping streams, missing rank/iteration evidence and mismatched inputs.

These outputs are explicitly `DIAGNOSTIC_ONLY`: kernel envelopes contain gaps
between profiled iterations, host calls overlap GPU execution, and traces do
not expose stalls inside persistent communication kernels. They cannot by
themselves attribute a queue-consumption or completion bottleneck, and they
do not replace unprofiled latency measurements. No GPU traces from the queued
run are available yet. The immutable queued snapshot is unchanged; this is
local postprocessing for collected evidence.

After collection, run:
`python3 tools/cxi_gin/backend/tools/analyze_profiles.py results/deepep_direct_10_26/tenhour/leases/3766440/results/10-ep-direct-profile`
only if that request actually completes. Wider routing correctness and warmed
SGLang gates still precede profiling; a failed earlier gate stops the sequence.

## Exact-reference stride failure diagnosed; rerun submitted — 2026-10-27, 11:20 UTC

Job **3765998** ran on `nid006281,nid006283` and stopped after its first
request. Slurm's outer batch is COMPLETED/0:0, but step `.0` and request
`01-sglang-exact-experts` **FAILED/1:0**. The remaining thirteen gates did not
run. All eight failed rank records were collected and preserved in
`leases/3765998/failure-analysis.json`.

The first FP8/32-token iteration failed the new source-ID equality check, with
matching received-row counts on every rank. Source inspection identifies a
checker error: `hybrid_dispatch.cuh:402` encodes IDs as
`rank_idx * kNumMaxTokensPerRank + token_idx`, and the SGLang adapter reserves
4096 tokens/rank even for a 32-token batch. The independent reference used
`rank * actual_tokens + token_idx`, so its stride was 32. Previous standalone
tests reserved exactly their batch size and did not expose this difference.

`reference_dispatch` now accepts an explicit source-ID stride (defaulting to
the actual token count for existing standalone callers). SGLang passes its
reserved capacity. The check remains exact; it was not removed or weakened.
Mismatch diagnostics now retain actual/reference source-ID heads and tails.
The source-ID stride is also recorded per case. Parsing and the actual-parser
sequence preflight pass; **the corrected GPU check has not yet passed**.

Replacement job **3766440** was submitted only after accounting confirmed
3765998 terminal. It uses two normal nodes, the same 60-minute maximum and
20-minute minimum, and immutable **`gate-20261027-1120`**, verified before
release. The same 14-stage sequence starts by rerunning the failed exact
SGLang gate. Request records are under
`results/deepep_direct_10_26/tenhour/followup-20261027-1120/`.
The queue-credit experiment remains separate and unselected.

## Isolated queue-credit candidate prepared — 2026-10-27, 11:16 UTC

Job **3765998** remains pending; its tested baseline and immutable 14-stage
sequence are unchanged. The previous goal turn was progress: it corrected the
unexecutable routing matrix and added exact comparison checks before GPU use.

A separate experiment under `tools/cxi_gin/experiments/cq_credit_v1/` prepares
one narrowly scoped change: permit multiple published TX commands when the
ring has credits, instead of waiting for NIC consumption after every command.
It retains the context lock, one doorbell per command, system publication fence,
transfer ACK accounting, conservative flush-before-signal ordering and ABI 1.
It does **not** yet implement deferred doorbells or weaker signaling.

The credit calculation follows the installed libcxi contract: eight initial
32-byte units reserved for status and one extra 64-byte empty entry. A CPU
model of the actual helper passed **1,044,160 pointer states**, **478,906
writes**, **321,094 backpressure observations** and **33,620 wraps**, including
delayed consumer-pointer updates. This tests arithmetic and slot ownership;
it is not evidence of GPU/NIC ordering or performance.

The candidate also passed an offline CUDA SM90 compilation of the public GIN
put/signal/flush probe against a new private header tree on the login host.
No GPU kernel ran. Candidate artifacts and build logs are retained at
`results/deepep_direct_10_26/queue-candidates/credit-v1/`; remote preparation is
`tenhour/experiments/credit-v1`. The qualified release and queued source
snapshots were not changed. No runnable library prefix or candidate GPU job
has been enabled.

Next candidate gates, after baseline integration/profiling: raw dynamic payload
and source-reuse; public GIN 1/4/129 contexts and concurrent wrap stress; real
EP8 correctness; then matched unprofiled timings and traces on the same nodes.
A failure returns to the isolated candidate; it cannot invalidate or replace
the preserved baseline passes. No speedup or bandwidth claim for this candidate.

## Queued-test audit and exact comparison safeguards — 2026-10-27, 11:04 UTC

Job **3765998** remains pending the normal-partition group node limit; no GPU
result is inferred from this wait. The preceding goal turn made concrete
progress (all-nine-gate evidence, queued integration/performance/build work).

Pre-execution review found two harness problems, corrected before admission:

- The two-distinct-destination routing generator cannot realize EP8 skew 8:
  each rank receives at most every source token, so its maximum max/mean skew
  is EP/2 = 4. The request now uses `skew2` and `skew4`. The real argument
  parser also needed those choices added; a CPU-only sequence check now
  executes the harness's actual parser block and verifies all 14 requests'
  dependencies and routing limits.
- An explicit `hot_rank` route sends every token to rank zero's unique top-k
  experts, leaving seven receivers empty. The independent reference now
  reshapes with an explicit row width, since `reshape(0,-1)` cannot infer the
  zero-length tensor dimension. This adds a real empty-receiver GPU test;
  it does not claim that test has passed yet.

The SGLang test now records input, route and weight hashes for **every** case,
plus deployed DeepEP source, native extension, NCCL, adapter/test source,
node/job and CPU placement identities. Hashing and independent-reference
communication happen outside the measured wrappers. `compare_sglang.py` refuses
to compute speedups unless both runs pass warmed timing qualification and
all eight ranks match these identities and case hashes. Four pairing tests,
five timing-summary tests, twenty gate tests and two routing tests pass locally.

The pending-held job's requests were updated atomically, with prior v2/v3
requests/manifests preserved. Its current snapshot is
**`gate-20261027-1106`** (58 backend hashes verified remotely); exact schedule:
`results/deepep_direct_10_26/tenhour/followup-20261027-1053/sequence-v4.json`.
The immutable earlier snapshots remain intact. The clean native-build timeout
is now 600 seconds within its 900-second enclosing gate, reserving time for
import and the requested EP8 rerun. These are prepared corrections, not new
hardware passes.

### Next performance experiment: command publication and batching

Static source inspection identifies a concrete candidate bottleneck, not yet
a measured attribution. Pinned `impls/hybrid_dispatch.cuh` issues per-token
`gin.put(... ncclGinOptFlagsAggregateRequests)` and later updates channel tails.
`impls/hybrid_combine.cuh` also marks non-final chunk requests for aggregation.
NCCL's existing GDAKI implementation translates this hint to
`DOCA_GPUNETIO_VERBS_GPU_CODE_OPT_SKIP_DB_RINGING`. Our initial
`device/gin_cxi.cuh` ignores that optimization hint, and `cxi_primitives.cuh`
publishes and waits for NIC queue consumption after **every** command.
It additionally completes prior transfers before signaling. These choices
provide conservative semantics but may limit a stream of small token puts.

The installed CSCS `cxi_prov_hw.h` (libcxi 1.7.0; SHA256
`7e4d3394f4f46e1b4718cc3f70cd689b283c868e30d4c6a40cc5f714bb510122`)
documents the appropriate bounded ring-credit calculation: reserve the first
eight 32-byte units for status and one extra 64-byte slot to prevent overwrite;
update cached read pointers when credits run low. A future experiment should
first replace per-command consumption waits with bounded credit checks while
retaining doorbells and completion/signaling semantics. Only after that gate
passes should it defer doorbells for aggregation hints, always publishing before
flush/signal, queue pressure, or an unaggregated operation. Do not equate queue
consumption with source-buffer completion, or simply delete synchronization.

Keep variants in new immutable NCCL/header/plugin prefixes and rerun raw/public
GIN, concurrency/wrap, source-reuse, full EP8 and matched timing gates. The
pinned JIT cache hashes DeepEP headers but not external NCCL header contents;
the NCCL include path is in its compiler signature. Therefore a new immutable
include prefix and fresh cache are required for a device-header experiment.
No queue-policy change has been applied to the tested backend or queued run.

## Pending sequence expanded for matched SGLang and clean rebuild — 2026-10-27, 10:58 UTC

While job **3765998** was authoritatively PENDING, it was held, checked again
as PENDING/JobHeldUser, and its unstarted sequence was replaced atomically.
The original requests and manifest are retained as `requests-v1` and
`sequence-manifest-v1.json`. The job was then released. This did not restart a
running test or change any earlier immutable snapshot.

The new immutable source is **`gate-20261027-1058`**, with all 54 backend hashes
checked remotely before release. The allocation requests at most **60 minutes**
with a **20-minute** backfill minimum. Actual granted time is still enforced;
later stages may be refused if the allocation cannot accommodate their timeout.

The 14 stages now include paired direct/proxy SGLang timings for each of the
three geometries, using the same adapter and synthetic inputs; the routing,
padding, profiling, proxy-repeat and context-capacity gates; then public GIN
against the clean reconstructed NCCL prefix and a clean native DeepEP build
on each node followed by full-size EP8 correctness for all three geometries.
The exact request list is in local
`results/deepep_direct_10_26/tenhour/followup-20261027-1053/sequence-v2.json`.

The SGLang proxy control is explicitly opt-in and selects type 2. Direct tests
still require type 6 and reject fallback. Gate evidence and timing CSV rows
carry transport/type labels, so a proxy success cannot count as direct-GIN
evidence. Twenty validator tests and five timing-summary tests pass, including
proxy mislabel rejection. These new proxy-adapter changes remain GPU-unqualified.

The clean build uses baseline DeepEP archive SHA256
`57e3c4601a1e37e7d80abcdbe72f947401f9a7cfdf6034072267eb83c6bf404d`
and pinned fmt archive SHA256
`eddee710df7126bb543e97c84d726030ed097202c78bccf3310c796d2646a89f`.
Both are checked before extraction; the exported DeepEP patch and changed-file
hashes are checked before compilation. Builds go into new per-node paths and
do not install packages globally. Clean build/import remains a separate result
from subsequent all-rank EP correctness.

The current scheduling constraint is group node availability in normal.
Debug already has another user's-session workload running and another queued;
neither was modified. No additional competing allocation was submitted.

## All nine integration gates passed; expanded run queued — 2026-10-27, 10:54 UTC

Job **3765839 COMPLETED, exit 0:0, 11m50s**. All nine requests were collected
and independently revalidated locally. In addition to the standalone direct
and proxy results below, SGLang now passes actual scatter/gather at 4096/GPU
for V4Flash, Qwen3 and MiniMax. V4Flash also passes the real SGLang DeepGEMM
expert runner at 32 and 4096 tokens, BF16 and FP8, on all eight ranks. That
expert test uses FFN width 128 with analytic diagonal weights; it does not
establish full-model compute performance. All current SGLang timings are
explicitly **CORRECTNESS_ONLY**, since these were three-round cold/debug tests.

Job **3765998** is submitted on normal, two nodes, 45-minute maximum and
30-minute minimum, with immutable snapshot `gate-20261027-1053`; pending Priority
at this checkpoint. It was held during request publication and released only
after all 52 backend file hashes were verified. Dependency on 3765839 prevents
overlapping these allocations. The sequence is:

1. V4Flash actual expert test with an independent exact dispatch reference.
2. Qwen3, MiniMax and V4Flash SGLang wrapper measurements: 10 warmups, 50 timed
   iterations, BF16/FP8, 4096/GPU, actual scatter/gather.
3. Standalone three-geometry local/remote/skew2/skew8 correctness matrix,
   three seeds; separate 127/129-token padding-boundary cases.
4. Standalone direct performance repeat plus separate all-rank CUDA traces;
   matching proxy repeat on the same allocation.
5. Missing public-GIN context counts 2/8/16/32/64 with reset/reuse, then stop.

New exact SGLang validation checks source IDs, raw BF16/FP8 bytes, FP32 scales,
local expert IDs, weights and padded counts against independent NCCL all-to-all,
outside dispatch/combine timers. The new gate rejects missing exact-reference
evidence. Nineteen gate regression tests and four timing-summary tests pass.
These strengthened checks are prepared, not yet GPU-qualified.

The expert test entered the image's broad DeepGEMM precompilation sweep, but
eventually passed within its watchdog. The next snapshot uses the image's
supported `SGLANG_JIT_DEEPGEMM_PRECOMPILE=0` setting: actual kernels still JIT,
unused shapes are not precompiled, and the cache is private to this job/node.
A barrier outside the combine timer keeps unequal cold expert-compilation
times from becoming a direct-network timeout.

First-run useful activation bandwidth remains below nominal link capacity:
direct fresh dispatch is approximately 4.87/12.54/5.25 GB/s for
V4Flash/Qwen3/MiniMax; direct combine is 7.41/7.43/7.51 GB/s. These are useful
payload rates from validated latency, not physical MAC rates. For example,
V4Flash direct fresh-dispatch TX MAC windows on node nid006249 show about
5.48–5.50 GB/s per NIC, around 22% of nominal 25 GB/s, including protocol bytes
and iteration gaps. Thus CPU-free correctness and a proxy speedup do **not**
establish link saturation. Profiling and controlled queue/flush changes remain.

Clean rebuild preparation now includes baseline DeepEP and its exact fmt
submodule archive (`a4c7e17133ee9cb6a2f45545f6e974dd3c393efa`), recorded hashes,
and `backend/tools/build_reconstructed_deepep.sh`. It builds in a new private
prefix without pip installation and leaves runtime checks enabled. Only shell
syntax has been checked so far; native build/import and subsequent GPU rerun
remain unexecuted. This later script is not in the queued immutable snapshot.

Remaining plan gaps include wider routing/stress coverage, warmed SGLang
measurements and matched proxy control at that same dispatcher boundary,
profiling/optimization, repeated allocations, full clean rebuild/rerun,
and fatal-error cleanup. No complete P11–P14 or production-support claim.

## Verified milestone and remaining work — 2026-10-27, 10:49 UTC

This checkpoint supersedes older status statements below. Final target remains
pinned DeepEP `bd1e1669`, direct GPU-initiated CXI networking on two GH200 nodes,
EP8 at 4096 tokens/GPU, SGLang integration, and validated communication performance.

Job **3765839** is running on `nid006249,nid006255`. Its completed gates are:

- `01-ep-small`: PASS, eight ranks, V4Flash geometry, 128/512 tokens, BF16/FP8.
- `02-ep-4096-mixed`: PASS, eight ranks, V4Flash, 4096/GPU, FP8, mixed routing.
- `03-ep-4096-direct`: PASS, eight ranks, all three geometries, 4096/GPU,
  uniform routing, seeds 1/2/3, private direct CXI GIN type 6.
- `04-ep-4096-proxy`: PASS, the matching type-2 OFI/CXI proxy control.
- `05-sglang-dispatcher`: PASS, actual SGLang dispatcher, V4Flash, 32 tokens,
  BF16/FP8, three rounds, all eight ranks.
- `06-sglang-permute-4096`: PASS, actual SGLang dispatcher and scatter/gather,
  V4Flash, 4096/GPU, BF16/FP8, three rounds, all eight ranks.
- `07-sglang-real-experts`: started; no result claimed at this checkpoint.
  Qwen3/MiniMax SGLang gates remain subsequent requests.

The direct backend declares `needsProxyProgress=0` and has no CPU progress
callback. GPU code posts NIC work and observes completion/signals. Host setup,
kernel launches and normal synchronization still exist. This is a private CXI
backend, **not** NVIDIA GDAKI/type 3 or an upstream-supported release.

First matched standalone timing results (milliseconds):

| Geometry | Proxy fresh dispatch | Direct fresh dispatch | Proxy combine | Direct combine | Measured cycle speedup |
|---|---:|---:|---:|---:|---:|
| V4Flash | 6.734 | 3.407 | 6.546 | 4.477 | 1.68x |
| Qwen3-235B | 6.614 | 1.335 | 6.600 | 4.506 | 2.25x |
| MiniMax2.7 | 6.804 | 2.390 | 6.650 | 3.346 | 2.35x |

Each entry is the median across three seeds of per-seed median rank-max CUDA
event latency, with 10 warmups and 50 samples. Cycle speedup uses the separately
timed fresh dispatch/combine cycle, not the sum of the table columns. All eight
ranks' source/script hashes, geometry, input/route hashes, SM/QP settings,
warmups/iterations and node placement were checked for matching. Each transport
has 72 passing correctness records and 14,400 operation timing samples.

These are synthetic geometry communication tests, excluding expert GEMM and
FP8 quantization time; they are not full-model inference or TTFT. The comparison
demonstrates improvement over this specific proxy configuration, not over an
independently tuned best proxy implementation. NIC saturation is not established.

Remaining: finish actual-expert and other-geometry SGLang gates; collect warmed
SGLang wrapper timings; profile queue/completion/signal serialization and tune
batching; repeat performance across allocations and inspect NIC counters; finish
clean DeepEP/native build and GPU qualification with the reconstructed NCCL
prefix; qualify longer stress and fatal-error teardown. Source reconstruction
and clean NCCL compilation passed, but the full reproducible GPU package has
not yet passed. Functional direct DeepEP EP8 is achieved for the tested matrix;
the final integrated, optimized and reproducible target remains incomplete.

## Recovery and bounds gates passed — 2026-10-27, 10:30 UTC

Job **3764744** completed on `nid005422,nid006672`. Both executed requests
were independently revalidated after collection:

- `01-recovery-self`: PASS on **8/8 ranks**, 1/4 contexts, invalid-version
  rejection, delayed-peer timeout followed by successful recovery/flush,
  self-signaling, reset/reuse and teardown.
- `02-bounds`: PASS on **8/8 ranks**, all five offset/length/peer rejection
  cases, without posting invalid NIC commands, followed by normal teardown.
- `03-ep-small`: **NOT RUN**. The controller refused admission for time;
  there was no DeepEP kernel/correctness failure.

The refusal exposed a scheduling-wrapper bug: exported `SLURM_JOB_END_TIME`
reflected roughly five minutes, while the authoritative running job record
showed a 20-minute allocation. The controller now queries `scontrol ... --json`
at startup and before each request; it uses the exported timestamp only on
query failure, and admits no work when neither deadline is known. Five local
regression tests pass, including stale exports, shortened actual allocations,
terminal jobs and conservative fallback. This fix does not extend allocations.

The debug resubmission was rejected by `QOSMaxSubmitJobPerUserLimit`. Other
workloads remain untouched; the continuation uses the authorized normal
partition instead. New job **3765839** uses two nodes, a 30-minute maximum
and 10-minute backfill minimum, with snapshot `gate-20261027-1035`. Its
sequence starts at real DeepEP EP8 and includes
conditional SGLang dispatcher, scatter/gather and actual-expert smoke tests.
Fatal GPU/NIC-error teardown remains unqualified; the passing negative tests
above do not establish transparent failover or production readiness.

## Source reproducibility preparation — 2026-10-27

The exported private DeepEP and NCCL patches were applied to fresh temporary
checkouts at their pinned commits. Every changed/new file matched the worktree
hashes. Bundle: `results/deepep_direct_10_26/source-bundles/20261027-preintegration-v2/`.
This is source reconstruction evidence, **not** a clean GPU rebuild/rerun pass.

The first export detected that the device copy of `cxi_gin_abi.h` lacked two
compile-time size assertions already present in the host copy. The structures
were identical; both copies now include the assertions. The failed packaging
attempt is retained with `FAILED.json`. Installed tested release
`cxi-20261026-201823` and queued GPU-test snapshots remain unchanged.

A new bounded build script reconstructs pinned NCCL from the baseline archive
and exported patch, verifies source hashes, and builds into a new private prefix.
The clean build is staged under remote `tenhour/repro-nccl-20261027`, with a
30-minute process timeout and four build workers. The **clean NCCL build passed
at 10:35:20 UTC**. Logs and binary hashes are collected under
`results/deepep_direct_10_26/tenhour/rebuilds/repro-nccl-20261027/`.
A clean DeepEP build/integration rerun and GPU qualification remain required;
**P14 is not complete**. The original tested NCCL release is still used by the
current EP/SGLang sequence.

The later local launch script accepts an explicit reconstructed NCCL source
path as well as the installed prefix. Its test helper is now included directly
in `backend/tests/common.py` with the same hash as the previously tested helper.
These later packaging changes do not modify the immutable running/queued snapshots.

## Active continuation — 2026-10-27, 10:15 UTC

The platform goal is active again. Job 3764744 remains pending Priority at
this checkpoint; no new GPU pass is inferred from its submission.

Source audit found that `EP_BUFFER_DEBUG=1` causes a C++ print on every hybrid
dispatch (`csrc/elastic/buffer.hpp`). The matched timing requests 05 and 06 now
select `CXI_EP_DEBUG=0`, which unsets that flag, using the same new immutable
snapshot `gate-20261027-1015`. Earlier correctness requests keep debug enabled.
This avoids treating debug I/O overhead as a network-performance property.

The actual container's MoeRunnerConfig and BF16/FP8 DeepGEMM code were inspected.
An optional `CXI_SGLANG_GEMM=1` smoke now invokes the real SGLang scatter, gated
expert runner and gather, with sparse diagonal weights and an analytic reference.
The FFN width is deliberately 128; communication retains the requested hidden
width/expert geometry. It qualifies operator integration only, not real-model
compute time or TTFT. Syntax checks passed; **GPU execution is still pending**.

The SGLang harness can additionally initialize the distributed group before
importing DeepEP (`CXI_SGLANG_IMPORT_AFTER_INIT=1`), exercising the runtime guard
with actual loaded transport plugins. It records loaded-library paths. A new
SGLang gate checks all eight ranks, exact dtype/token/iteration coverage, selected
backend/geometry, and whether real scatter/gather or expert kernels were used.
Eighteen local validator tests pass, including missing cases, wrong integration
scope, and nonfinite error rejection. No SGLang requests have been submitted
before standalone DeepEP correctness is established.

## Continuation — 2026-10-27, 09:40 UTC

SSH authentication is restored after certificate renewal. Job **3758590**
completed (exit 0) on `nid006578,nid006647`. Retrieved and checked every rank's
JSON/evidence: **8/8 ranks × 20 lifecycle cycles**, each with two 14-round
payload/signaling epochs, reset/reuse and normal teardown; zero reported errors.
This is public GIN qualification, not a DeepEP performance result.

New two-node debug job **3764744** is submitted with a 20-minute maximum and
5-minute backfill minimum. Its first immutable snapshot is
`gate-20261027-0940`; request `01-recovery-self` tests invalid-version rejection,
delayed-peer timeout/recovery, self-signaling and reset. At submission it was
pending Priority. Bounds rejection and real DeepEP EP8 remain dependent gates.

A separate local integration fix narrows DeepEP's runtime guard to actual
`libnccl.so[.version]` files, excluding `libnccl-net.so` and GIN plugins. The
original pinned function reproduces a false duplicate-runtime error with a
plugin loaded; the private fix passes five regression cases, including rejecting
two runtimes and a binary mismatch. `EP_SUPPRESS_NCCL_CHECK` stays zero. This is
not yet a SGLang GPU validation. Original DeepEP and prior snapshots stay intact.

### Bounded continuation sequence for job 3764744

The queued allocation now has explicit dependent requests. The controller
checks both node completion markers and all eight rank records. It validates
context rounds, reset/self-signal evidence, expected timeout recovery, teardown,
and the exact EP correctness matrix before permitting the next request. Any
failure, failed evidence check, or insufficient remaining time ends the sequence.
The final request releases the allocation; it does not submit another job.

| Order | Target | Workload |
|---|---|---|
| 01 | Public GIN recovery and self-signal | 1/4 contexts, reset, invalid version, delayed peer |
| 02 | Bounds rejection | Five invalid-offset/length/peer cases; no invalid NIC command |
| 03 | First real DeepEP direct EP8 | V4Flash geometry, 128/512 tokens/GPU, BF16 and FP8, mixed routing |
| 04 | Required token capacity | V4Flash geometry, 4096/GPU, FP8 dispatch/BF16 combine, mixed routing |
| 05 | Direct performance candidates | Three geometries, 4096/GPU, uniform routing, seeds 1/2/3, 10 warmups/50 samples/50 NIC-window iterations |
| 06 | Matched proxy control | Same workload, seeds, SM/QP settings and private DeepEP source; type 2 instead of direct type 6 |

Steps 02–06 use immutable `gate-20261027-0948` and the separate
`DeepEP-runtimeguard-20261027` deployment where relevant. The previous 01 source
snapshot remains unchanged. The driver and validator hashes are recorded in
`leases/3764744/sequence-manifest.json`. Fourteen local gate-validation tests
passed, including rejection of incomplete ranks, proxy fallback, GPU errors,
missing recovery/reset evidence, failed teardown, and incomplete EP matrices.
The validator also accepted the actual eight-rank, twenty-cycle lifecycle data
from 3758590. These are controller checks, not new GPU results.

The controller is a bounded execution/validation script, not an autonomous
code-repair agent. SGLang integration is prepared but remains a subsequent gate
after standalone EP correctness. The platform goal tracker still reports
`usageLimited`; submitting this finite cluster sequence does not reset that state.

## Resume check — 2026-10-27

The user requested continuation. The goal tracker still reports `usageLimited`
(779,538 recorded tokens, 5,280 seconds active time); it does not expose account
quota remaining or a reset time. The original ten-hour wall-clock window has
elapsed. This continuation request is recorded without claiming that the
background goal has resumed or changing the platform-controlled limit state.

SSH currently fails at `ela.cscs.ch` with `Permission denied (publickey)`.
The configured CSCS certificate expired at **09:19:13 UTC / 10:19:13 CET** on
27 October. User renewal is needed to retrieve remote evidence. Job **3758590**
was previously pending; its current state is **unknown**, not assumed failed
or completed. No replacement job was submitted during this check.

Local Python parsing and shell syntax checks passed. These checks do not
qualify GPU correctness. Resume by collecting job 3758590's accounting and
lifecycle outputs, then continue the ordered public-API, bounds, DeepEP, and
SGLang gates. Preserve all existing snapshots and passing job 3758296 evidence.
See `results/deepep_direct_10_26/tenhour/resume-check-20261027.json`.

**Current result (20:50 UTC):** the experimental direct CXI backend now passes
public NCCL GIN payload/signaling tests on **8/8 GH200 GPUs**, including 129
contexts/GPU, concurrent producers, and reset/reuse (job **3758296**).
It uses private backend type 6 with `needsProxyProgress=0` and no host progress
callback. **CPU-free DeepEP EP8 and SGLang have not yet passed or been benchmarked.**
Lifecycle/failure qualification and real DeepEP integration are next, under
job **3758590**. Earlier raw-CXI and proxy controls are retained below.

## Active implementation plan — direct CXI GIN for DeepEP EP8

This section is the actionable continuation plan. The S0–S9 table and dated
execution entries below describe the original investigation. Follow P01–P14
in order. Implementation is now **IN PROGRESS** in the ten-hour run recorded
below. Compilation, hardware correctness, and performance are separate gates;
a code change or submitted job does not count as a passing experiment.

**Success target:** one eight-rank DeepEP communicator, two Clariden GH200
nodes with four GPUs each, 4096 input tokens per GPU (16,384/node;
32,768/EP8 group), FP8 fresh dispatch and BF16 combine. All ranks participate
in the same operation. NIC posting, completion and remote signal delivery must
progress without per-transfer CPU assistance. Host setup, kernel launches,
ordinary CUDA synchronization and final teardown are permitted. Correctness
and CPU-free progress are required before interpreting performance.

**Implementation choice:** keep DeepEP bd1e1669; build a separate public-libcxi
CXI host/device GIN backend and an isolated, matching NCCL v2.32.3-1 fork.
Use the current OFI/CXI proxy as a reference and control. Missing CLIC KI
headers do not block this chosen route. The working raw probes establish
feasibility only on the tested nodes; verify resources on each new allocation.
Do not modify the original serving installation or repurpose GDAKI/type 3.

### Completed prerequisites to carry forward

| Evidence | Status | What it establishes |
|---|---|---|
| 3754974: proxy/auto vs forced type 3 | PASS diagnostic | Proxy works; installed direct GDAKI backend is unavailable on these CXI nodes |
| 3754974: isolated portable DeepEP barrier | PASS, limited | One 4096-token/GPU proxy EP8 correctness case; broader coverage still required |
| 3755312: GPU queue, HBM puts, CT completion, remote adds | PASS, 8/8 GPUs | Raw public-libcxi primitives without in-kernel CPU network progress |
| 3756020: changing payload, source reuse, READY/ACK ordering | PASS, 8/8 GPUs | Conservative sequential protocol; 128 rounds/GPU |
| P01 rebuilt unmodified NCCL control | PASS, 3758279 | 8/8 proxy create/destroy and 4096-token FP8 dispatch/BF16 combine correctness |
| NCCL CXI public API | PASS, 3758296 requests 03–05 | 8/8 ranks; 1/4/129 contexts; GPU payload/signal/counter operations and concurrent producers; lifecycle/fault coverage incomplete |
| CPU-free DeepEP EP8 correctness/performance | NOT RUN | P10–P12 below |

### Planned source layout and patch ownership

The following layout describes the deliverables. Host/plugin/device code and
initial probes now exist; stress/lifecycle harnesses remain planned unless
explicitly recorded below. Existing probe snapshots stay immutable.

```text
tools/cxi_gin/nccl-cxi-dev/             # full isolated NCCL source checkout
tools/cxi_gin/backend/
  include/cxi_gin_abi.h                # versioned host/device structures
  host/cxi_resources.cc                # libcxi resource and MR ownership
  host/gin_plugin.cc                   # NCCL GIN host callbacks
  device/gin_cxi.cuh                   # GPU operations, queues, completion
  tests/cxi_resource_probe.cc
  tests/cxi_dynamic_probe.cu
  tests/gin_smoke.cu
  tests/gin_cxi_stress.cu
  tests/gin_cxi_lifecycle.cc
  tools/build.sh                      # isolated prefixes, source manifest
  tools/run_gate.sbatch                # bounded Clariden allocation
  tools/collect_gate.py                # rank results and PASS classification
```

DeepEP changes belong in the existing isolated `DeepEP-cxi-dev` worktree.
The NCCL fork must install matching CXI device headers and link the private
host library; our current `reference/nccl-v2.32.3-1/` is only a source reference,
not a buildable full checkout. Remote builds/results use a new private prefix
under `/iopsstor/scratch/cscs/zyu/deepep-direct-20261026/`; assign a distinct
build ID rather than replacing the tested binaries or source snapshots.

### P01 — Freeze the build inputs and reproduce the control

**Target:** make every later result attributable to a known binary/header pair.

- Prepare the isolated NCCL checkout at v2.32.3-1, record its full commit and
  required submodule revisions, and preserve the clean DeepEP bd1e1669 control.
- Implement the build/manifest harness. Record CUDA, NCCL headers and loaded
  library paths/hashes, plugin ABI, libcxi headers/library, compiler flags,
  GPU/NIC topology, driver identity and launch environment. Do not infer the
  loaded runtime solely from a package version string.
- Build unmodified pinned NCCL first, then rerun communicator creation and
  one proxy EP8 correctness case in the isolated environment.
- **Pass:** all eight ranks report the intended paths/versions, proxy selection
  and correct results with clean teardown. **On failure:** resolve toolchain,
  dependency or dynamic-linking differences before adding CXI code.

### P02 — Specify the ABI and the required operation contract

**Target:** agree what host code prepares and GPU code consumes before coding
either side independently.

- Define `cxi_gin_abi.h`: version, structure sizes, per-context queue ownership,
  completion sequence state, peer addressing, registered-window bounds and
  access metadata, indexed signals and optional public counters. Keep host-only
  owners separate from GPU-dereferenceable descriptors.
- Audit reachable DeepEP EP calls and list required operations: Put, relevant
  PutValue calls, VA/indexed signal adds and reads/resets, Flush and any reached
  FlushAsync/Wait variants. Treat Engram/Get as a separate scope. Unsupported
  calls must fail clearly; no successful no-op stubs.
- Specify strong/weak signal visibility, local completion/source reuse, queue
  capacity, sharing modes, abort behavior and callback lifetime. Distinguish
  NIC ACK counters from the public GIN per-operation counter contract.
- Reserve a private CXI type only after auditing the pinned NCCL enum/array
  bounds; the name/number is experimental, not upstream-assigned.
- **Pass:** host and CUDA compilation agree on ABI sizes/offsets; every required
  operation has a test and every advertised capability has an implementation
  plan. **On failure:** resolve the semantic gap rather than copying GDAKI flags.

### P03 — Extract reusable CXI host resources

**Target:** replace probe-specific allocation with owned, reusable resources.

- Factor `gpu_order_host.c` into `cxi_resources.cc`: allocated Slurm service/VNI,
  GPU/NIC association, LNI/CP/domain, command/target queues, PTEs, HBM DMA-BUF
  registration, CUDA mappings and completion storage. Preserve the passing
  IoMemory mapping fallback and explicit error reporting.
- Implement partial-construction cleanup and reverse-order teardown. Design
  peer/MR serialization for plugin bootstrap; shared-file exchange is allowed
  only in the raw test harness, not as the finished plugin protocol.
- Run `cxi_resource_probe` and rerun the original NOOP/HBM/counter/atomic/order
  tests through the factored resource layer.
- **Pass:** all eight GPUs retain the previous results and repeated
  create/register/deregister/destroy succeeds. **On failure:** compare resource
  flags, mappings and descriptors against the successful source snapshots.

### P04 — Generalize the GPU operations beyond fixed templates

**Target:** one producer/context supports runtime peer, address and length.

- Implement GPU command construction in `gin_cxi.cuh` using CXI descriptors,
  window offsets and completion state; remove assumptions of 64-byte payloads,
  fixed addresses or one hard-coded peer. Split transfers at documented NIC
  limits, and check offset/length overflow and region boundaries.
- First use conservative completion/order rules. Implement puts, remote adds,
  source-safe flush and bounded waits before adding batching optimizations.
- `cxi_dynamic_probe` tests 0-byte API behavior, 1/8/64/128 B, 4 KiB, 64 KiB,
  1 MiB and 16 MiB transfers, valid nonzero/unaligned offsets where supported,
  multiple registered windows and bidirectional traffic. Add guard regions,
  changing patterns, source poisoning, and enough operations to wrap queues.
- **Pass:** exact payload/guard validation and correct signals/completions;
  unsupported inputs reject explicitly. **On failure:** distinguish command
  consumption from transfer completion, then inspect encoding, MR bounds,
  memory ordering and credit handling separately.

### P05 — Implement the NCCL CXI host plugin

**Target:** NCCL can create valid CXI host/device handles through its callbacks.

- Implement `cxi_plugin.cc` against the pinned supported GIN ABI (prefer v14
  after checking the installed headers): init/devices/properties,
  listen/connect, create/destroy context, regMrSym/DmaBuf/deregistration,
  close/finalize and error reporting as required by that ABI.
- Replace raw-test shared-file peer exchange with the plugin bootstrap and
  exchange all peer/window information needed by GPU operations. Honor rail
  connectivity and requested rank stride; do not assume world rank equals a
  two-node peer index.
- Return matching backend type/version and device descriptors. Set
  `needsProxyProgress=0` only for an implementation that genuinely requires
  no host data progress. Include diagnostic counters for accidental host
  submission/progress. Advertise only validated capabilities.
- **Pass:** host callback harness exercises connection, multiple windows,
  context ownership and cleanup with consistent peer metadata. **On failure:**
  debug bootstrap/ABI/registration without launching DeepEP kernels.

### P06 — Wire CXI into the isolated NCCL host and device builds

**Target:** a device communicator explicitly selects CXI and cannot silently
fall back to the proxy.

- Patch backend type definitions, capability/type bounds and version mapping;
  host sites include `src/gin/gin_host.cc` and `src/plugin/gin.cc`.
- Add the CXI enable/mask/dispatch entry in `gin_device_common.h`, include the
  new backend in `gin_device_api.h`, and provide the required specializations.
  Install the matching ABI header. Audit all type-indexed tables, not just the
  visible switch. Preserve existing proxy behavior.
- Build the library, plugin and CUDA probe together. Extend the current
  `gin_probe.cu` to request the exact experimental CXI backend and fail if any
  selected connection is another type; report `needsProxyProgress` through
  plugin diagnostics. Record actual runtime paths on every rank.
- **Pass:** eight ranks create/destroy the intended device communicator with
  matching versions. Missing plugin, incompatible version and unsupported
  device tests fail clearly rather than selecting proxy. **On failure:**
  inspect loader paths, plugin exports, type/version tables and device masks.

### P07 — Prove one-context GIN operations without DeepEP

**Target:** the public NCCL GIN API executes the validated CXI protocol.

- Implement `gin_cxi_probe.cu`: initially one GPU per node, then four same-rail
  GPU pairs. Call public Put, signals, wait/read and Flush, using registered
  windows, changing data and immediate source reuse. Verify both VA and indexed
  signals and correct per-context signal indexing.
- Cover payload-only, signal-only, bundled put+signal and prior puts followed
  by a strong signal. Test reset/reuse without racing live updates. Test any
  required asynchronous flush/request lifetime through the public API.
- Disable required host network progress in the test configuration; verify
  plugin submission/progress counters remain zero during kernels. Trace a
  representative run to inspect host activity. CPU utilization alone is not
  proof, and setup/bootstrap traffic is outside the measured interval.
- **Pass:** all public-API cases pass exact references on all eight GPUs with
  CPU-free progress and clean teardown. **On failure:** run the same case through
  the raw module to isolate NCCL handle/offset translation from NIC behavior.

### P08 — Scale contexts, producers, signals and resource usage

**Target:** meet the concurrency requested by the actual DeepEP configuration.

- `gin_cxi_stress.cu` sweeps 1, 2, 4, 8, 16, 32, 64 and 129 contexts; exercise
  the relevant THREAD/CTA/GPU sharing modes, concurrent CTAs and delayed
  producers/consumers. Test queue wraparound and backpressure at depth 1024.
- Exercise multiwriter atomic adds, independent contexts, exact completion
  accounting and signal reuse after quiescence. Use both directions on all four
  rails. Preserve per-context ordering without imposing an accidental global
  serialization point in the final performance path.
- Count actual CXI resources before allocation. If one hardware queue per
  logical context is infeasible, implement and separately validate multiplexing;
  do not silently lower DeepEP's 129-context configuration and call it matched.
- **Pass:** supported capacity reaches the intended configuration with exact
  results, bounded progress and no CPU assist. **On failure:** log reservation,
  publication, consumption and completion sequences per context; identify
  resource exhaustion, a queue hole, credit deadlock or a signal race.

### P09 — Validate lifecycle and bounded failures

**Target:** repeated operations and failures leave no live unsafe resources.

- Add `gin_cxi_lifecycle.cc`: at least 20 create/register/transfer/deregister/
  destroy cycles, repeated device communicators and multiple windows. Log every
  cleanup result and resource counts where exposed.
- Inject software-level invalid version/offset and a delayed peer; verify
  timeout/abort behavior without manipulating drivers or physical links.
  Keep registered memory alive until operations quiesce or the context is
  safely aborted. Distinguish an expected negative result from an accidental
  crash or an allocation killed by its walltime.
- **Pass:** successful cycles return cleanly; negative cases report the intended
  stage and all ranks exit within the watchdog. **On failure:** separate protocol
  quiescence from resource-release ordering. No skip-destroy workaround.

### P10 — Integrate the portable DeepEP build and a small EP8 case

**Target:** a real eight-rank DeepEP dispatch/combine uses the direct CXI backend.

- Apply the existing bounded waitSignal/readSignal barrier patch in
  `DeepEP-cxi-dev`. Update backend selection/diagnostics as needed to request
  and assert CXI explicitly. Keep token routing/packing kernels unchanged
  unless a reproduced correctness issue requires a separate patch.
- Build/JIT against the private matching NCCL headers/runtime with a fresh
  cache. Start with 128 and 512 tokens/GPU, deterministic mixed local/remote
  routes, FP8 dispatch and BF16 combine. Validate payloads, expert/source IDs,
  counts, weights and combine reduction against independent references.
- Use the planned DeepEP contexts; a reduced-context diagnostic must be labelled
  separately and cannot satisfy the final gate. All eight ranks run in one group.
- **Pass:** repeated fresh dispatch/combine, barriers and teardown pass with
  exact backend identity and no required host network progress. **On failure:**
  separate metadata notification, payload transfer, signal wait and reduction;
  reduce only the failing case while preserving its reproducer.

### P11 — Validate the full 4096-token/GPU experiment matrix

**Target:** CPU-free correctness for the same workload geometry as the baseline.

- Reuse the recorded model/routing metadata from `tools/ep8_demo`, preserving
  seeds and route hashes. Current harness tuples `(hidden, experts, top-k)` are
  v4flash `(4096,256,6)`, qwen3 `(4096,128,8)`, minimax `(3072,256,8)`;
  these are benchmark configurations, not a new claim about every model release.
  Resolve any mismatch with recorded source metadata before comparison.
- Test uniform, skewed, local-only and remote-heavy routes, empty destination
  buckets, padding boundaries and multiple seeds. Keep fresh routing/dispatch
  primary; cached-handle dispatch is a separately labelled diagnostic. Verify
  repeated operations, not just the first call.
- **Pass:** every required rank/case has a correctness record and all jobs exit
  cleanly, with no proxy fallback. **On failure:** retain the smallest failing
  model/route/seed and exact source snapshot; do not proceed to a performance claim.

### P12 — Measure matched performance and then optimize

**Target:** trustworthy direct-vs-proxy dispatch/combine measurements.

- Keep the historical proxy results, and rerun a matched proxy control using
  the same isolated NCCL/DeepEP portability build wherever supported. Pin model
  geometry, route/seed, payload format, padding, SM count, contexts and GPU/NIC
  placement. Record actual DeepEP SM/QP values; `--sms` currently controls UCCL.
- Use at least 10 warmups, 50 measured iterations and three independent runs
  per primary case within bounded allocations. Record all-rank timings and a
  group critical-path statistic from aligned iterations, not an average of
  rank averages. Time fresh dispatch, combine and their full cycle separately.
- State whether quantization, layout/handle creation and synchronization are
  included. Match the existing scope, where quantization and expert GEMM are
  excluded, and report any expanded end-to-end scope separately.
- Collect isolated NIC TX/RX byte deltas and useful-payload counts; distinguish
  useful GB/s from physical link traffic and per-NIC from node totals. Keep
  instrumentation/profiling runs separate from unprofiled timing runs.
- **Pass:** publish latency distributions, correctness/CPU-free evidence and
  matched configuration, even if direct is slower. Then profile and tune command
  batching, doorbell frequency, credits and context mapping one change at a time.
  Do not require near-peak bandwidth as a correctness acceptance criterion.
- **On failure:** exclude invalid timing/counter windows and identify the scope
  or synchronization error before repeating them. A new correctness/progress
  failure returns to the relevant earlier gate; low throughput alone triggers
  profiling rather than a claim that direct GIN is unsupported.

### P13 — Integrate and verify the SGLang dispatcher

**Target:** SGLang uses the pinned DeepEP v2 direct-CXI implementation across
one eight-rank group, and dispatch/combine performance is measured through its
real dispatcher boundary.

- Inventory the SGLang source in the actual serving container and freeze its
  revision/files. The older local third_party tree is not proof of the container
  API. Build an isolated SGLang overlay/checkout; preserve existing serving runs.
- Audit its DeepEP v2 Buffer API and tensor/handle formats against bd1e1669
  ElasticBuffer. Adapt the dispatcher only where needed; do not silently replace
  the pinned DeepEP library with a different major API or a bundled v1 wheel.
- Add a distributed dispatcher integration test using actual SGLang dispatcher
  objects, routing metadata, FP8 scales and BF16 combine. Verify independent
  references at 4096 tokens/GPU and loaded DeepEP/NCCL/plugin identities on all
  ranks; enforce exact CXI backend selection with no CPU network progress.
- Measure fresh dispatch/combine at that boundary using matched proxy/direct
  inputs and report quantization/layout/synchronization scope. Where installed
  model/config resources permit, run a small two-node serving smoke and confirm
  the same dispatcher/backend logs. A dispatcher-only result must not be called
  a completed multi-model serving campaign or an end-to-end TTFT measurement.
- **Pass:** real SGLang dispatcher integration and cross-node correctness/perf
  evidence, with exact scope stated. **On failure:** isolate import/API/schema,
  quantization, routing and runtime-library differences from NIC behavior using
  the already-qualified standalone DeepEP case.

### P14 — Package the runnable implementation and reproducible evidence

**Target:** another session can rebuild and rerun the qualified EP8 path.

- Save ordered patch sets for DeepEP portability, NCCL integration and the CXI
  plugin; full revisions, build instructions, private runtime setup, bounded
  Slurm launcher, tests and per-gate artifacts. State supported node/driver/CXI
  combinations and remaining limitations.
- Rebuild in a clean private prefix and rerun the GIN smoke plus a full-size
  EP8 correctness case using only the documented procedure.
- **Pass:** independent clean rebuild/rerun succeeds and the support matrix
  clearly separates raw primitives, GIN integration, EP8 correctness and
  performance. PR preparation can follow; publication is a separate action.
- **On failure:** identify the missing dependency, environment assumption or
  undocumented artifact; fix the recipe and repeat the clean-prefix run before
  declaring the implementation reproducible.

### Debug-node execution and evidence rules

Use the proven two-node debug shape: account infra01, debug partition, four
GPUs/node, one launcher task/node spawning four GPU ranks. Derive new scripts
from the bounded `ordering/run.sbatch` harness. Prefer 10-minute allocations
and divide large matrices across jobs; check current site limits at submission.
Do not cancel or alter existing EP4 jobs. Compile on appropriate available
resources and use allocations for the hardware gates.

For each attempt, preserve a source snapshot, build/library manifest, Slurm
job and node identity, rank-to-GPU/NIC map, stdout/stderr, exit codes, operation
counters and machine-readable reference comparisons. Suggested record fields:
`gate`, `attempt`, `status`, `source_revision`, `job_id`, `nodes`, `backend_type`,
`backend_version`, `needs_proxy_progress`, `ranks_passed`, `ranks_expected`,
`failure_stage`, `artifact_dir`, `next_action`.

Use NOT_STARTED, READY, BUILD_PASS, SUBMITTED, RUNNING, PASS, FAIL or BLOCKED.
BUILD_PASS and Slurm COMPLETED are not substitutes for required rank-level
correctness. A backend-selection failure does not establish a hardware failure.
On failure: collect first, identify one cause, change one component, snapshot,
then rerun the failed gate and any affected prerequisites. Never automatically
resubmit identical failing code. Stop downstream gates when a prerequisite fails.

**Current action:** complete the P01 hardware control and qualify the new
P03–P07 implementation. Keep the original successful raw-probe sources
as the reference while factoring the reusable module.

## Scope and execution window

User authorized autonomous debugging on Clariden debug nodes while away for
two hours. Start: 14:27 UTC (15:27 Zurich); target checkpoint: 16:27 UTC
(17:27 Zurich). Baseline is DeepEP bd1e1669. No upstream migration. Target is
one EP8 group on two GH200 nodes, four GPUs each; eventual workload is 4096
tokens/GPU, FP8 dispatch and BF16 combine. CPU setup is allowed; per-transfer
CPU posting, completion draining or notification processing fails the CPU-free
target. A forced GDAKI initialization failure is diagnostic, not a direct-GIN
benchmark. Preserve original serving installations and queued/running jobs.

## Debugging steps and acceptance targets

| Step | Substeps | Target / pass evidence | Failure action |
|---|---|---|---|
| S0 Baseline and allocation | Record revisions, libraries, launch settings and debug QOS; isolate source/cache/output | Reproducible manifest; two nodes with four GH200 each | Preserve logs; wait for authorized debug slot |
| S1 Compute-node capability | Inventory CXI devices/drivers and mapped libraries; search bounded readable provider prefixes; check KI headers/API | Establish exact node/provider identity and whether FI_CXI_KI_OPS can be built/used | Name missing provider/driver component; do not infer global cluster absence |
| S2 NCCL selection | Fresh process groups with forced proxy (2), automatic (unset), forced GDAKI (3); query properties and request a device communicator | Record supported types and selected backend on all eight ranks, or precise failing initialization stage | Expected unsupported-direct failure is retained; never label fallback direct |
| S3 Portable DeepEP barrier | Build/use isolated bd1e1669 patch replacing private GDAKI signal access; compile against installed NCCL | Patch compiles; repeated EP8 correctness/barriers pass with existing proxy | Debug build/API issues in isolated copy; retain unchanged control |
| S4 Obtain direct CXI primitives | Inspect accessible public/current CLIC dependencies; probe KI endpoint setup, GPU queue/doorbell and counter mappings | Matching provider and node expose usable GPU resources | Continue source-level work; document external dependency if unavailable |
| S5 GPU-only progress | Small two-node puts, data-before-signal, source reuse, queue wraparound; disable CPU CQ drain | Sustained GPU progress with no host posting/progress and correct data | Instrument queue/credit/order failure; no EP benchmark before primitive gate |
| S6 NCCL CXI backend | Map required puts, indexed/VA signal adds, flush and context semantics to qualified primitives | Correct host/device backend identity and isolated communicator tests | Implement/test one primitive at a time; do not masquerade as mlx5 GDAKI |
| S7 EP8 correctness | Independent payload/combine references, all eight ranks, repeated construction/destruction | Correct dispatch/combine with verified direct backend and clean teardown | Preserve per-rank failures and narrow smallest reproducer |
| S8 Performance | Unprofiled 4096-token/GPU cases, same model geometry/routes as proxy baseline | Latencies, useful bytes and NIC counters with verified CPU-free status | No throughput claim if correctness/progress gates fail |
| S9 Report | Collect results, classify PASS/FAIL/BLOCKED/NOT_RUN, record patches and next action | Reviewable evidence and honest checkpoint by window end | Leave queued/running job status explicit |

Dependencies: S5 requires S4; S6 requires validated primitive semantics; S7/S8
require a working direct backend. S1–S3 and source audit can proceed while the
KI dependency is unresolved. Nsight proxy profiling is a separate existing job
and cannot establish direct-GIN support.

## Initial evidence

### Primitive test gates after usable direct CXI resources are available

- **S4a mapping:** queue allocation and CUDA doorbell mapping must succeed;
  no command execution is inferred. This probe is staged now.
- **S4b endpoint:** a matching KI provider or public libcxi setup must return
  valid device queue buffers, peer/MR descriptors and counter mappings. Reject
  provider/driver ABI mismatch; the public SDK route is a separate experiment.
- **S5a payload:** one GPU posts a put; the remote GPU checks a rank/sequence
  pattern. No CPU posts or polls after launch. Test both node directions.
- **S5b ordering:** publish readiness only after payload visibility; receiver
  verifies data immediately after the signal. Exercise release/acquire scopes.
- **S5c source reuse:** overwrite the source immediately after the backend's
  local-completion/flush promise; the receiver must retain the original data.
- **S5d signal semantics:** concurrent adds from multiple contexts and repeated
  reset/reuse must preserve the exact count. CLIC's per-peer absolute-value
  signal puts are not automatically equivalent to arbitrary GIN VA-signal adds.
- **S5e sustained progress:** exceed queue capacity repeatedly, with bounded
  timeouts and no CPU CQ drain. A short successful exchange is insufficient.
- **S5f lifecycle:** repeat registration, endpoint creation and teardown; do not
  use skip-destroy as a correctness workaround.
- **S6a integration:** expose only supported operations with explicit capability
  checks and matching host/device backend versions.
- **S6b EP mapping:** verify DeepEP's rail teams, four local NVLink peers,
  context mapping and remote indexed/VA signals before dispatch/combine.

These are acceptance tests to implement/run after S4b; they are NOT reported
as executed merely because the plan or a mapping probe exists.

- Existing runtime forces NCCL_GIN_TYPE=2 and FI_PROVIDER=cxi.
- NCCL 2.32.3 built-in GDAKI targets mlx5; private OFI direct backend targets
  EFA and was compiled with HAVE_GDAKI=0.
- CLIC current source needs fi_cxi_gpu_ext.h / FI_CXI_KI_OPS; October 26 login
  audit found no complete KI development installation in checked prefixes.
- The draft portable barrier patch exists at
  tools/cxi_gin/patches/deepep-bd1e166-portable-signal-wait.patch. Static checks
  pass; compilation and GPU tests are pending.
- Original EP8 demo job 3753568 and separate proxy profiler must remain
  distinguishable from this direct-GIN investigation.

## Execution log

- 14:27 UTC: created this plan and started the authorized investigation.
  No direct backend has been implemented or demonstrated at this point.
- 14:33 UTC: staged tools/deepep_direct_debug and isolated DeepEP-portable
  under /iopsstor/scratch/cscs/zyu/deepep-direct-20261026. Portable copy retains
  the original host extension and patches only JIT device headers, with a fresh
  JIT cache. Scripts and Python files pass static syntax checks.
- Debug QOS slots are occupied. To obtain evidence within the window, reuse
  already-queued two-node job **3754974** (ep8-profile-1026). Its original batch
  script snapshots the runtime tools at execution; the uniform step now first
  invokes a bounded per-node diagnostic sequence, then profiles. No nested srun
  is used. Each diagnostic has a fresh torchrun process group and separate port;
  inventory/compile 25 s each, selection cases 35 s each, portable test 150 s.
  Existing step/allocation limits remain 360 s / 15 min. Duplicate direct-job
  queue entry removed; other jobs unchanged. Evidence uses separate direct
  result/source directories. This is a capability/portability investigation,
  not proof of a direct backend.
- Earlier control job 3753568 finished: DeepEP v2 proxy correctness PASS
  (144 rank-case records); UCCL step crashed, making aggregate job FAILED.
  DeepEP uniform fresh dispatch/combine were approximately 6.5 ms each.
- 14:37 UTC: added mapping-only S4a probe using public libcxi and the allocated
  job's SLINGSHOT_DEVICES/SVC_IDS/VNIS. It creates a small TX queue, attempts
  CUDA registration/device-pointer mapping of its 4 KiB doorbell page, then
  unregisters and destroys resources. It does not emit commands, ring the
  doorbell, send packets, or prove GPU progress. Missing job metadata is a
  failure, not permission to allocate an unrestricted service. Node sequence
  now includes this 35-second bounded probe and caps the portable test at
  120 seconds, within the existing 360-second parent step.
- Public provider audit: HewlettPackard/shs-libfabric trees main
  8c8ce6ec, release/shs-14.0 69137ab5 and release/shs-15.0 9011331b
  have no fi_cxi_gpu_ext.h entry; the checked shs-15.0 fi_cxi_ext.h has no KI
  extension definitions. Public exact-symbol commit search returned no results.
  This bounds the search; it does not prove no other branch exists. Public
  libcxi mapping interfaces are available and form the limited S4a probe.

## Validated findings and follow-up

- Job **3754974 completed 0:0**, elapsed 4m16s, on nid006904/nid007487.
  Both nodes expose four CXI devices; PCI uevent identifies driver cxi_ss1
  and device 17DB:0501. Container modinfo could not find module metadata;
  this does not mean the loaded driver is absent.
- S2: proxy and auto each created/destroyed a GIN device communicator on all
  eight ranks with selected/support type [2]. Forced type 3 returned no
  supported types and create_rc=5 (invalid usage) on all eight ranks.
- S3: the isolated portable signal-wait patch JIT-compiled and passed one
  V4-Flash mixed-route FP8/BF16 correctness case at 4096 tokens/GPU on all
  eight ranks, with clean DONE markers. This validates the tested proxy path;
  broad lifecycle/timeout and other backend validation remain outstanding.
- S4a: both tested nodes successfully registered the NIC doorbell with CUDA
  and obtained a device pointer. No commands were sent in this test. Therefore
  a blanket claim that these nodes lack GPU doorbell mapping would be wrong.
  KI provider/API availability and actual GPU-issued command progress remain
  distinct gates.
- Prepared a separate GPU-NIC-NOOP follow-up using the job's public libcxi
  service: eight GPUs write CQ NOOP descriptors, ring their NIC doorbells and
  observe hardware read-pointer updates for 10,000 iterations, including
  wraparound, without host queue progress during the kernel. No network packet
  or RDMA payload is sent. Queue mapping/execution is not yet verified. The
  10-minute job is next in the feeder after already-submitted EP4 jobs; its
  bounded retry mechanism allows a reviewed source fix within the allocation.
- Proxy profiling also completed on all 16 rank/route traces. After excluding
  five warmups, uniform dispatch main-kernel median across rank medians is
  7.266 ms, copy epilogue 0.222 ms; combine main 6.627 ms, reduce epilogue
  0.029 ms. These instrumented durations include device waits and do not assign
  CPU/network causality. Raw capture averages contain a startup outlier.
  See results/ep8_profile_10_26/job-3754974/kernel_phases.md and .csv.

## Additional bounded raw-CXI probes staged at 15:03 UTC

The next allocation now first runs a separate 128-NOOP host control, then
10,000 GPU-issued NOOPs on each of eight GPUs. Only if all queue probes pass,
it runs 128 GPU-issued 64-byte puts per GPU across four independent same-index
node pairs. The GPU fills the source pattern, submits descriptors and rings
NIC doorbells, then verifies every incoming word. CPU setup and final event
verification are outside the kernel; no CPU posting/CQ draining occurs during
it. Payload buffers are CUDA-mapped host memory, not HBM. The event queue is
sized to hold this bounded run; therefore passing does not prove indefinite
CPU-free completion management, local-completion/flush semantics or a NCCL
GIN backend. Per-attempt source snapshots and separate NOP/PUT status markers
preserve failures for in-allocation debugging.

Reference for public resource/descriptor setup:
HewlettPackard/shs-libcxi 7c26f51d52129f3f622b450bfc666600e12881f1,
`tests/libcxi_test_common.c`, with installed compute-node headers as the ABI
source. The public reference checkout is read-only; no provider/driver has been
modified and no unavailable KI ABI has been fabricated.

## Build checkpoint — 15:09 UTC

Both GPU-NOOP and raw-put probes compile and link successfully on the AArch64
login node using the CUDA 13.0.88 compiler extracted from the existing SGLang
image and installed Cassini headers/library. The put host code also passes
`gcc -Wall -Wextra -Werror`. This is build validation only. A login-container
attempt could not run because the site Slurm hook requires `/run/slurm`; no
hook was bypassed. Only the needed toolkit files were extracted into this
investigation's private scratch directory.

The raw-put runner now has a second, separately recorded HBM mode, conditional
on all mapped-host-memory tests passing. It allocates CUDA device buffers,
sets `CU_POINTER_ATTRIBUTE_SYNC_MEMOPS`, registers them through public
`cxil_map(... CXI_MAP_DEVICE ...)`, and uses the same bounded GPU-only posting
and receive-verification kernel. HBM registration and execution are NOT yet
validated. Four peer pairs are tested simultaneously; this is not an all-to-all
EP8 communicator or a replacement for DeepEP correctness testing.

## Completion-counter gate staged — 15:16 UTC

Job **3755312** is submitted and pending behind EP4 job 3755123. The raw-put
runner now optionally continues, only after both nodes pass mapped-memory and
HBM puts, into a hardware-counter test. Each GPU issues 32,768 64-byte HBM puts
(256 rounds of 128 descriptors) with successful CQ events suppressed and NIC
ACKs counted in a Cassini CT. A second GPU-accessible command queue issues
`C_CMD_CT_GET`; the GPU polls CT writeback, including its error bits, before
starting the next round. No CPU CQ draining occurs during the kernel.

This exceeds the ordinary 64-KiB event queue's capacity if each put generated
a 16-byte success event. A passing counter test would therefore be stronger
than the bounded 128-put event-buffer test. Payload stays constant across
rounds and final receive contents are checked: it does not yet test source
reuse with changing data, data-before-signal ordering, multiwriter atomics,
concurrent CTAs or arbitrary NCCL contexts. Compile and link pass; hardware
execution remains pending.

## What a CXI GIN backend must supply after these probes

| DeepEP requirement | Relevant baseline source | Remaining CXI proof |
|---|---|---|
| Remote payload put | common/handle.cuh `put`; hybrid_dispatch/combine | Correct HBM registration, peer addressing, GPU queue ownership and sustained completion |
| VA signal add | common/handle.cuh `red_add_rel` | Exact 64-bit remote addition and visibility; replacing it with an absolute-value put is insufficient |
| Indexed barrier signal | common/comm.cuh `gin_barrier_wo_local_sync` | Per-context signal storage, increment, acquire wait, reset/reuse; portable wait patch removes the private GDAKI cast |
| Flush | common/handle.cuh `flush`; common/comm.cuh barrier | All earlier source reads complete before buffer reuse; separate from merely consuming a CQ descriptor |
| Strong/weak ordering | NCCL GIN device API contract | Signal visibility implies the required earlier/bundled data visibility, including remote GPU visibility |
| Rail/world teams | common/handle.cuh team mapping | Four local NVLink peers and correct cross-node peer/resource mapping |

The EP dispatch/combine scope does not require proving the separate Engram
`get` path just because its wrapper exists. Unsupported broader operations
must remain explicit if a limited backend is developed.

Public libcxi provides NIC-specific resources rather than IB verbs metadata:
LNI/service/VNI, communication profiles, domain PID/NIC address, portal-table
entries and memory LAC/IOVA. These can potentially support a CXI host/device
GIN pair, but are not valid mlx5 QP/WQE/lkey/rkey objects. The NCCL GIN developer
guide explicitly distinguishes a host-only proxy plugin from a full custom
implementation requiring both host and device APIs. Thus setting type 3 is
not the implementation step; matching backend code and versioned device
handles are required. This investigation has not added that backend yet.

## Atomic and registration gates staged — 15:27 UTC

The hardware-counter and atomic probes run independently after the two-node
HBM put gate. The atomic test uses the installed SDK to encode a small IDC
64-bit unsigned SUM, padded to a 64-byte command slot, then has the GPU issue
128 increments to its peer's HBM word. CPU configures CQ state before launch;
the receiving GPU checks the exact final value. It is a single-remote-writer
prerequisite test, not a concurrent GIN signal/ordering proof.

HBM registration now follows the available provider mechanism: try CUDA
DMA-BUF export and `cxi_md_hints` first, then the public device-pinning path if
needed. Every attempt and return code is logged; neither route is assumed to
work before execution. NIC error events and CQ status are collected after a
failed kernel. A failed GPU-NOOP run may receive a separate CPU doorbell ring
for diagnosis; its original failure remains a failure.

All current C and CUDA sources compile and link against the existing image's
CUDA toolkit and the installed SDK. No GPU execution of these new probes has
yet occurred. Job 3755312 remains pending due to QOSMaxJobsPerUserLimit.

The installed NCCL headers enumerate proxy=2, GDAKI=3, GPI=4 and EFA_GDA=5;
`gin_device_common.h` dispatches to a compiled specialization for each. GPI
also uses NVIDIA DOCA interfaces; it is not an existing generic CXI backend.
A maintainable CXI integration needs its own recognized host/device backend
and capability checks, rather than reusing an unrelated numeric device type.

## Failure diagnosis and retry procedure

1. Collect `results/deepep_direct_10_26/nop-3755312/attempt-N`, including
   `run.log`, `put-run.log`, per-GPU logs, stage status and source snapshot.
2. NOP interpretation: compare GPU status with `final_nic_status`. If the GPU
   timed out, the separate `post_failure_cpu_doorbell` reports whether a host
   ring advances the NIC. This does not turn the failed GPU phase into a pass.
3. RMA interpretation: identify registration mode/return code, device queue
   status, NIC event error code, GPU receive verification and final teardown
   result. For CT mode, distinguish command-consumption from NIC completion
   writeback. Do not infer completion from the TX read pointer alone.
4. Make a specific source fix only after examining the failure. Recompile in
   the isolated SDK workspace, deploy changed probe files, then create
   `/iopsstor/scratch/cscs/zyu/deepep-direct-20261026/retry-3755312-N` to request
   the next in-allocation attempt. Maximum three attempts and a 10-minute
   allocation; each attempt snapshots sources afresh. Preserve earlier logs.
5. A passing primitive is not a passing NCCL/DeepEP backend. Keep S6–S8
   pending until matching host/device GIN code, signal ordering and EP8
   correctness are actually validated.

Build manifest and SASS are retained under
`results/deepep_direct_10_26/login-compile/`. Inspection confirms that the
NOOP kernel contains descriptor stores, system fences, a system-scope GPU
store to the doorbell, and system-scope status loads. This confirms generated
code, not NIC execution.

The original type-3 log explicitly records: the Libfabric type-2 plugin is
skipped because type 3 was requested; NET/IB finds no device; then no GIN
plugin initializes. The later symmetric-memory warning is downstream of
that missing backend. It does not establish a broken NVLink fabric.

After job 3754974 completed and its artifacts were collected, the temporary
diagnostic hook was removed from `tools/ep8_profile/inside.sh` locally and in
remote runtime tools. The completed job's immutable source snapshot still
records the hook it actually executed. Future profiling runs keep their
normal behavior.

## Hardware milestone — job 3755312 COMPLETED, 16:00 UTC

The 46-second allocation on **nid006760 / nid007658** completed **0:0** on
its first attempt. Every stage passed on all eight GPUs:

| Primitive | Observed result | Scope |
|---|---|---|
| GPU NIC queue | 10,000 NOOPs/GPU, including wraparound | GPU wrote descriptors, rang the NIC doorbell and polled NIC consumption |
| Cross-node mapped-memory puts | 128 x 64-byte puts/GPU, every incoming word checked | Four independent bidirectional GPU/NIC pairs |
| Cross-node HBM puts | 128 x 64-byte puts/GPU, every incoming word checked | CUDA device allocations; DMA-BUF export and CXI registration succeeded |
| GPU completion counters | 32,768 HBM puts/GPU; GPU observed exactly 32,768 NIC ACK completions | Success events suppressed; GPU issued CT_GET and polled writeback; no CPU CQ drain during the kernel |
| Remote HBM atomic add | 128 GPU-issued uint64 SUM operations/GPU; remote GPU observed 128 | One remote writer per target word; bounded event queue |

No CPU network posting/progress function executes while these kernels run.
CPU resource setup and final verification/teardown are outside the kernels.
All per-GPU processes exited zero, including checked put-resource teardown.
The hardware status return code **1 is C_RC_OK** in the installed SDK.

A practical mapping detail: ordinary CUDA registration of the driver-owned CQ
buffer returned CUDA error 1; the already-staged `cudaHostRegisterIoMemory`
registration succeeded, and actual GPU queue execution then passed. Thus we
have evidence beyond a mapped pointer. Each tested GPU also reports GPUDirect
RDMA support and GPUDirectRDMAWritesOrdering=200.

**Revised conclusion:** these tested nodes already support the raw GPU-issued
CXI operations needed for a plausible direct backend. Missing CLIC KI headers
are not an absolute hardware barrier to exploring a public-libcxi route.
However, this is **not yet a CPU-free NCCL GIN plugin or DeepEP EP8 run**.
The NCCL type-3 selection failure remains real. No DeepEP direct-mode latency
or bandwidth result is claimed, and these small serial probes are not
throughput benchmarks.

Next: validate source reuse and payload-before-signal ordering with changing
payloads and repeated handshakes; then integrate a correctly identified,
versioned CXI host/device GIN backend. Multi-CTA/context concurrency,
multiwriter signals, cancellation/errors and full DeepEP correctness remain.
A separate `tools/deepep_direct_debug/ordering` prototype preserves the exact
passing primitive implementation in the first allocation's source snapshot.

## Integration contract and remaining gates — 16:21 UTC

The raw probe is a useful feasibility result, but the next change belongs in
an isolated NCCL CXI host/device GIN backend, with DeepEP kept at bd1e1669.
Selecting NCCL_GIN_TYPE=3 alone cannot provide that backend: the current type-3
implementation expects its supported NIC resources and device command format.
Our CXI code instead obtains Cassini resources through public libcxi and emits
Cassini commands. Working proxy transport established network connectivity;
the new GPU probes establish a separate, stronger prerequisite.

Source audit identifies a concrete scaling requirement:

- `DeepEP/csrc/kernels/backend/nccl.cu:96` requests
  `ginContextCount=num_allocated_qps`, exclusive contexts, queue depth 1024,
  12 indexed signals for EP8, and rail connectivity in hybrid mode.
- The tested proxy/portable run logs **129 allocated QPs per rank** in
  `results/deepep_direct_10_26/job-3754974/portable-node0.log:410`.
- `deep_ep/buffers/elastic.py:199` defaults hybrid mode to 129 allocated
  contexts when the fast-atomic heuristic is false. The heuristic in
  `deep_ep/utils/envs.py:223` recognizes a specific mlx5 device through ibstat;
  the successful CXI atomic probe does not justify changing this performance
  heuristic to true.
- Hybrid operation chooses `min(num_sms * 16 + 1, num_allocated_qps)`;
  the nonhybrid nine-QP cap must not be applied to this run. The benchmark
  computes DeepEP SM count automatically; its `--sms` argument configures
  UCCL, not DeepEP.

A backend must preserve these logical-context semantics, whether using
independent hardware queues or a carefully synchronized mapping onto fewer
queues. The current single-producer probes do not validate multi-CTA queue
reservation/publication, per-context completion/flush, credits, concurrent
signal updates, signal reset/reuse, error/abort handling, or repeated lifecycle.
Reducing context counts for a first smoke test would require an explicitly
labelled configuration and a matching proxy control; it is not an equivalent
performance comparison to the existing baseline.

### Ordering/source-reuse follow-up

The separate `tools/deepep_direct_debug/ordering` implementation compiles and
links against the installed CUDA/CXI stack. It is queued in the existing
feeder for the next free debug submission slot; no hardware pass is claimed.
The source snapshot from successful job 3755312 remains intact.

Each GPU exchanges 128 changing rounds of 128 x 64-byte HBM payloads. It waits
for NIC completion with delivery-complete puts, immediately overwrites the
source, publishes READY using a remote atomic, and verifies the received
payload immediately on observing READY. A peer ACK prevents the next round
from overwriting data before verification. Expected per GPU: 16,640 completed
commands and 131,072 verified 64-bit words. No host progress runs during the
kernel. This validates the proposed sequential put/signal/flush contract if
it passes; concurrent contexts and general GIN semantics remain separate gates.

The detached collector records the eventual job ID, source snapshot, scheduler
state and per-rank results in `results/deepep_direct_10_26`, and refreshes the
checkpoint below. It collects evidence; it does not autonomously implement
further backend changes after this interactive debugging window ends.

| Stage | Status at this checkpoint |
|---|---|
| S0 baseline/isolation | PASS: bd1e1669a932 unchanged; isolated patch and source snapshots |
| S1 capability | PASS for tested-node inventory; CLIC KI development dependency absent in checked environment |
| S2 backend selection | PASS diagnostic: proxy/auto succeed; requested type 3 unsupported on all eight ranks |
| S3 portable barrier | PASS for one EP8 mixed-route 4096-token/GPU correctness case under proxy; broader lifecycle tests remain |
| S4 direct resources | PASS: all eight GPUs execute NIC queue commands through public libcxi |
| S5 direct primitives | PARTIAL: HBM puts, queue wraparound, GPU completion counters and remote atomic adds pass; ordering/source reuse queued; concurrent signals and lifecycle remain |
| S6 NCCL CXI GIN backend | NOT IMPLEMENTED; host/device API and logical-context requirements identified |
| S7 CPU-free DeepEP EP8 | NOT RUN: requires S6 |
| S8 CPU-free performance | NOT RUN: requires S7; raw probes are not bandwidth measurements |
| S9 evidence/report | Collected locally; final queue state is recorded below |

### Submission checkpoint — 16:24 UTC

The feeder submitted the ordering/source-reuse test as **3756020**. At
16:23:52 UTC it was PENDING (Priority), not running. The detached collector is
alive and will record the eventual outcome; a scheduler submission is not a
correctness pass. Local and remote staged ordering sources/scripts match in
all six files; hashes are in
`results/deepep_direct_10_26/ordering-source-manifest.json`.

## Two-hour checkpoint — 16:27 UTC / 17:27 Zurich

The authorized two-hour investigation has reached its checkpoint. Jobs
3754974 and 3755312 completed 0:0; the latter demonstrated the listed raw
GPU-issued CXI primitives on all eight GPUs. Full CPU-free NCCL GIN and DeepEP
EP8 correctness/performance remain unimplemented and unmeasured.

Ordering/source-reuse job 3756020 is **PENDING**
((Priority)). The detached collector remains active and
updates this document with results. It does not perform unattended code fixes.
The next engineering action is to inspect that gate, fix any reproduced failure,
then implement the isolated CXI host/device backend with the context and signal
contracts above. No existing EP4 job was cancelled, and baseline bd1e1669a932
remains clean.

## Follow-up: ordering PASS and source-level transport boundary

Job **3756020 completed 0:0 in 21 seconds**, on nid007645/nid007653.
All eight GPUs passed 128 changing-payload rounds, 16,640 completed commands
and 131,072 verified 64-bit words per GPU. Source overwrite after completion
and immediate payload verification after READY both passed. Results and exact
sources are in `results/deepep_direct_10_26/order-3756020/` and
`results/deepep_direct_10_26/sources/order-3756020/`. The earlier pending entries
are historical checkpoints. Multiwriter/concurrent-context and full GIN tests
remain outstanding; no bandwidth claim follows from this small serial test.

### Pinned bd1e1669 source map

| Layer | File / entry point | Responsibility |
|---|---|---|
| DeepEP dispatch/combine | `DeepEP/deep_ep/include/deep_ep/impls/hybrid_dispatch.cuh`, `hybrid_combine.cuh` | Token/metadata transfer and local NVLink work; scale-out uses rail GIN operations |
| DeepEP transport wrapper | `DeepEP/deep_ep/include/deep_ep/common/handle.cuh:175` (`put`), `:98` (`red_add_rel`), `:145` (`flush`) | Express remote operations through ncclGin, symmetric windows and offsets |
| DeepEP host setup | `DeepEP/csrc/kernels/backend/nccl.cu:81` | Query GIN availability, create contexts/rail connectivity, register symmetric memory |
| NCCL proxy device | `tools/cxi_gin/reference/nccl-v2.32.3-1/gin_proxy.h:106` (`postGfd`) | GPU publishes descriptors into a CPU-consumed queue |
| NCCL proxy host | `tools/cxi_gin/reference/nccl-v2.32.3-1/gin_host_proxy.cc:319` | Translate descriptors into host plugin iput/iputSignal and completion processing |
| Our OFI/CXI host plugin | `tools/clariden_deepep/aws-ofi-nccl-gin/src/rdma/gin/nccl_ofi_gin_reqs.cpp:314`, `nccl_ofi_gin_api.cpp:277` | fi_writedata/fi_writemsg; CPU resource progress and GDRCopy signal-delivery completion |
| NCCL direct NVIDIA-NIC reference | `tools/cxi_gin/reference/nccl-v2.32.3-1/gin_gdaki.h:61` | GPU QP handles, lkey/rkey, DOCA device puts/signals and CQ completion |
| CXI direct prototype | `tools/deepep_direct_debug/gpu_put*`, `ordering/gpu_order*` | Host allocates/maps CXI resources; GPU emits Cassini commands, rings doorbells, observes completions and signals |

Working proxy execution establishes that the tested DeepEP operations can be
implemented over CXI; it does not mean DeepEP contains a native Cassini device
backend. CPU proxy also does not imply that payload must be staged through
CPU memory. Request submission/progress and GPU-memory DMA are separate axes.

The NVIDIA proxy/direct implementations provide a useful same-API comparison.
The difference is below DeepEP's ncclGin calls. GPU-side verbs in the GDAKI
backend encode NVIDIA-NIC commands; they are not the ordinary host verbs
functions compiled for a GPU, nor reusable Cassini descriptors. The future CXI
backend must implement matching host resource/registration handles and device
put/signal/flush/context semantics. Existing proxy code supplies useful setup
and semantic reference, but its CPU queues, locks, CQ progress and signal
workers cannot simply be relabelled GPU code.

One actual DeepEP portability exception is `common/comm.cuh:166`: the baseline
barrier casts the opaque GIN handle to `ncclGinGdakiGPUContext`. Our isolated
portable patch uses public waitSignal/readSignal instead and has passed the
recorded proxy EP8 case. This change belongs above the new backend.

Reference architecture: NVIDIA's [GIN developer guide](https://github.com/NVIDIA/nccl/blob/master/plugins/gin/README.md)
distinguishes host-only proxy plugins from full host/device implementations.
The pinned local NCCL 2.32.3 guide and source files are used for concrete line
references; this audit does not update DeepEP upstream.

## Detailed code structure and proposed CXI patch boundaries

This is a source-level design, not a completed backend. DeepEP remains pinned
to bd1e1669; NCCL references are pinned to v2.32.3-1. Nine additional reference
files were fetched and verified against their upstream Git blob SHA; provenance
is in `tools/cxi_gin/reference/nccl-v2.32.3-1/structure-audit-manifest.json`.
The `gin_plugin.cc` reference is upstream `src/plugin/gin.cc` renamed locally
to distinguish it from other gin.cc files. These are reference copies, not an
installed or compiled NCCL fork.

### 1. Shared DeepEP layer

Host: `csrc/kernels/backend/nccl.cu` queries available GIN support, requests
contexts/queue depth/signals and rail connectivity, and registers a symmetric
window. GPU: `impls/hybrid_dispatch.cuh` and `hybrid_combine.cuh` use
`common/handle.cuh` to express put, VA signal add and flush. Local NVLink work
and MoE routing/packing remain above the NIC-specific implementation.

NCCL `src/include/nccl_device/impl/gin__funcs.h` translates team peers and
window offsets into backend calls. For example, Put calls `ncclGinApi_Put`,
signals also reach that operation with the appropriate signal descriptor,
and Flush calls `ncclGinApi_Flush`. `gin_device_common.h:209` dispatches these
calls by backend. `gin_device_api.h` includes each compiled implementation.

### 2. Proxy control and payload paths

```text
GPU DeepEP put / signal / flush
  -> NCCL gin_proxy.h: buildGfd -> postGfd
  -> shared request queue (operation metadata)
  -> NCCL gin_host_proxy.cc: decode and submit
  -> host plugin iput / iputSignal / iflush / test / ginProgress
  -> private OFI plugin -> libfabric CXI provider -> Cassini

Payload: registered source GPU memory -> NIC/network -> target GPU memory
         (CPU request handling does not itself require CPU payload staging)
```

The private plugin's `src/rdma/gin/nccl_ofi_gin_reqs.cpp:314` posts
fi_writedata/fi_writemsg. `nccl_ofi_gin_api.cpp:277` calls resource progress and
drains completions from the GDRCopy signal-delivery worker. Thus the current
CPU role includes completion and remote notification handling, not just
turning a sender request into a NIC command. Its mutexes, host CQ loops and
worker queues are CPU implementation details, not device-callable primitives.

### 3. Direct NVIDIA-NIC reference

```text
CPU initialization
  -> createContext: allocate/configure QPs and GPU-visible queue resources
  -> regMrSym: register memory and exchange peer keys
  -> return versioned device context/window handles
GPU steady-state
  -> ncclGinApi_Put<GDAKI> in gin_gdaki.h
  -> DOCA device verbs using QP and memory-key handles
  -> NIC commands/doorbell -> NIC transfer
  -> GPU completion polling and signal observation
```

Host reference:
`src/transport/net_ib/gdaki/gin_host_gdaki.cc:588` creates contexts;
`:999` exports QPs to device handles; `:1255` registers symmetric memory.
`gin_gdaki_device_host_common.h` defines the shared ABI: QP pointers, signal
and counter tables, and NVIDIA memory keys. Device reference `gin_gdaki.h`
implements Put/PutValue, Flush/FlushAsync/Wait, signal/counter access and reset.
The high-level GIN API can be reused; these NVIDIA-NIC queue descriptors and
keys cannot be presented to Cassini unchanged.

**CPU-free check:** even this GDAKI reference computes `need_cpu_proxy` from
the exported QPs and sets `needsProxyProgress` at line 1052. Its progress
function at line 1331 can call `doca_gpu_verbs_cpu_proxy_progress`. Therefore
type 3 alone is not proof that every supported configuration is CPU-free.
Our CXI acceptance test must demonstrate no required per-transfer host
progress and report the actual handle/progress configuration.

### 4. Concrete patch packages

| Package | Existing source/reference | Proposed change and acceptance gate |
|---|---|---|
| DeepEP portability | `common/comm.cuh:166` | Use public bounded signal wait/read instead of casting to the GDAKI private layout. Isolated patch already passed one proxy EP8 correctness case. |
| CXI shared ABI (new) | GDAKI shared header; raw `gpu_put_contract.h` / `gpu_order_contract.h` | Define versioned CXI context, peer and window handles: mapped command queues/doorbells, completion storage, queue ownership, peer addressing and memory-registration descriptors, indexed signals. No cast to an mlx5 context. |
| CXI host plugin (new) | `ordering/gpu_order_host.c`, GIN plugin API, `gin_host_gdaki.cc` lifecycle | Implement init/devices/properties, listen/connect, create/destroy context, symmetric registration/deregistration, error query and teardown. Use allocated Slurm services/VNIs and public libcxi. Replace probe shared-file peer exchange with plugin bootstrap exchange. Return device-visible descriptors; request no host data progress only once that is actually true. |
| CXI device operations (new) | `ordering/gpu_order.cu`, `gpu_put.cu`, `gin_gdaki.h` API surface | Implement dynamic puts, VA/indexed signal adds, flush and signal access through Cassini commands. Add runtime address/length encoding, segmentation, queue credits, cooperative-thread rules, abort/timeout behavior, and per-context ordering. |
| NCCL host integration | `src/gin/gin_host.cc:276`, `src/plugin/gin.cc:331`, public/backend type definitions | Add a distinct CXI backend identity and version negotiation; audit type bounds, capability arrays, priority and diagnostics. Existing unknown types fail the version switch. Do not reuse type 3 for incompatible context layouts. |
| NCCL device integration | `net_device.h`, `gin_device_common.h`, `gin_device_api.h` | Add the agreed type, enable/mask/dispatch entry and include CXI specializations. Match host/device versions; rebuild the isolated library and DeepEP JIT code against the matching headers. A .so alone is insufficient. |
| Integration tests | existing raw tests and `gin_probe.cu` | Start with GIN-only operations and one context; scale to concurrent contexts, signals, arbitrary lengths and repeated lifecycle; then EP8 DeepEP correctness and unprofiled performance. |

The new type/name is a design placeholder, not an upstream-assigned enum or a
currently supported NCCL_GIN_TYPE value. A full NCCL checkout/patch build is
still needed; this table identifies concrete integration points rather than
claiming an exhaustive already-applied diff.

### 5. What must be generalized beyond the passing probes

The probes use host-encoded templates, fixed 64-byte transfers and fixed peer
pairs. A real backend must derive commands from arbitrary GIN windows, offsets,
sizes and target peers; preserve access permissions and handle multiple memory
regions. NIC queue-consumption pointers do not establish source-buffer safety:
flush must use appropriate transfer completion. A NIC CT ACK count is useful
internal machinery but is not automatically the public NCCL per-operation
counter contract.

The ordering test uses delivery-complete puts and a conservative wait before
publishing READY. It validates that particular sequential protocol. It does
not establish all strong/weak signal behavior, multiwriter signal updates,
signal reset safety or queue sharing among CTAs. Our first backend can use
conservative ordering for correctness, then optimize only with matched tests.
Its small serial loops are unsuitable as a performance implementation.

NCCL's strong signal requires visibility of preceding operations in that
context; a weak signal covers its bundled put. Flush guarantees local
completion/source reuse for puts. These promises need separate tests. Public
API operations not implemented for the initial DeepEP subset must fail clearly
or be excluded by audited capabilities/call sites; no silent no-op stubs.

DeepEP's current hybrid configuration allocates 129 contexts/rank, asks for
queue depth 1024 and 12 indexed signals for EP8. A one-context adapter is a
first integration gate, not an equivalent benchmark. Sharing fewer physical
queues requires correct reservation, ordered publication, per-context progress
and completion accounting. Resource capacity and GPU/NIC placement must be
checked on the actual allocation.

### 6. High-level implementation order (expanded in P01–P14 above)

1. Extract the passing public-libcxi setup and GPU primitives into a small
   reusable CXI module with explicit host/device descriptor versions.
2. Implement the host plugin and one-context device Put/Signal/Flush contract;
   wire it into an isolated matching NCCL host/device build.
3. Run GIN-only put + signal + source-reuse tests, without DeepEP, including
   teardown and absence of required CPU progress. Expand sizes and peers.
4. Exercise multiple producers/contexts, multiwriter signals, bounded errors
   and resource limits up to the intended DeepEP configuration.
5. Apply the isolated DeepEP portable barrier patch and validate the complete
   EP8 dispatch/combine reference at 4096 tokens/GPU.
6. Compare unprofiled proxy/direct latency with identical routes, payload
   formats and context/SM settings; then use traces/counters to tune batching,
   doorbell rate and concurrency.

The recommended starting point is our working libcxi prototype plus NCCL's
full-backend interface. The existing OFI proxy remains a control and semantic
reference. DeepEP's token-routing kernels are not the main implementation site.

## Ten-hour autonomous implementation run

Authorized start **2026-10-26 19:37:53 UTC** (20:37 Zurich); checkpoint
**2026-10-27 05:37:53 UTC** (06:37 Zurich). User authorized two GH200 nodes in
debug or normal. Final scope now explicitly includes SGLang's DeepEP v2
dispatcher and cross-node dispatch/combine measurements (P13); reproducible
packaging moves to P14. No additional user guidance is needed to start.

- P01 IN_PROGRESS: full isolated NCCL v2.32.3-1 source obtained at
  **12df1a11afad322be5a204a2db890161cbf8131d**, local branch cxi-gin-20261026.
  No submodules are declared. Unmodified source archived to a separate remote
  control directory; DeepEP baseline remains bd1e1669a932 and clean.
- Clariden access confirmed. Normal limit is 12 hours, debug 90 minutes at
  this check; existing EP4 debug work remains untouched. New tests will use
  bounded allocations and retain per-attempt sources/results.
- SGLang integration preflight: local historical third_party tree exposes
  the older dispatcher. Actual container source/API will be inventoried before
  selecting an adapter. The enclosing repository revision is not assumed to
  identify a standalone SGLang checkout.

### 20:02 UTC implementation checkpoint

- P01: unmodified NCCL control **BUILD_PASS**. Two-node normal job
  **3757981** is pending. An idempotent debug fallback is queued behind existing
  work; it can cancel only our still-pending normal job before submitting the
  same control to debug. Running or completed jobs are never replaced.
- P02–P04: reusable CXI host resources, dynamic GPU operations, and public GIN
  device-API instantiation compile against Clariden's installed SDK. The new
  dynamic probe covers 0 bytes through 16 MiB, changing/unaligned offsets,
  guard bytes, delivery completion, source poisoning, and remote READY/ACK.
  **Hardware validation is pending**, separate from previous raw-probe passes.
- P05–P06: an experimental full-backend plugin and NCCL dispatch integration
  are being built. Private backend type **6** is CXI-specific; type **3** remains
  GDAKI. Device operations use Cassini commands, not translated mlx5 WQEs.
  Plugin initialization/registration uses host TCP bootstrap; device descriptors
  request `needsProxyProgress=0`. This flag is a design choice, not yet runtime
  proof of successful CPU-free communication.
- First modified-NCCL build exposed missing install rules for the new `.cuh`
  headers; rules were added. Initial host-plugin link needed the extracted
  CUDA SDK's static runtime. These are build issues, not NIC capability results.
- Initial backend intentionally favors correctness: serial queue-consumption
  checks and delivery-complete flushes before signals. GET is rejected explicitly;
  the first supported operation subset is audited DeepEP PUT/signal/flush.
  No throughput claim is justified until public GIN, concurrency, and full
  DeepEP/SGLang gates pass.

### 20:07 UTC — first P01 allocation failed at import

Job **3757981 FAILED 1:0**, 22 seconds, nodes nid006299/nid006668.
No communication kernel ran. PyTorch explicitly preloaded its venv's NCCL
in addition to the rebuilt NCCL specified with LD_PRELOAD; DeepEP's duplicate
runtime guard correctly rejected the process. The guard remains enabled.

The image's `torch/__init__.py` confirms `_preload_cuda_deps` searches
`sys.path` for `nvidia/nccl/lib/libnccl.so.*`. A private per-attempt Python
path overlay now directs that search to the selected build as well as setting
LD_PRELOAD/LD_LIBRARY_PATH. The next allocation must verify one loaded NCCL
before proceeding. Failure artifacts are in
`results/deepep_direct_10_26/tenhour/p01-3757981`.

The actual SGLang image was also inspected: its normal dispatcher imports
legacy `deep_ep.Buffer`. DeepEP v2 still exports that legacy class, so package
replacement alone is insufficient. P13 needs an explicit isolated
ElasticBuffer adapter; the mapping and validation requirements are recorded
in `tools/cxi_gin/backend/docs/sglang_integration.md`.

### 20:13 UTC — control retry running

Retry **3758224 RUNNING** on nid006278/nid006281. Its private Python NCCL
overlay is in place; the duplicate-runtime guard is still enabled. Per-attempt
sources and per-node outputs are retained. Direct testing follows only if the
control and dynamic raw-CXI stages succeed and the modified NCCL build is ready.

Additional local validation: TCP bootstrap with eight peers and 64 changing
allgathers passed exactly (`bootstrap_test`); this proves setup exchange only.
The public GIN test now also instantiates FlushAsync/Wait. Backend host/device
ABI sizes are asserted explicitly. `collect.py` records accounting and separates
control, raw dynamic, and direct-GIN verdicts rather than treating batch completion
as proof of every gate.

### 20:14 UTC — runtime fixed; CPU allocation preflight failed

**3758224 FAILED 1:0**, 38 seconds. Both nodes loaded exactly the intended
control NCCL library and imported the portable DeepEP build, so the duplicate
runtime issue is fixed. `torch.cuda.nccl.version()` reports PyTorch's build-time
2.28.9; the loaded file is 2.32.3 and the C API probe remains the runtime-version
check. Do not confuse those two version sources.

The worker affinity helper then rejected ranks 1–3: the 16-CPU launcher cgroup
had no CPUs near those GPUs. Widening affinity cannot escape that cgroup.
The corrected allocation requests **288 CPUs/node**, matching the earlier
successful EP8 setup, and uses `srun --cpu-bind=none`; per-GPU workers retain
their normal NUMA binding. No network kernel ran in this failed attempt.

### 20:20 UTC — P01 passed; subsequent copy step failed

Job **3758279** on nid006046/nid006050 recorded:

- **8/8** proxy communicator create/destroy, runtime version **23203**,
  selected type **2**.
- **8/8** portable DeepEP V4Flash 4096-token/GPU FP8 mixed-route correctness;
  summary PASS, 32 operation records, 160 event samples (short control run,
  not a final performance campaign).
- Both per-node control PASS markers were written. The aggregate batch failed
  afterward because container `cp -a` could not preserve scratch ACL/mode
  attributes. Dynamic and direct tests had not started. Source copying now
  avoids preserving those attributes.
- Modified NCCL full build **PASS at 20:18:23 UTC**. This is compilation proof,
  not direct-GIN runtime proof.

The next allocation will retain two nodes for at most one hour with serial,
explicit test requests and a ten-minute idle cutoff. Failed test steps remain
failed records; the allocation can accept a corrected immutable snapshot
without rerunning P01. No other user's or existing serving jobs are modified.

### 20:21 UTC — bounded allocation and preserved build

Next allocation **3758296**, normal, two GH200 nodes, 288 CPUs/node, one-hour
limit, is pending. Its first explicit request runs only the dynamic raw-CXI
gate; direct GIN is submitted to the allocation only after that passes. The
obsolete P01 debug-fallback queue entry was removed without changing other
queued work. The allocation driver exits after ten minutes without a request.

The first modified NCCL release is preserved at remote
`tenhour/releases/cxi-20261026-201823` with matching headers. Shared-library
SHA256: `43126080b901ff199c20dce664aec5d39eda36c8785aac629c45de4a3b95f295`.
Local integration diff and new-header hashes are under
`tools/cxi_gin/backend/docs/`. Actual SGLang source reference is the image's
`/sgl-workspace/sglang/python/sglang`, confirmed by the running-job inventory.

### 20:30 UTC — scheduling adjustment and concurrency audit

The one-hour normal allocation was initially estimated beyond the ten-hour
window. Job **3758296** is now capped at **20 minutes**, with a **10-minute
minimum** for backfill. The driver derives its budget from Slurm's actual end
time, reserves cleanup time, and rejects a step whose timeout does not fit.
An attempt to enable both debug and normal partitions was rejected by Slurm's
accounting/QOS submit limit; the job remains on normal. Existing debug work is
left intact. The latest scheduler estimate is approximately 21:00 UTC, subject
to change.

Source audit found multiple notify threads sharing DeepEP's context zero.
`gin_producer_stress.cu` now compiles and will test same-warp and cross-CTA
contention on one context before DeepEP is enabled. One producer per context
is insufficient coverage. No raw dynamic or direct-GIN hardware result has
been obtained yet in this run.

### 20:39 UTC — dynamic CXI transfers passed on a new allocation

Job **3758296** started on `nid006116,nid006314` with a ten-minute
backfill allocation. Its first request passed on **8/8 GPUs**: 18 rounds per
GPU, sizes from zero through 16 MiB, unaligned offsets, guard bytes, changing
payloads, source poisoning after completion, and READY/ACK ordering.
All ranks reported zero diagnostics/errors and `posted=completed=100`.
This qualifies the dynamic resource/descriptor layer; it is still a raw-CXI
probe, not NCCL GIN or DeepEP.

The second request now exercises the public NCCL GIN API with explicit CXI
backend type 6 and one/four contexts. Source snapshots are immutable under
`tenhour/sources/gate-20261026-2021` (raw) and
`gate-20261026-2039` (GIN). The latter includes fail-fast teardown: an errored
CUDA context or failed NIC cleanup terminates the isolated rank with exit 86;
it does not free possibly live resources and pretend recovery succeeded.
This failure policy still needs fault-injection qualification.

The actual SGLang dispatcher harness and opt-in adapter are prepared but have
not run. They preserve fresh dispatch, nonuniform routing weights, and separate
BF16/FP8 cases; a deterministic expert transform validates combine semantics.
No full-model serving or performance claim follows from these planned tests.

### 20:44 UTC — public direct CXI GIN and concurrency gates passed

All following results are from **3758296**, `nid006116,nid006314`:

| Request | Result | Evidence scope |
|---|---|---|
| `02-direct` | FAIL before kernel | `ncclMemAlloc` VMM buffers reject pointer-level `SYNC_MEMOPS` with CUDA error 801 |
| `03-direct-vmm` | PASS 8/8 ranks | Explicit type 6; one/four contexts; 14 rounds/context; indexed/VA signals, PutValue, payload, source reuse, counters, FlushAsync/Wait; clean teardown |
| `04-producer` | PASS 8/8 ranks | One shared context, 1/2/8 CTAs × 32 GPU threads × 128 rounds; exact values and atomic signal counts; queue wrap |
| `05-context129` | PASS 8/8 ranks | 129 independent contexts/GPU × 14 rounds; every result has zero errors; clean teardown |

The VMM fix checks GPUDirect-RDMA capability, preserves existing CUDA context
flags, enables and verifies `CU_CTX_SYNC_MEMOPS`, and synchronizes once during
registration. It does not add CPU network progress. The synchronization scope
is documented by [NVIDIA's context API](https://docs.nvidia.com/cuda/cuda-driver-api/cuda_driver_api/group__CUDA__CTX.html)
and [primary-context flags](https://docs.nvidia.com/cuda/archive/12.5.0/cuda-driver-api/group__CUDA__PRIMARY__CTX.html).
The tested driver returned RDMA capability 1 and context flags `0x88`.
The plugin reports `needsProxyProgress=0`; its progress callback is null, and
payload/CT/atomic commands execute in GPU code. Separate host collective
bootstrap/control traffic remains present and is not labelled CPU-free.

This establishes a working experimental **public GIN transport**, not yet
DeepEP EP8 or SGLang integration. Reset/reuse, repeated lifecycle, bounded
negative tests and profiling remain before a broader qualification claim.
Requests `06-reset` and `07-reset-bounded` were refused by the lease controller
because their requested timeout plus cleanup reserve exceeded the allocation
budget; these were not executed kernel failures. `08-reset-short` retries with
a 60-second outer watchdog. The source snapshot is `gate-20261026-2043`.

### 20:50 UTC — first allocation complete; lifecycle continuation queued

`08-reset-short` passed on all eight ranks: both indexed signals and local
counters plus VA signals were reset at global quiescence, and a second full
transfer epoch passed with clean teardown. Job **3758296** was released early
and completed in 6m47s. Its aggregate COMPLETED status does not erase the
recorded initial VMM-registration failure or the controller-refused requests.

Job **3758590** is queued in normal (30-minute maximum, 10-minute backfill
minimum), with a first request for **20 create/register/transfer/reset/
deregister/destroy cycles per rank**. A separate prepared test checks an
incompatible API version and a deliberately delayed GPU peer: the short wait
must time out, a subsequent bounded wait must recover, and teardown must pass.
An invalid-offset test is also prepared; it requires the exact bounds diagnostic
before controlled rank termination, not merely any nonzero exit code.

The SGLang harness now additionally has an optional path through the actual
image's DeepGEMM pre/post permutation functions (`ep_scatter`/`ep_gather`).
This checks real layout and router-weight application around a deterministic
expert transform. It remains unrun and is not a full GEMM/model benchmark.
All snapshot-specific results are collected under
`results/deepep_direct_10_26/tenhour/leases/`.

<!-- AUTO_CHECKPOINT -->
## Earlier raw-prerequisite checkpoint

Updated UTC: 2026-10-26T17:22:47.590585+00:00

Allocation: **3754974 / COMPLETED**.

**CPU-free DeepEP EP8 has not been demonstrated. Raw GPU/CXI prerequisite tests are reported separately below.**

Job artifacts: `results/deepep_direct_10_26/job-3754974`

| Probe | Collected evidence |
|---|---|
| proxy | 8/8 readable property records; 8/8 create+destroy success; selected types `[2]`; supported `[2]` |
| auto | 8/8 readable property records; 8/8 create+destroy success; selected types `[2]`; supported `[2]` |
| direct | 8/8 readable property records; 0/8 create+destroy success; selected types `[]`; supported `[]` |
| KI provider | DEPENDENCY_CHECK_FAILED; DEPENDENCY_CHECK_FAILED |
| Doorbell mapping | 2/2 nodes report a mapped device pointer; no NIC command was issued |
| Portable barrier patch | 8 passing correctness records; 8/8 DONE markers; proxy transport |

Per-node exit codes:

- `step-status-node1.tsv`: inventory=2, compile=0, map=0, proxy=0, auto=0, direct=1, portable=0
- `step-status-node0.tsv`: inventory=2, compile=0, map=0, proxy=0, auto=0, direct=1, portable=0

GPU NIC-NOOP follow-up: **3755312 / COMPLETED**.

`nop-3755312`: **8/8 GPUs** completed 10,000 NIC queue NOOPs. No network payload was transferred; this is not a GIN/EP8 correctness result.

Bounded GPU-issued cross-node mapped-memory put probe: **8/8 GPUs** passed. Completion events are drained after the GPU kernel. This is not a sustained-completion or NCCL GIN/DeepEP test.

Bounded GPU-issued cross-node HBM put probe: **8/8 GPUs** passed. This bounded variant drains events after the kernel; the separate counter test below checks GPU-only completion. NCCL GIN and DeepEP EP8 remain unverified.

Counter prerequisite probe: **8/8 GPUs** passed. 32768 HBM puts with GPU-polled NIC completion counters; constant payload, no signal-ordering/source-reuse or NCCL GIN proof.

Atomic prerequisite probe: **8/8 GPUs** passed. 128 GPU-issued remote HBM atomic adds per peer pair; single remote writer, no NCCL GIN ordering proof.

Ordering/source-reuse follow-up: **3756020 / COMPLETED**.

`order-3756020`: **8/8 GPUs** passed 128 changing-payload, source-poison, READY/ACK rounds using conservative delivery-complete writes. This remains a single-producer raw-CXI test, not an implemented NCCL GIN backend.


## Decomposition figure from job 3781109 — October 28

Artifacts: `results/deepep_direct_10_26/figures_3781109/ep8_latency_decomposition.{png,pdf,svg}`
and `decomposition.csv`. Reproducible script: `tools/cxi_gin/backend/tools/plot_ep8_decomposition.py`.
Separate panels show unprofiled call latency and ideal payload/25GBps floor;
profiled GPU hybrid vs copy/reduction kernel durations; and host kernel-launch
API time (median of per-rank medians, union of nested launch API intervals).
CPU launch calls total roughly 15–19us per operation; they overlap GPU work and
are not an additive decomposition of full latency. Pure NIC transfer time is
not resolved inside the hybrid kernel. No chart segment falsely labels the
whole hybrid kernel or the ideal floor as measured network-only time.

## Eight-rank dispatch instrumentation — October 28, job 3786579

User requested step-level timestamps for all eight ranks to distinguish NIC
utilization from submission, forwarding and synchronization costs. The first
campaign targets the same V4 Flash fresh-FP8-dispatch geometry: 4,096 tokens/GPU,
two GH200 nodes, private direct CXI GIN type 6, DeepEP baseline bd1e1669.

Implementation and acceptance gates:
`tools/cxi_gin/experiments/trace_v1/README.md`. Immutable submission snapshot:
`results/deepep_direct_10_26/trace_20261028/source-v3` (remote
`/iopsstor/scratch/cscs/zyu/deepep-direct-20261026/trace-20261028/sources/v3`).
The tested baseline source/release was not modified.

- Host in-memory CLOCK_MONOTONIC timestamps: stream setup, main launch,
  receive-count polling, output allocation, epilogue launch and return.
- Per-warp/lane GPU globaltimer spans: initial/final barriers, count notification,
  packing, scale-out and forwarding roles, receive-tail waits, NVLink issue,
  token puts, tail signaling and copy dependency waits.
- CXI spans: context locking, command emission and consumption, completion
  flushes, puts and signals. Existing transport ordering remains unchanged.
- Bounded trace buffers; overflow fails validation. Three captures per rank;
  all receive payloads/scales/IDs/experts/weights/counts validated independently.
- Original uninstrumented control plus tracing-disabled before/after controls.
  Tracing overhead above 20% prevents treating captured durations as quantitative
  attribution of the original 3.4 ms; targeted lighter captures then remain needed.
- CPU/GPU and cross-node clock calibration retains uncertainty. NIC telemetry
  records hardware timestamps over 600 repeated dispatches; it does not measure
  exact DMA-active intervals within one call.
- Outputs: compressed raw events, complete Perfetto trace, host and GPU stage
  CSVs, overhead controls, NIC interval rates, and an eight-rank HTML overview.

Preflight: actual instrumented hybrid-dispatch and copy-epilogue specializations
compiled for SM90a using CUDA13/GCC13 on Clariden. Six analysis tests pass locally
and with Clariden Python3.6, including missing-rank/overflow rejection and
inclusive-interval handling. First offline compiler attempt used default GCC7
and failed C++20 support; using installed GCC13 resolved it without a code change.

Submitted job **3786579**, debug partition, 2 nodes / 8 GPUs, 30 minutes.
Last observed state at submission: **PENDING (Priority)**. Native extension
build, GPU correctness, actual tracing overhead and NIC rates are not yet
validated. Detached read-only monitor:
`results/deepep_direct_10_26/trace_20261028/job-3786579/latest.txt`.
The monitor collects terminal results; it does not edit code or resubmit jobs.

Correction to the earlier decomposition visualization: V4 Flash copy-epilogue
kernel lifetimes overlap the hybrid kernel because of programmatic dependent
launch. The epilogue finishes about 45–47 us after the hybrid ends in the recorded
profile; its inclusive 46–194 us per-rank duration includes dependency waiting.
Do not add the earlier stacked kernel medians to reconstruct a critical path.
Also, 17.431 MB on rank0's RDMA rail comprises 4,035 token-sized 4,320-byte puts,
not one contiguous 17 MB operation. Aggregate size does not prove saturation.

## October 29: trace job setup failure corrected; replacement 3790260

Job 3786579 FAILED 1:0 after 1m10s. The original, unchanged EP8 control passed
on all eight ranks (8 correctness records, 32 operation records, 1,600 CUDA-event
samples). V4 Flash fresh FP8 dispatch was 3.396544 ms and BF16 combine 4.532656 ms
(median rank-max), consistent with the earlier 3.400/4.529 ms result.

Failure occurred afterward: `cp -a` attempted to preserve source directory
permissions while copying the installed NCCL headers into the private trace
runtime. The cluster filesystem returned `Invalid argument`. This was a launcher
setup failure, not a GPU correctness failure; native trace build and detailed
captures never started. The STAGE marker still said original control, so the
batch log and completed control artifacts were needed to identify the boundary.

Changed the launcher to use `copy_headers.py`: content-only copying, new
destination, no source mode/ownership/ACL replay, SHA256 verification for each
file. Local metadata-failure simulation passed; actual Clariden preflight copied
and verified all 72 headers. The installed header tree contains no symlinks.
The tested baseline release and failed job snapshot remain unchanged.

After the user renewed SSH access, submitted replacement **3790260**, debug,
2 GH200 nodes / 8 ranks / 30 minutes, immutable snapshot `sources/v4`.
Last observed state: PENDING (Priority). Detailed GPU trace results remain
pending. Monitor:
`results/deepep_direct_10_26/trace_20261028/job-3790260/latest.txt`.


## October 29: three-path dispatch timestamp campaign

Job **3790260 FAILED 1:0 after 2m30s**. Unmodified control and instrumented
native build completed; the trace workers then received SIGSEGV during startup,
before detailed captures. There is no function-level timing result from this
job. Root cause is not established. Replacement **3790547** uses sealed
`sources/v5`: faulthandler, per-rank startup markers, CPU binding before CUDA
initialization, and explicit eager NCCL process-group initialization matching
the successful baseline. These changes are diagnostic, not a verified fix.

Submitted **3790548**, debug, two GH200 nodes, eight ranks, 30 minutes, for
UCCL native CPU-proxy/CXI and DeepEP v2 NCCL CPU-proxy GIN type 2. This is held
until separately built instrumented NCCL passes. Local detached
`tools/ep_trace_threepaths/release_after_build.py` releases this job only on
build PASS; it cancels the still-held job on build FAIL or a two-hour deadline.
It does not modify other jobs. Snapshot: `ep8-threepath-trace-20261029/sources/v4`;
NCCL build: `builds/nccl-v2`. NCCL source hashes match exactly between the
snapshot and that build. UCCL remains pinned to Apertus control_fix 54ef064;
DeepEP remains bd1e1669 and private NCCL baseline 12df1a11.

Common first-stage scope: V4 Flash H4096/K6/E256, 4096 tokens/GPU, **fresh FP8
dispatch only**. Combine and other model geometries remain outstanding.
CPU/GPU raw start/end timestamps retain rank, thread/warp, operation IDs,
clock-calibration uncertainty and tracing overhead. UCCL hooks include GPU
queue publication, proxy command handling, fi_write/atomic submission, CQ
polling and observed completions, and publishing completion to the GPU.
NCCL proxy hooks include GPU credits/publication/completion waits and CPU
descriptor processing, RMA submissions/tests and completion publication.
Direct hooks include packing/staging, token puts, command-consumption and
completion waits, forwarding, barriers and copy-epilogue dependencies.
Role lifetimes are inclusive, not pure memcpy durations. Provider submission
and observed completion are not physical NIC DMA start/end timestamps.

Validation: 10 local proxy recorder/analyzer tests and six existing direct
trace tests passed; seven analyzer tests also passed on Clariden Python 3.6.
These validate tooling, not GPU execution. Full tracing above 20% overhead
requires lower-overhead targeted captures before assigning baseline costs.
UCCL uses one process group per case and exits after synchronized validation
and output writes, avoiding explicit scratch teardown/reuse; this does not
validate buffer teardown. No detailed three-path measurements exist yet.

Detached status/result collectors:
- `results/deepep_direct_10_26/trace_20261028/job-3790547/latest.txt`
- `results/ep8_threepath_trace_20261029/job-3790548/latest.txt`
- `results/ep8_threepath_trace_20261029/job-3790548/build-gate.json`

These monitors do not edit code or resubmit failed jobs.


## October 29, 13:41 CET check: all three dispatch captures collected

- **3790547 COMPLETED 0:0**, 11:51:08–11:55:12 CET (4m04s).
  Direct-GIN: 8 DONE ranks, 24 captures, correctness PASS, no GPU trace overflow.
  Offline analysis PASS; median tracing overhead 4.1%, maximum 6.2%.
- **3790548 FAILED 1:0**, 11:59:32–12:02:38 CET (3m06s), but both GPU
  stages completed: UCCL and DeepEP proxy each have 8 DONE ranks and 24 valid
  captures. Failure occurred only in the DeepEP proxy offline analyzer.
  It incorrectly required event400 (explicit GFD completion wait). Fresh hybrid
  dispatch disables flushing in its initial barrier and uses only an intra-node
  final barrier. Queue publication/credits, incoming-tail waits and CPU
  completion events were present. The analyzer now treats explicit GFD wait as
  optional and reports its absence; all other coverage gates remain enforced.
  Eleven tooling tests passed. Local reanalysis in `deepep-proxy/analysis-v2`
  passed, retaining the original raw data, snapshot and Slurm FAILED record.

Trace-disabled medians by rank, measured in the diagnostic builds:

| Path | Fresh FP8 dispatch | Median tracing overhead | Maximum overhead |
|---|---:|---:|---:|
| UCCL native CPU proxy/CXI | 1.515–1.539 ms | 18.9% | 23.6% |
| DeepEP v2 direct-GIN | 3.428–3.431 ms | 4.1% | 6.2% |
| DeepEP v2 CPU-proxy GIN | 6.598–6.608 ms | 51.1% | 54.7% |

These are full fresh-dispatch CUDA-event timings for V4 Flash, 4096 tokens/GPU,
not the earlier cached transmit-only UCCL metric. Inputs and call boundaries
are matched; library algorithms/configurations differ. Proxy traces locate
activity/dependencies but exceed the maximum 20% overhead policy, so targeted
lower-overhead captures are required before attributing baseline milliseconds.
All eight-rank timelines and inclusive stage CSVs are available locally.
Exact NIC wire-active time and a complete causal critical path are not proven.
Combine tracing remains outstanding. No trace jobs are currently running or
pending; unrelated user jobs 3791463 and 3791554 were pending and untouched.

Artifacts:
- Direct: `results/deepep_direct_10_26/trace_20261028/job-3790547/results/analysis/v4flash/`
- UCCL: `results/ep8_threepath_trace_20261029/job-3790548/results/uccl/analysis/`
- DeepEP proxy: `results/ep8_threepath_trace_20261029/job-3790548/results/deepep-proxy/analysis-v2/`
- Analyzer correction evidence: `results/ep8_threepath_trace_20261029/job-3790548/reanalysis-v2-provenance.json`


## October 29: comparative overlap and transport analysis

Reproducible analysis: `tools/ep_trace_threepaths/compare_paths.py` reads all
72 saved captures, verifies matching routing hashes per rank, and computes
merged intervals/intersections within each GPU clock. It emits
`results/ep8_threepath_trace_20261029/comparison/per-capture-comparison.csv`,
`summary.json`, and `gpu-stage-overlap.pdf` / `.png` (rank0, capture1). Plot bars
are union across warps, not an additive decomposition or proof of a causal
critical path. Missing instrumented stages are omitted rather than assigned
zero cost. CPU lanes are omitted from the plot to avoid exact-alignment claims.

Median sender-time overlap with forwarder-role lifetime: UCCL 99.94%, DeepEP
proxy 100%, direct 99.88%. Overlap includes waiting. UCCL's forwarder finishes
about0.820ms after its sender; this tail includes receiving/forwarding and is
not proven to be CPU overhead alone. DeepEP GPU packing median per token is
0.704us(proxy) vs0.608us(direct); forwarding-token median1.120us and NVLink-issue
median0.224us are the same for both. These are traced instruction-region costs,
not complete per-token delivery latencies.

Observed submission granularity differs: UCCL ~145 fi_write calls/rank,
mean119317B and median137216B, total~17.301MB including metadata. DeepEP
~4035 token payload puts of4320B, plus metadata and signals (~4039 CPU RMA iput
calls and1533 iputSignal calls). Thus UCCL has ~28x fewer write submissions;
these are API requests, not necessarily NIC packet/descriptor counts after
provider aggregation. UCCL uses24SM; both DeepEP paths64SM/129contexts, so this
is not a transport-only comparison between UCCL and DeepEP.

In the DeepEP CPU-proxy traced run, union of GPU credit waits is7.611ms within
~9.826ms hybrid duration. CPU process-descriptor union7.099ms includes RMA iput
union4.862ms and signal submission union1.718ms. CPU receive-count wait~4.850ms
overlaps GPU notify activity~4.799ms. This localizes visible stalls to queue
backpressure/submission/progress, but doesn't identify the provider's internal
cause. The51% tracing overhead prevents direct attribution of these traced
milliseconds to the6.60ms trace-disabled result.

The private direct-CXI backend serially waits for command consumption inside
emit() while holding a context lock; add_locked() flushes previous puts before
issuing the signal. Trace median per-call context acquisition48.12us,
command-consumption wait20.336us and completion-flush67.712us; respective
all-warp unions3.175ms,3.072ms,2.383ms overlap within3.447ms hybrid duration.
These expose concrete synchronization costs, not NIC wire-time estimates.
The direct trace overhead is4.1%, making it the stronger initial quantitative
case. Long final-barrier intervals include early-finished/unused warps waiting
for active workers and must not be added after the sender/forwarder durations.

Next causal checks: lower-overhead proxy tracing; provider-level breakdown of
long RMA submission calls and queue progress; controlled request coalescing;
and direct-CXI bounded in-flight command credits / batched completion checks
while retaining payload ordering and correctness gates. None of these
optimizations has been validated by this analysis.


### Latest-finishing warp analysis, October 29

To avoid equating all-warp union with the causal critical path, selected the
latest-ending sender and forwarder role separately in each of24captures/path.
Intersected wait spans from the same block/warp with its role interval and
merged overlapping lanes. Results in
`results/ep8_threepath_trace_20261029/comparison/latest-finishing-warps.json`.
Medians across captures (individual medians need not sum exactly):

| Path/role | Role duration | Observed wait union | Median wait fraction |
|---|---:|---:|---:|
| DeepEP CPU proxy, last forwarder |9.397ms|9.321ms arrival waits|99.1%|
| DeepEP CPU proxy, last sender |7.659ms|7.504ms queue-credit waits|97.5%|
| DeepEP direct, last forwarder |3.239ms|3.156ms arrival waits|97.4%|
| DeepEP direct, last sender |3.146ms|2.777ms context/command/completion waits|88.9%|

These are traced role intervals and candidate late-path blockers, not proof
that each wait is avoidable or a complete inter-rank dependency reconstruction.
Receiver waits can include useful in-flight NIC transfer. Same-warp merged
lane intervals capture exposed warp waiting but do not imply every lane is idle.
Proxy tracing overhead remains51%; direct4.1%. UCCL currently has broad
forwarder-role spans but insufficient internal wait instrumentation to report
a comparable last-forwarder wait fraction. Separate NIC-active service time
from queue residence, delayed issue, delayed signal and completion-observation
time before attributing the deficit from the payload/BW ideal.


### Ideal transport bound and rank0 routing clarification

For the current matched4K/GPU V4 Flash routing, directed rails are0<->4,
1<->5,2<->6,3<->7. Rank0 stages its own tokens and rank4-origin tokens for
NVLink delivery within node0; it does not receive original tokens from5-7
via rank4. For example, dispatch0->5 is0--RDMA-->4--NVLink-->5;
dispatch5->0 is5--RDMA-->1--NVLink-->0. Combine of rank5's expert contribution
to a rank0-origin token follows5--NVLink-->4--RDMA-->0, with reduction of
remote-node contributions before RDMA in this selected configuration.

Rank0 dispatch rail0->4:4035unique remote-node tokens*4320packedB=17.4312MB,
0.697248ms at25GB/s. Incoming4->0:4033tokens=17.42256MB,0.6969024ms.
Maximum across all8directed rails:4050tokens=17.496MB,0.699840ms.
Actual UCCL fi_write byte totals in capture0 give a maximum17.367412MB,
0.69469648ms, excluding atomic/protocol traffic. Small packing differences
mean the common conceptual floor is~0.70ms, not exactly identical bytes.
Largest directed NVLink dispatch volume in the matched routing table is
19.93248MB(0->2),0.1328832ms at150GB/s per pair per direction. Full ideal
streaming uses the maximum bottleneck service time, not a sum of complete
RDMA and NVLink batch times. Finite pipeline startup/drain, packing, memory,
protocol and synchronization costs are omitted from this lower bound.

Full duplex means take max(TX_bytes,RX_bytes)/25GB/s for each NIC, not sum;
all rails must be considered for collective completion, and shared PCIe/HBM
limits could impose another bound. Neither duplex support nor queue channels
prove actual simultaneous peak bandwidth in our runtime.

BF16 combine bound for the selected DeepEP layout:4035*8256B=33.31296MB
returning4->0,1.3325184ms; maxrail33.4368MB,1.337472ms. Combine reverses
routing but includes reduction and uses different precision, so its latency
is not expected to equal dispatch. Bounds and assumptions saved in
`results/ep8_threepath_trace_20261029/comparison/ideal-transport-bounds.json`.


### Per-rank timestamp export and source-stream waits

Exported representative capture1 for all8ranks/all3paths to
`results/ep8_threepath_trace_20261029/comparison/per-rank-stage-timestamps-capture1.csv`.
Times are relative to each rank's first recorded GPU event, not synchronized
absolute cross-rank timestamps. Includes first stage start, final stage end,
and latest-finishing warp's start/duration. Union/envelope is not additive.

Also classified event105 on each latest-finishing DeepEP forwarder by
`aux1` source-node index. Capture1 median across8ranks: proxy remote-source
wait9369.10us, local-source0.80us (one local outlier631.648us); direct remote
2633.98us, local548.46us, with substantial rank variation. Values are in
`late-forwarder-source-waits-capture1.csv`. This separates which stream is
awaited, not physical arrival from delayed signal visibility or scheduling.
The direct sender loop stages local and remote copies then issues a remote put
before advancing its next token iteration, so RDMA submission stalls can also
delay local-stream production despite independent physical NVLink links.
This is a source-supported coupling mechanism, not an exhaustive attribution
of every local arrival wait.

Rank0/capture1 timestamps(ms): UCCL notify0-.461; sender.498-.836;
forwarder.498-1.726; dispatch kernel.497-1.753. DeepEP proxy sender.069-8.403,
forwarder.069-9.551; hybrid0-9.920. Direct sender.145-3.272,
forwarder.145-3.460; hybrid0-3.464. Full CUDA-event calls include boundaries
outside these GPU intervals. All timestamps refer to traced runs; proxy
instrumentation remains a large perturbation. Current evidence is dispatch
only; combine has no corresponding detailed timestamp capture yet.


### Same-CPU request correlation: submission versus observed completion

`tools/ep_trace_threepaths/correlate_cpu.py` now joins stored CPU records within
each rank/capture, without subtracting CPU/GPU or cross-node clocks.
UCCL keys are(thread ID, WR ID), joining write submission311 to write CQ
observation314. DeepEP keys are(context ID,peer,descriptor sequence), joining
dequeue410 to credit publication413. Ambiguous pending IDs are rejected;
negative durations assert; unmatched starts/observations are reported.
Artifacts under `results/ep8_threepath_trace_20261029/comparison/`:
`cpu-request-lifetimes.csv`, `cpu-request-matching-audit.csv`,
`cpu-request-lifetimes-summary.json`.

Across24captures/path:
- UCCL:3480 matched writes, zero ambiguous or unmatched records. fi_write return
  to observed CQ completion median317.319us,p95 450.259us,max482.227us.
  Four distinct write-submitting CPU threads per rank in every capture.
- DeepEP proxy:130289 matched descriptors,zero ambiguous IDs,zero unmatched
  credit observations,3301 dequeues without credit return inside the window.
  CPU dequeue return to credit-publication start median3351.590us,
  p95 5472.443us,max6452.093us. One descriptor-dequeue thread per rank,
 129 active contexts. Unmatched requests are capture-boundary incomplete
  records, not evidence of payload loss; end-of-window matching is censored.

The two intervals have DIFFERENT boundaries, and neither is NIC wire time.
DeepEP interval includes submission, transport completion, polling and in-order
credit retirement. GPU publication-to-dequeue is not included. All numbers
are from heavily instrumented captures (proxy median51% overhead,UC19%).
Source ncclGinProxyProgress polls completions for one context, submits its
bounded batch, then visits the other contexts; it does not poll that context's
completions again inside its descriptor submission loop. Delayed revisits and
in-order credit retirement are specific hypotheses to test, not yet an
exclusive root-cause proof. UCCL has a different four-thread progress pipeline.

CPU CLOCK_MONOTONIC timestamps on different hosts do not have a shared origin
by assumption; GPU globaltimer clocks must also be aligned. Existing calibration
uncertainty (~24–159us across paths/ranks) permits coarse millisecond comparisons
but not exact submicrosecond cross-node flight-time attribution. All above
same-CPU correlations avoid this alignment uncertainty.

## 2026-10-29: Request-correlated tracing submitted for all three paths

The statement about GPU descriptor credits returned by CPU progress applies to
DeepEP v2 NCCL CPU-proxy GIN type 2. It is not a claim about all three paths.
NCCL's proxy descriptor queue is transport-independent and can also sit above
IB/RoCE; direct GPU NIC queues still have finite resources, but do not use this
CPU-returned descriptor queue. UCCL here uses its native CPU/libfabric CXI path,
not NCCL's proxy-GIN implementation.

| Job | Path | Submission state |
| --- | --- | --- |
| 3792104 | Apertus UCCL native CPU proxy/CXI | debug, pending priority |
| 3792106 | DeepEP v2 CPU-proxy GIN type 2 | normal, held for NCCL build |
| 3792108 | DeepEP v2 private direct-CXI GIN type 6 | normal, held for NCCL build |

Each job reserves two GH200 nodes for 30 minutes: EP8, V4Flash geometry,
4096 tokens/GPU, fresh FP8 dispatch, three all-rank captures, independent
payload/scales/routing/weights correctness checks, and 50-iteration timing
controls before/after tracing. This campaign does not trace combine. Baseline
DeepEP remains bd1e1669; NCCL12df1a11; Apertus UCCL54ef064.

New tools: `tools/ep_request_trace/`. Immutable snapshot:
`results/ep8_request_chain_20261029/source-v4/`; remote root:
`/iopsstor/scratch/cscs/zyu/ep8-request-chain-20261029`.
The NCCL source manifest matches the detached build at `builds/nccl-v1`.
DeepEP dispatch/copy-epilogue CUDA13/GCC13 GH200 compile preflight PASS;
three join/clock-envelope unit tests PASS; Python and shell syntax checks PASS.
UCCL extension compilation and all GPU execution remain unverified for these
new hooks until the scheduled jobs execute.

Instrumentation records:
- DeepEP source token ID -> remote request offset/context/queue sequence ->
  relay payload load -> NVLink destination/slot -> final receiver token/output.
- Proxy context progress sweeps, descriptor dequeue, first observed completion,
  in-order credit publication, and GPU credit waits.
- Direct context lock, payload command, command-consumption wait, signal and
  completion flush, with context/offset/counter identifiers.
- UCCL token-to-channel slot -> chunk -> GPU queue/sequence -> CPU work request
  -> fi_write -> CQ observation -> relay slot -> NVLink ordinal -> receiver.
  UCCL event600 is slot assignment BEFORE packing, not payload readiness.
- Receiver and relay waits, source/routing identities, overflow detection,
  raw per-rank GPU and per-thread CPU timestamps, pre/post clock calibration.

The analyzer rejects duplicate/ambiguous payload mappings and reports missing
CPU endpoints rather than inventing times. It exports payload-chains.csv,
capture-summary.csv and validation.json; raw per-function events remain in
per-rank gzip captures. Physical NIC wire timestamps are not available through
these hooks. Submission/completion observations bound parts of the transport
pipeline but are not DMA-active time. Different hosts/GPU clocks are not assumed
synchronized; cross-rank estimates retain calibration uncertainty. Drift between
calibration endpoints remains a limitation. Tracing overhead must accompany
all results, and inclusive overlapping intervals must not be added.

Root-cause tests: distinguish proxy completion/revisit/credit-retirement delay
from NIC backpressure; distinguish direct context serialization and conservative
command/completion fences from network flight time; distinguish UCCL chunk
formation/proxy/CQ delay from epoch visibility and downstream NVLink credits.
Previous traces show these waits, but do not establish an exclusive cause or
quantify the same waits in the uninstrumented execution.

Detached monitors retrieve terminal-job outputs. Build gates release only the
two named DeepEP jobs after NCCL PASS; failure or a two-hour gate deadline
cancels those still-held jobs. These monitors do not automatically rewrite code
or resubmit failed jobs. Process IDs are in submitted-jobs.json. No existing
user jobs were modified.

### Status checked 2026-10-29 16:34 CET

All three jobs remain PENDING (Priority), with zero execution time; none has
started, failed, or produced new traces. Instrumented NCCL build PASS; the two
DeepEP jobs were automatically released at 15:12 CET. All three detached
monitors are alive. Slurm currently estimates UCCL3792104 at Oct29 19:35 CET
and DeepEP3792106/3792108 at Oct30 03:20 CET; these are tentative scheduler
estimates. Full request-correlated per-rank decomposition remains pending GPU
execution and validation; earlier coarse traces are not new campaign results.

### 2026-10-29: source-guided replay of all eight direct-CXI ranks

Analyzed existing job **3790547**, not the newer request-chain campaign:
V4 Flash, 4096 tokens/GPU, fresh FP8 dispatch, three captures on all eight
ranks. New tools: `tools/ep_direct_replay/`. Results:
`results/ep_direct_replay_20261029/overview.html` (interactive timeline) and
`eight_rank_replay.pdf` (eight-rank timeline plus lock-wait correlation).
This is a trace-guided replay, not a cycle-accurate NIC simulator.

Median measurements across 24 rank/capture records:

| Measurement | Time |
| --- | ---: |
| Dispatch, tracing disabled | 3.430 ms |
| Dispatch, tracing enabled | 3.572 ms |
| Latest-finishing sender warp, inclusive | 3.146 ms |
| Union of that sender's recorded waits | 2.777 ms |
| Sender context-lock acquisition | 1.641 ms |
| Sender command-consumption wait | 0.869 ms |
| Sender completion flush | 0.279 ms |
| Latest-finishing forwarder warp, inclusive | 3.239 ms |
| That forwarder's arrival waits | 3.156 ms |

Sender and forwarder execute concurrently. These are separate medians and
must not be summed into a dispatch decomposition. Median tracing overhead
is 4.12%. The payload-only RDMA lower bound is approximately 0.70 ms per
rail at 25 GB/s; it excludes protocol/synchronization work and is not a
guaranteed attainable full-dispatch time.

New same-context attribution: **96.7%** of accumulated lock-waiter duration
overlaps another caller's confirmed ownership of that context; **82.3%**
overlaps the owner in command-consumption or completion-flush waits
(52.5% and 29.7% respectively). These are medians across captures/ranks,
weighted within each capture by waiter duration. They describe parallel
waiter time, not fractions of dispatch wall time. Ownership interiors run
from acquisition completion to the final nested operation end, conservatively
omitting the release boundary. The analyzer rejects overlapping owners.

This connects the observed lock stalls to the current implementation:
`backend/device/cxi_primitives.cuh` holds the context while `emit()` waits
for command consumption; `add_locked()` flushes preceding transfers before
issuing a signal. Competing callers cannot progress on that context during
these waits. Command consumption is distinct from payload completion.
The useful next experiment is bounded asynchronous command submission and
shorter lock ownership, preserving queue-capacity checks and payload-before-
signal ordering. The replay does not establish that all waiting is avoidable
or predict a speedup from subtracting wait durations.

All **32,275 remote-token puts per capture** match uniquely to processing on
the paired remote relay: **96,825 matches** across the three captures.
Routes are 0↔4, 1↔5, 2↔6, 3↔7; e.g. 0→RDMA→4→NVLink→5.
Relay processing timestamps occur after payload loading, not at physical NIC
arrival. Old traces lack final-receiver token identifiers and NIC active-time
events. Approximate cross-rank alignment retains calibration uncertainty
(median half-width 145.7 µs); intervening clock drift is not proven bounded.
Therefore this does not yet provide exact per-token network flight time,
physical NIC utilization, or a complete final-receiver delivery chain.

Validation: 24 captures, zero reported trace overflow, input correctness
PASS, unique token joins, and no negative source-to-relay estimates beyond
the calibration envelope. Four offline analyzer unit tests PASS. The PDF
has two pages and both figures were visually inspected. Interactive HTML
is standalone; browser execution was not tested in this environment.
Input SHA256 hashes, validation.json, per-rank-summary.csv,
context-lock-correlations.csv, and source-to-relay-token-chains.csv accompany
the figures. This analysis covers dispatch only; no new GPU jobs or transport
code changes were made for this replay.
