# DeepEP v2 direct GIN on Slingshot — 2026-10-30

The original review below is retained as historical context. Implementation and
GPU measurements are recorded in the dated sections that follow, including the
[24-hour campaign](#resumed-24-hour-optimization-campaign--2026-10-30-2327-cet).
Current scheduler/experiment records are in
`results/deepep_pipeline_20261030/campaign.json`; read the latest entries at the
end of this document for failures and active debugging.

Current checkpoint — 2026-10-31, 07:33 CET:

- Job **3810110** completed all interval16 gates4000–4011 and all context gates4100–4109.
  **129 contexts remain preferred:** the matched4K dispatch medians are1.0594ms
  with129 versus1.2004ms with257. Follow-up **3811125** is running on nid006152/nid007356;
  its active plan includes fresh qualification, private traces and raw transport probes.
- Packed interval16 dispatch is **1.061ms at4K** and **3.498ms at16K** per GPU,
  versus2.756/10.381ms for row-wise interval3. Combine remains near3.31/12.80ms.
- Zero-byte completion markers, native NIC fencing and retirement refresh are
  qualified by the recorded matrices/stress tests. The repeated-byte marker
  hazard remains rejected. Full SGLang/release qualification is still pending.
- New final-tail notification merging passed64 actual compiler templates;
  private129/257-context tracing passed6 additional templates. Neither has run on GPUs.
- Runtime logs, JIT and journals use node-local storage. Identified Lustre stalls
  are separate from GPU/NIC timings. `campaign.json`'s `current` object and
  `job-3810110/live-status-fast.json` hold the current experiment state.

Three-repeat medians of per-iteration rank-max CUDA latency, V4 Flash fixture,
`source-zero-packed-v7`, marker-zero,129 contexts, forward chunk3, tracing off:

| Tokens/GPU | Layout / interval | Fresh FP8 dispatch | Cached FP8 dispatch | BF16 combine |
|---:|---|---:|---:|---:|
|4,096|Rows /3|2.7558ms|2.7678ms|3.3129ms|
|4,096|Packed /3|2.1980ms|2.2059ms|3.3213ms|
|4,096|Rows /16|2.3761ms|2.3192ms|3.3141ms|
|4,096|Packed /16|**1.0606ms**|1.0527ms|3.3099ms|
|16,384|Rows /3|10.3807ms|10.3689ms|12.8579ms|
|16,384|Packed /3|8.6983ms|8.7089ms|12.7922ms|
|16,384|Rows /16|8.9123ms|8.9151ms|12.7595ms|
|16,384|Packed /16|**3.4981ms**|3.4908ms|12.8010ms|

[Three-repeat comparison figure](results/deepep_pipeline_20261030/job-3810110/figures/packed_dispatch_comparison.pdf)
([data](results/deepep_pipeline_20261030/job-3810110/figures/packed_dispatch_comparison.json)).
The4K dispatch payload serialization bound is **0.708ms**, excluding relay,
packet/control overhead and synchronization. Packed interval16's median4K NIC
TX window rate is **17.906GB/s**; useful RDMA payload divided by CUDA latency
is **16.684GB/s**. These have different numerators/timing scopes. Combine's
NIC TX window rate remains11.336GB/s. Do not sum TX and RX.

Companion to [10_29_DeepEP_v2_Slingshot.md](10_29_DeepEP_v2_Slingshot.md). The original
review below was documentation only. Subsequent dated entries record the actual
patches, jobs, qualification limits, failures and measurements.

## Feedback from Claude

Review date: 2026-10-30. Sources: the 10_29 document; the candidate and baseline device
headers under `tools/cxi_gin/backend/device/` and `results/deepep_async_20261029/`;
the per-gate result files of job 3795952; the GDAKI device headers under
`tools/cxi_gin/nccl-cxi-dev/src/transport/net_ib/gdaki/doca-gpunetio/include/device/`
and the GDAKI host and device adapters; `libcxi.h`, `cassini_user_defs.h`, and HPE's
`write_bw.c`, `utils_common.c` and `hip_cntr_test.cpp` under
`tools/cxi_gin/reference/shs-libcxi/`; the eight-rank replay under
`results/ep_direct_replay_20261029/`.

### 1. Verdict

Partly on the right path. The engineering process is sound and the stage-2 change is
the correct Cassini primitive for command-slot reuse. The roadmap after stage 2,
however, is a transcription of mlx5/GDAKI queue mechanics and does not use the two
Cassini mechanisms that make most of that transcription unnecessary: counting-event
threshold writeback and triggered commands. The stage order also attacks the lock
first while the measured waits are command consumption and completion flush. The
candidate should not advance to stage 3 until the combine regression is explained.

### 2. What the stage-2 change actually is

The entire change is the new header
[cxi_queue_credit.h](tools/cxi_gin/backend/device/cxi_queue_credit.h) and twelve
lines in `emit()` in
[cxi_primitives.cuh](tools/cxi_gin/backend/device/cxi_primitives.cuh). The GIN adapter
[gin_cxi.cuh](tools/cxi_gin/backend/device/gin_cxi.cuh) is unchanged since 2026-10-26.
Before: write one 64-byte command, ring, spin until the NIC read pointer reaches it.
After: check free 32-byte units against the NIC read pointer, write, ring, return.

Compared with the GDAKI reference the document cites:

| GDAKI mechanism | Candidate status |
| --- | --- |
| Lock-free slot reservation by atomic add on the reserved index | Not done; one spin lock per context held across put, signal and flush |
| Slot reuse gated on completion of the slot's previous occupant | Replaced by read-pointer credits, the correct CXI analogue (consumption-based) |
| Ordered publication by ready-index CAS, no holes | Not needed yet (single producer under the lock) |
| One doorbell per batch via atomic max of the producer index | Not done; one doorbell per command |
| Signal ordered by same-queue execution, no flush before signal | Not done; CT-GET round trip plus CSTATE before every signal |
| Per-peer queue pairs | Not done; one queue per context for all peers |
| Aggregate-requests hint skips the doorbell | Ignored |

Of the reserve, construct, publish, submit, retire cycle named in the 10_29 document,
only the retirement of command storage changed. The document labels this stage 2 and
is honest about it; the title "GDAKI-inspired asynchronous CXI backend" overstates
the delivered scope and should read "credit-based TX slot reuse".

Correctness of the change: units are consistent (write pointer and size in 32-byte
units, NIC read pointer in 64-byte units doubled, as the baseline's equality wait
assumed); wraparound to unit 8 and the empty-slot rule match the baseline; the
initial zero read pointer is handled conservatively. Two caveats:

- The claim that the arithmetic follows the installed `__cxi_cq_free_slots_check` is
  not verifiable from local files. Only the SHA-256 of `/usr/include/cxi_prov_hw.h`
  is recorded (`results/deepep_direct_10_26/login-compile/manifest.txt`); the function
  text is not. The CPU ring model asserts the formula against a capacity definition
  derived from the same formula, so it checks self-consistency, not conformance.
  Record the helper's text on the next allocation.
- Error detection reads the first 32 bits of `c_cq_status`, so it sees
  `num_write_cmds_rejected` but not `fail_command` or `return_code`. Inherited from
  the baseline, not new.

### 3. What job 3795952 shows

Recomputed from `results/deepep_async_20261029/job-3795952/results/results/*/direct/ep/`
rather than from the summary. V4 Flash, FP8, 4096 tokens/GPU, median of the
per-iteration rank maxima, four baseline samples (gates 07, 10, 11, 13) and four async
samples (08, 09, 12, 14):

| Operation | Baseline | Async | Change |
| --- | ---: | ---: | ---: |
| fresh dispatch | 3.469 ms | 3.159 ms | -9.0 % |
| cached dispatch | 3.443 ms | 3.113 ms | -9.6 % |
| combine | 4.546 ms | 5.705 ms | +25.5 % |

The three-geometry sweep (gates 13 vs 14) agrees: combine is 23 to 29 % slower in all
six model/dtype cases; dispatch moves between -8.6 % and +2.8 %. Per-rank combine
medians are uniform (baseline 4.38 to 4.46 ms, async 5.34 to 5.51 ms), so this is not
one straggler link. Host CPU usage is about 3 core-equivalents per process in both
variants, which the "CPU out of steady state" objective has not yet addressed.

The dispatch gain of 0.31 ms is about one third of the 0.87 ms of command-consumption
waiting that the replay attributes to the slowest sender (sender duration 3.15 ms,
lock waits 1.64 ms, consumption waits 0.87 ms, flush 0.28 ms). That share is plausible
for a change that removes consumption waits only.

Gate coverage: data integrity is well covered (16,384 commands per rank through
wrap, bounds, 1/2/8 producer CTAs, exact EP8 outputs, dispatcher scatter/gather). Not
covered: lock hold times under the new scheme, any traced run of the candidate
(`CXI_EP_PROFILE_STEPS=0` throughout), combine decomposition, and the CPU-free claim.

### 4. Why combine probably regressed, and how to tell

Two mechanisms fit the data; each has one discriminating experiment.

1. Code generation in the forward warps. Combine's forward warps run under a
   216-register budget (`warpgroup_reg_alloc<256 - 40>` in `hybrid_combine.cuh`) and
   `emit()` is inlined into that loop next to TMA loads and reductions. The new
   capacity loop adds live state and may spill. Dispatch issues puts from dedicated
   scale-out warps without that budget, which would explain why only combine suffers.
   Test: compile both variants with `-Xptxas -v` and compare spill/stack for the hybrid
   combine kernel, or mark the capacity loop `__noinline__`.
2. NIC queue depth. The old per-command wait paced 128 data contexts to one
   outstanding command each. With the plugin's default depth of 64, each context can
   now hold roughly 59 outstanding 64-byte commands (if the allocated ring is 128
   32-byte units), and the Cassini command scheduler may serve deep queues unevenly;
   combine's end time is bounded by its slowest channel's final flush. Test: run the
   async header with the credit threshold raised so at most one or two commands are
   outstanding. If combine returns to baseline while dispatch keeps part of its gain,
   depth is the cause and a tunable cap belongs in the design.

Context sharing is unchanged and still relevant: 129 contexts are one notify plus
128 data contexts over 64 SMs, two per SM; combine runs up to four channel warps per
SM, so two warps share one lock in CTA-sharing mode (`comm::get_qp_mode`).

### 5. GDAKI logic versus Cassini mechanisms

GDAKI is itself a hand-written GPU re-implementation of mlx5 ring mechanics because
libibverbs is host-only. libcxi is the same: `cxi_cq_emit_*`, `cxi_cq_ring` and the
credit helper are host inline C. The GPU-side CXI layer already exists in
`cxi_primitives.cuh`; what is missing is queue policy, not NIC functionality.

| GDAKI logic | IB/RoCE realisation (GDAKI code) | Cassini/CXI realisation | Backend state |
| --- | --- | --- | --- |
| Queue creation and GPU mapping | QP, CQ, DBR, UAR via DOCA verbs; rings in GPU memory; rkeys allgathered | `cxil_alloc_cmdq`, `cxil_alloc_evtq`, `cxil_alloc_ct`, `cxil_alloc_cp`; ring and doorbell page host-registered for the GPU | Done. Ring is kernel-allocated host memory; `cxil_alloc_buf_cmdq` takes a user buffer, untested with GPU memory |
| Multi-producer slot reservation | Atomic add on `sq_rsvd_index`, software | No NIC help either; same GPU atomic; 32/64-byte command units | Not done (lock) |
| Slot reuse / capacity | Poll the CQE of the slot's previous WQE | NIC writes `c_cq_status.rd_ptr` (`CXI_CQ_UPDATE_ALWAYS`); libcxi free-slot formula | Done (stage 2); cheaper than mlx5 |
| Descriptor construction | `wqe_prepare_write/_atomic/_write_inl/_read/_wait` | `c_full_dma_cmd` PUT/GET, IDC put, IDC AMO, `c_cstate_cmd`; host emit helpers are host-only | Done as device code except GET |
| Ordered publication, no holes | Ready-index CAS chain, software | Same need; NIC consumes sequentially to the doorbell pointer | Not needed under the lock |
| Doorbell and batching | DBR record + UAR write, atomic max under `sq_lock`, BlueFlame inline WQE | One 64-bit write of the write pointer; `write_bw.c` emits `list_size` commands then rings once | One ring per command; batching native but unused |
| Completion for flush | Per-WQE CQE polled by the GPU; flush waits for the CQ to pass a reserved ticket per peer QP | Counting event incremented by each command's ACK (`event_ct_ack`); read by `CT_GET` or delivered by `C_CMD_CT_TRIG_EVENT` at a threshold; writeback may live in GPU memory via `cxil_ct_wb_update` (`hip_cntr_test.cpp`) | `CT_GET` polling under the lock; threshold and GPU-resident writeback unused |
| Signal after data (strong signal) | Same-QP in-order execution; `FlushesAllPutsOnAnySignal` true | No same-queue ordering guarantee established locally; hardware route is `C_CMD_CT_TRIG_DMA` with threshold = posted count | Software flush before every signal |
| Counter after put (dependent op) | Companion QP: WAIT WQE then fetch-add (`put_counter`) | Triggered commands on the trigger queue: `TRIG_DMA`, `TRIG_INC`, `TRIG_EVENT` | Trigger queue allocated, used only for `CT_GET` |
| Atomic signal | RDMA fetch-add with sink buffer | Non-fetching IDC AMO `C_AMO_OP_SUM` | Done |
| Inline value put | Inline RDMA write | IDC put | Done |
| Get | RDMA read | `C_CMD_GET`, `use_offset_for_get` | Not done (traps) |
| Aggregate-requests hint | `SKIP_DB_RINGING` | Defer the ring | Ignored |
| Error handling | CQE request-error syndrome | `c_cq_status` fail fields, `C_EVENT_COMMAND_FAILURE`, `ct_failure` | Partial |

Where Cassini is better and the design should change rather than port:

- Threshold-triggered completion. HPE's `write_bw.c` arms one `CT_TRIG_EVENT` per
  batch (`inc_ct`) and waits for one notification (`wait_for_ct`). With the writeback
  in GPU memory, flush becomes "arm threshold, return a request, poll one word". This
  removes the repeated `CT_GET` round trips inside every signal.
- Triggered signal. A `TRIG_DMA` AMO with threshold equal to the posted count is the
  hardware form of GDAKI's companion-QP WAIT and gives payload-before-signal without
  the GPU waiting. This answers stage 6 without relying on an ordering guarantee that
  Slingshot may not provide.

Open points not settled by local sources:

- Whether restricted puts with the `flush` bit, which the backend already sets, give
  any ordering at the target. Treat ordering as absent until the Cassini specification
  says otherwise.
- Ring placement: a GPU-memory command ring through `cxil_alloc_buf_cmdq` is the only
  way to match GDAKI's layout; unproven.
- Traffic class: the backend uses best-effort default; HPE's utilities switch a queue
  to a high-rate-put profile with `cxi_cq_emit_cq_lcid`. Unmeasured.

### 6. Recommended order of work

1. Diagnose combine with the two experiments in section 4 before any further
   transport change. Add lock-hold and flush tracing to the candidate gates.
2. Replace the `CT_GET` polling loop in `flush_locked` with an armed `CT_TRIG_EVENT`
   writing back into GPU memory; make `FlushAsync`/`Wait` genuinely asynchronous on it.
3. Batch doorbells and honour the aggregate-requests hint, always ringing before a
   flush, a signal, queue pressure, or an unaggregated operation.
4. Implement signals as counter-triggered AMOs on the trigger queue.
5. Revisit the lock last; once flush is short, most lock waiting disappears with it
   (82 % of lock-waiter time overlapped the owner's consumption or flush waits).

Rough size from the existing primitives: triggered-event flush and asynchronous
request about 80 lines, batched doorbell about 30, triggered AMO signal about 40,
lock-free reservation and publication about 60.

### 7. Document-level notes on 10_29

- Headline and title should match the delivered scope (credit check, stage 2).
- Record the installed libcxi helper text, not only the header hash.
- Add `hip_cntr_test.cpp` to the implementation entry points; it is HPE's own
  GPU-side counter pattern (GPU writes to the CT doorbell, GPU polls a GPU-resident
  writeback armed by a threshold trigger).
- The "do not promote" conclusion is correct. The gating discipline, isolation and
  reporting are good and should be kept.

## Implementation campaign — 2026-10-30

The review above describes the earlier stage-2 candidate. Following the user's
instruction to patch and benchmark, a new isolated campaign is prepared under
`tools/cxi_gin/experiments/async_v2/`, with immutable snapshot
`results/deepep_async_20261030/source-v5/`. DeepEP remains pinned to `bd1e1669`.
The baseline and job 3795952's submitted sources/runtimes are not changed.

### Changes being tested

1. **Bound unconsumed TX commands per context:** limits 1, 2, 4, and 8, against
   both the original consumption-wait baseline and the previous unrestricted
   credit-based candidate. The physical ring still uses native read-pointer
   credits. This tests command pacing/fairness; it is not an RDMA completion cap.
2. **Threshold completion writeback:** opt-in `CXI_CT_THRESHOLD_FLUSH=1` replaces
   repeated CT GETs with native `C_CMD_CT_TRIG_EVENT`, using the command fields
   from libcxi's `hip_cntr_test.cpp`. It preserves blocking flush, the context
   lock, source-lifetime checks, and flush-before-signal. A second variant combines
   threshold completion with the four-command pacing limit.
3. **Evidence:** actual TX/CT ring sizes and requested depth are logged; ptxas
   register/spill reports are retained. Instrumented private builds timestamp
   both fresh dispatch and combine on all eight ranks. The trace reader derives
   layout dimensions from the device writer to prevent the earlier header-offset
   mismatch.

Holding the context lock through threshold completion is deliberate. A shared
aggregate count reaching a snapshot does not prove that snapshot's requests all
completed if later requests are allowed to increment it out of order. This first
threshold variant permits no later submissions while it waits, and permits only
one outstanding trigger/writeback. Splitting that lock or implementing truly
asynchronous FlushAsync/Wait requires an additional ordering/accounting proof.
GPU-resident queue or writeback allocation is not imposed as a prerequisite for
this experiment; the existing GPU-accessible mapping is retained.

### Campaign and success criteria

One normal allocation: two GH200 nodes, eight ranks, four-hour limit. Each rank
uses 4096 input tokens. Forty-one sequential gates cover public GIN, reset,
self-signal and negative checks, queue-wrap/source-reuse tests, threshold-path
producer contention, two reversed-order V4 Flash trials, four traced variants,
and BF16/FP8 dispatch across the V4 Flash, Qwen3 and MiniMax geometries. Combine
is BF16. Quantization and expert GEMMs are outside communication timing.

The ordinary benchmark contains no trace hooks. Separate traced builds collect
three captures per operation/rank, disabled-before/after timing controls, exact
dispatch payload/scales/routing checks and combine reduction checks. GPU events
cover context acquisition, command capacity/consumption, publication, CT writeback
and CT command consumption, dispatch packing/relay/arrival, combine contributor
wait/reduction/TMA/remote-tail wait, barriers and epilogues. CPU/CUDA profiling
provides launch and host-call observations. Analysis reports overlapping intervals
and wait unions, not an invalid sum of parallel durations. Cross-node timestamps
retain clock-calibration bounds.

NIC telemetry is sampled over repeated untraced operations. Software submission
and completion-observation timestamps are **not NIC wire timestamps**. Approximately
0.70 ms remains the V4 Flash dispatch payload-serialization lower bound at 25 GB/s;
it is not a promise that the entire fresh dispatch can attain that duration.
Compare the measured payload volume and timings, explain the residual critical
path, and do not promote a dispatch improvement that regresses combine.

The controller keeps the allocation after completion or a failed gate until STOP
or the allocation deadline, with 180 seconds reserved for shutdown. A failure
pauses execution. New immutable snapshots/runtimes and requests can be added in
the same allocation; resume first checks GPU health. It cannot extend Slurm's
allocation. The detached 30-second monitor collects live logs/results and does
not itself invent code fixes.

### Validation and submission record

Local checks passed: Python/shell syntax, four controller/trace tests, 1,044,160
queue-model states with delayed consumption and wraparound, and packaging checks
for all twelve ordinary/instrumented runtime prefixes. These are not GPU
qualification. Native SM90 compile preflight precedes submission.

SSH initially failed at `ela.cscs.ch` with `Permission denied (publickey)`. The user
renewed the certificate; access was verified at **2026-10-30 11:37:54 CET**. The
bounded access watcher was stopped in favor of the active session. Submission
and runtime status are recorded in `results/deepep_async_20261030/submitted.json`
when a job ID is obtained, with remote compile output in `remote-preflight.log`.
No new performance result is asserted here before GPU gates finish.

**Submitted:** job **3801971**, 2026-10-30 **11:43:23 CET**, normal partition,
2 nodes × 4 GH200 GPUs, four-hour allocation. Initial state: **PENDING (Priority)**.
Live collector PID **206860**; latest status is
`results/deepep_async_20261030/job-3801971/latest.txt`.

Before submission, native SM90 compilation passed for every ordinary/instrumented
GIN variant and the burst probes. The patched dispatch, combine and both epilogue
trace templates also compiled. The combine trace adds spills (216 registers,
36-byte spill stores / 112-byte spill loads for the checked V4 Flash template);
this is instrumentation evidence, not a performance result. Disabled/enabled
controls and the independent ordinary builds are mandatory for interpretation.

A launch audit found that `runtime.sh` resets `EP_JIT_CACHE_DIR`. Snapshot v5 fixes
this by setting the attempt-private cache after sourcing the runtime. Source v4
was never submitted. Its transport probe compile results were reused only after
verifying identical compiled inputs and all twelve runtime-header manifests;
see `compile-reuse.json`. No prior performance claim is revised here: the old
baseline/candidate runtime prefixes also enter the JIT signature, but their cache
locations were shared across attempts and are now explicitly isolated.

The four-hour allocation remains available after the planned sequence or a failed
gate, bounded by its deadline. The collector is read-only; automatic GPU tests
run under the controller, while code fixes require an active debugging session.

Latest check, **11:43:55 CET**: job 3801971 remains pending, now with
`QOSGrpNodeLimit` (the QOS/account group node cap), rather than priority. No GPU
benchmark has started. The collector remains active.

## Feedback from Claude on the implementation campaign — 2026-10-30 12:00 CET

Review of the "Implementation campaign — 2026-10-30" section above, of the code in
`tools/cxi_gin/experiments/async_v2/` and the snapshot
`results/deepep_async_20261030/source-v5/`, and of the job records under
`results/deepep_async_20261030/`. Job 3801971 was still PENDING (QOSGrpNodeLimit) at
10:57 UTC, so this review covers design and code only; no GPU result exists yet.
Nothing was submitted, modified or cancelled by this review.

### Verdict

A good response to the earlier feedback. The campaign turns both combine hypotheses
into one clean experiment, adds the lock/flush/combine instrumentation that was
missing, and implements the threshold flush as an opt-in variant without touching the
adapter or the ABI. I found no correctness defect in the device code. Three design
choices should be fixed before or during the run: the threshold command fields are
copied without verified semantics, a single gate failure pauses all independent
chains, and the allocation is held to its deadline after completion.

### What was built, checked against the code

- Device change: two compile-time switches in `backend/device/cxi_primitives.cuh`,
  selected per runtime prefix by `install.py` and `variants.json`.
  `CXI_TX_PENDING_LIMIT` caps unconsumed 64-byte commands per context (1, 2, 4, 8)
  through the new `cq_pending_commands` helper in `cxi_queue_credit.h`.
  `CXI_CT_THRESHOLD_FLUSH` replaces the `CT_GET` command in `flush_locked` with
  `C_CMD_CT_TRIG_EVENT`, threshold = `c.posted`, lock held, one trigger outstanding.
  `gin_cxi.cuh`, `cxi_gin_abi.h` and the host plugin are unchanged apart from the
  `CXI_QUEUE_INVENTORY` log line in `cxi_resources.cc`. The section's description of
  these changes matches the code.
- Twelve runtime prefixes: baseline, async, cap1/2/4/8, threshold, threshold-cap4,
  plus traced copies of baseline, async, cap4 and threshold. Ordinary builds contain
  no trace hooks; traced builds come from a separate `DeepEP-trace.tar.gz`.
- Evidence: `nvcc_wrapper.py` adds `--ptxas-options=-v` to every JIT compile and
  keeps the report per variant and node; `CXI_QUEUE_INVENTORY=1` logs the real
  `tx_size32`; `CXI_EP_NIC_ITERS=600` samples NIC counters over untraced operations;
  traced builds stamp lock acquisition (200), emit (201), capacity wait (202), flush
  (203), payload (204), signal (205), writeback wait (207), CT consumption (208) and
  the combine stages (130 to 141) with `globaltimer`.
- Sequence: 41 gates; smoke/burst/producer for all eight variants, then sixteen
  V4 Flash FP8 trials in forward and reversed order, then four traced runs and four
  three-geometry sweeps. From the realised durations of job 3795952 (smoke about
  110 s, burst 13 s, first EP trial about 55 s, later trials about 32 s, geometry sweep
  about 130 s) the whole sequence should take roughly one hour. The 13.5-hour sum of
  per-gate timeouts is only an upper bound.
- Hygiene: `direct_node.sh` previously honoured an inherited `EP_JIT_CACHE_DIR`, and
  the shared `runtime_cxi.sh` overwrote it, so job 3795952's attempts shared a JIT
  cache. Snapshot v5 forces the per-attempt directory. The claim that earlier results
  are unaffected is plausible because the NCCL include prefix enters the JIT
  signature, but it should be confirmed from the retained compiler reports.

How this maps to the earlier review:

| Earlier item | Addressed by | Remaining gap |
| --- | --- | --- |
| Combine hypothesis A (register spills) | ptxas reports for every ordinary and traced JIT build | None; the preflight compiled only traced kernels, the ordinary comparison arrives with the job |
| Combine hypothesis B (queue depth) | Cap ladder 1, 2, 4, 8 versus baseline and unlimited credits, reversed-order trials | None. cap1 versus baseline isolates code generation; cap1 to cap8 to async isolates depth |
| No lock-hold or flush timing | Trace scopes 200 to 208 | Traced combine spills (216 registers, 36/112 bytes), so traced timings are indicative only |
| No combine decomposition | Trace scopes 130 to 141 | None |
| Threshold-triggered flush | `CXI_CT_THRESHOLD_FLUSH` variant | Semantics risk below |
| Record the installed libcxi helper text | Not done | Still only the header hash |
| About 3 host cores per process | Not mentioned | Open |
| Batching, triggered AMO, lock-free reservation | Deferred | Agreed |

### Risks to act on

1. **Trigger command fields are copied, not verified.** `flush_locked` arms the event
   with `ct_success=1; set_ct_success=1`, taken from `hip_cntr_test.cpp`, which arms a
   trigger once per counter value. Every HPE program that re-arms cumulative
   thresholds on one counter (`write_bw.c`, `read_bw.c`, `atomic_bw.c`, `send_bw.c`,
   `loopback_bw.c`) sets only `trig_ct` and `eq` and never sets `set_ct_success`. If
   that bit means "set the counter to `ct_success` when the trigger fires", the
   counter restarts at 1 after the first flush and every later flush in that context
   waits for a threshold the counter cannot reach again; the failure would appear as
   diagnostic code 5 (writeback timeout). The burst gate performs four cumulative
   flushes per rank, so the campaign would detect this at gate 12 or 13 rather than as
   silent corruption, but it would also pause the run (next point). Mitigation: in
   `burst_probe.cu`, after each flush under the threshold variant, issue one `CT_GET`
   and record whether the count equals the threshold or was reset; if reset, either
   drop `set_ct_success` (and confirm a memory writeback still occurs without `eq`),
   or make the accounting relative per flush epoch on purpose.
2. **One failed gate pauses every independent chain.** `controller.py` waits for
   `RESUME.json` after any failure. The threshold chain occupies gates 12 to 17, before
   all sixteen timing trials; a threshold failure would block the cap ladder, which has
   no dependency on it, until a human intervenes. Either let the controller skip the
   failed chain and continue with requests whose `requires` are satisfied, or move the
   threshold gates after the cap trials.
3. **Allocation held to the deadline.** `run.sbatch` sets `CXI_KEEP_ALLOCATION=1`, so
   two GH200 nodes stay allocated until STOP or four hours after a one-hour sequence.
   That is about three idle node-hours on the shared normal partition, charged to the
   account, and it raises the same group node limit that is blocking job 3801971 now.
   Prefer STOP after the sequence completes, or the previous 45-minute idle window,
   unless a debugging session is actually in progress.

### Smaller notes

- The threshold switch is a compile-time define baked into each prefix, not a runtime
  environment variable; the section's wording ("opt-in `CXI_CT_THRESHOLD_FLUSH=1`")
  should say so.
- The threshold variant still waits for consumption of the trigger command on the CT
  queue after the writeback arrives, and still issues one trigger per `flush_locked`
  call, which happens before every signal. That is correct and conservative; the
  expected gain is the removal of repeated `CT_GET` round trips, nothing more.
- The argument for holding the lock through the threshold wait is right for a single
  shared counter: a later submission's ACK can satisfy an earlier threshold out of
  order. The standard way out, when asynchronous flush is wanted, is per-epoch
  counters (rotate two CTs per context, close an epoch at `FlushAsync`, poll its
  writeback in `Wait`). Not needed for this campaign.
- `cq_pending_commands` and the extended CPU model in `test_queue_credit.cc` are
  consistent with the credit formula, including the initial zero read pointer.
- After the job: compare ptxas spill lines for the ordinary baseline and async
  V4 Flash combine kernels first; that single comparison decides hypothesis A, and the
  cap ladder decides B. Do not read the traced combine timings as performance.

## Runtime update and response to the second review — 2026-10-30 13:31 CET

Job **3801971 started at 12:02:07 CET**, on `nid006101` and `nid007252`,
with an allocation deadline of approximately **16:02:07 CET**. Gates **01–33
passed**. Gate **34-baseline-trace failed at 12:41 CET** during JIT source parsing:
`Non-standard include: #include "device_trace.cuh"`. This was a diagnostic-source
integration error, not a dispatch payload failure or a threshold-completion timeout.
The controller paused and retained the allocation; the read-only monitor continued
collecting logs but did not repair the failure by itself.

During the active debugging session, immutable **source-v6** changes the four
DeepEP trace includes to `<deep_ep/impls/device_trace.cuh>`. Recursive traversal of
all 13 reachable DeepEP headers passed the JIT parser's include-format rule. Device
transport headers and all twelve runtime contents are unchanged from v5. The three
unstarted faulty trace requests were moved to an auditable `superseded-requests-include-fix`
directory. Independent geometry gates 38–41 are scheduled first, followed by corrected
trace requests 42–45. A resume request was published at **13:30:24 CET**, requiring
the controller's existing GPU health check. No replacement Slurm allocation was needed.

### First uninstrumented results

V4 Flash, EP8, 4096 tokens/GPU, fresh FP8 dispatch and BF16 combine. Each entry is
the median of two trial medians; each trial uses per-iteration maximum latency over
all eight ranks. All corresponding correctness gates passed. These are preliminary
results from one node pair, not full SGLang serving or final multi-model qualification.

| Variant | Fresh dispatch (ms) | Combine (ms) |
| --- | ---: | ---: |
| Original baseline | 3.399 | 4.387 |
| Previous unrestricted credit reuse | 3.144 | 5.602 |
| Cap 1 | 3.402 | 4.520 |
| Cap 2 | 3.102 | 4.602 |
| Cap 4 | 3.130 | 4.513 |
| Cap 8 | 3.147 | 4.539 |
| Threshold completion | **2.766** | **3.664** |
| Threshold + cap 4 | 2.821 | 3.884 |

Threshold completion improves dispatch **18.6%** and combine **16.5%** versus the
original baseline. It still does not approach the approximately 0.70-ms dispatch
serialization bound. The cap ladder removes most of the unrestricted candidate's
combine regression, while the ordinary baseline, async, cap4 and threshold combine
compiler reports all show **216 registers, 208-byte stack, zero spill stores and
zero spill loads**. Thus additional register spills do not explain this observed
regression; queue-depth/pacing effects have stronger experimental support. This does
not yet identify the precise NIC scheduling or waiting mechanism.

Evidence: `results/deepep_async_20261030/job-3801971/interim-analysis/` contains
`timing-comparison.csv` and the retained combine compiler-report excerpts.

### Review items: agreement and corrections

- **Trigger-field semantics:** the suggested explicit post-trigger CT_GET audit is
  useful additional evidence. The predicted repeated-flush timeout did **not** occur:
  threshold public GIN, reset/negative cases, four-epoch burst/source-reuse checks,
  producer contention and repeated EP timing all passed. The burst reached
  `posted=completed=16396` with zero diagnostics on all eight ranks. This substantially
  constrains the counter-reset hypothesis for this configuration; it is not a formal
  specification of every trigger field. Do not change the flags speculatively while
  the working variants are being compared. A direct CT_GET audit remains a follow-up.
- **Global pause:** the concern materialized for a JIT setup failure, not threshold
  transport. Independent sweeps were explicitly unblocked in the same allocation,
  with the failed trace attempts retained and corrected attempts given new identities.
  Automatic independent-chain continuation should still require drained processes
  and healthy GPUs after failures; it must not silently continue after a device fault.
- **Holding the allocation:** keeping a debugging window was explicitly requested by
  the user. The allocation is now being used for active recovery and remaining tests.
  The collector is not an autonomous code-repair agent; retained idle time must not
  be described as ongoing optimization.
- **Installed libcxi helper:** already captured, including the full header text,
  at `results/deepep_async_20261029/source-audit-20261030/cxi_prov_hw.h`, with
  `provenance.json`. The review's “still only the hash” statement is outdated.
- **Actual queue size:** live logs show `requested=1024`, `tx_size32=2048`, and
  `ct_size32=2048`. Even the raw probe's requested depth 64 was rounded to 2048
  32-byte units. The earlier hypothetical 59-command physical capacity does not
  describe these allocations; the current padded-command ring has 1019 usable
  command positions after reserved status and the empty-slot rule.
- **Compile-time switches:** `CXI_TX_PENDING_LIMIT` and `CXI_CT_THRESHOLD_FLUSH`
  are compiled into isolated runtime prefixes; setting an environment variable alone
  does not change an already compiled kernel.
- **Host CPU use:** remains a separate measurement question. Aggregate process CPU
  consumption alone does not establish CPU participation in NIC progress. The direct
  plugin still declares `needsProxyProgress=0`; identifying the remaining host work
  requires CPU-thread attribution, not relabeling this transport as CPU-proxy.

## Three-repeat token-size sweep — 2026-10-30 17:38 CET

The user requested 2K/4K/6K/8K/10K/12K/14K/16K tokens **per rank**, repeated three
times, to distinguish a fixed per-call overhead from size-dependent costs. The
previous allocation (3801971) ended at **15:59:13 CET**, so this is a new allocation.

**Job 3806153**, submitted **17:38:05 CET**, requests two GH200 debug nodes for
90 minutes. Initial status: **PENDING (Priority)**. Live collector PID **355246**.
Campaign: `results/deepep_size_sweep_20261030/`; immutable snapshot `source-v1`.
The transport and ordinary DeepEP archive are byte-identical to the qualified
threshold-completion implementation from the previous job. Only the measurement
harness and sequence change. No trace hooks or profiler are enabled.

Experimental controls:

- V4 Flash geometry, EP8, 64 SMs, 129 contexts, FP8 dispatch with FP32 scale factors;
  BF16 combine retained as a secondary control.
- Actual sizes: 2048, 4096, 6144, 8192, 10240, 12288, 14336, 16384 input tokens/rank.
- Three independent process-group runs use ascending, descending and permuted size
  orders. Routing seed stays 1 and uses the same controlled `mixed` routing as the
  previous 4K result. This is not a production routing trace.
- At every size: correctness checks, 20 warmups, 100 timed calls per operation.
  Primary metric is the median of per-iteration maximum latency across all eight
  ranks; also retain p95 and repeat variation. Cached dispatch, combine and cycle
  timings are controls. Input quantization, JIT and buffer construction are excluded.
- Every size/operation gets NIC-counter measurements over at least 600 calls, with
  a shared iteration count selected from the preceding rank-max timing to target
  at least 2.5 seconds, avoiding sub-telemetry-period windows.

Byte accounting is explicit. The current FP8 V4 input sends 4096 hidden bytes,
128 scale bytes and 96 aligned metadata bytes: **4320 bytes per remotely sent token**.
For this controlled routing every source token reaches the remote node once. The
4K per-rail payload is **17.69472 MB**, and its 25-GB/s serialization bound is
**0.7077888 ms**. This refines the earlier rounded 0.70-ms estimate; it is not NIC
wire-byte accounting including protocol overhead. Do not add full-duplex TX and RX
volumes when forming the one-direction serialization bound.

Analysis fits warmed dispatch latency `T = alpha + beta * max_rail_payload_MB`,
with separate repeat fits, R², residuals, payload effective GB/s and excess over the
serialization bound. Alpha is an extrapolated per-call intercept, not cold startup.
Beta includes per-token packing, signaling and queueing as well as NIC work; a low
`1/beta` does not by itself identify intrinsic NIC bandwidth as the bottleneck.

Using 2.766 ms at 4K solely as an illustrative anchor:

- Fixed extra overhead: approximately 2.058 ms plus payload serialization, giving
  approximately **4.89 ms at 16K**.
- Constant end-to-end effective throughput: proportional to token count, giving
  approximately **11.06 ms at 16K**.

These are hypotheses, not measured sweep results. The local postprocessor will
produce `size-analysis/size-sweep.csv`, `latency-fits.json`, a PDF/PNG figure and
`summary.md` only after all 24 size/repeat cases pass. Partial runs are labeled
incomplete. The controller retains the debug allocation on failure for inspection
and releases it after the scheduled sweep finishes. Local syntax, sweep coverage,
unchanged-source checks and a synthetic known-intercept/slope report-generation
test passed before submission.

Scheduler correction: debug partition's `debug-qos` enforces **90 total node-minutes**,
so two nodes permit at most 45 minutes, despite its 90-minute single-job wall limit.
The pending **same job 3806153** was updated to **normal, two hours** to avoid
`QOSMaxNodeMinutesPerJob` and allow compilation plus all three sweeps. It still exits
as soon as the scheduled sweep finishes. Snapshot v1's original SBATCH header is
retained for provenance; the live Slurm record and submitted.json record the override.

## Status and completed-trace analysis — 2026-10-30 18:40 CET

Live Slurm check: **3806153 remains PENDING (Priority)**; the 2K–16K three-repeat
sweep has not started. Its collector is updating `job-3806153/latest.txt`. Do not
interpret the earlier 4K results as a completed size sweep. **3801971 completed at
15:59:13 CET**. Its four multi-geometry gates (38–41) and corrected trace gates
(42–45) passed, including correctness on all eight ranks. The earlier trace compile
failure was resolved in source-v6; it does not invalidate these subsequent captures.

Ordinary, untraced V4 Flash FP8-dispatch/BF16-combine measurements at 4096 tokens/rank
(median of two trial medians, each based on per-iteration maximum across ranks):

| Variant | Fresh dispatch, ms | Combine, ms |
|---|---:|---:|
| Baseline | 3.399 | 4.387 |
| Asynchronous TX, polling CT completion | 3.144 | 5.602 |
| Asynchronous TX, pending-command cap 4 | 3.130 | 4.513 |
| Threshold completion | **2.766** | **3.664** |
| Threshold completion plus cap 4 | 2.821 | 3.884 |

Threshold completion reduces dispatch by 18.6% and combine by 16.5%. Removing
per-command consumption waits alone moves the bottleneck and regresses combine.
The independent geometry run confirms threshold benefits for V4 Flash and MiniMax;
Qwen3 dispatch improves less (1.332 to 1.285 ms), while combine improves from 4.412
to 3.671 ms. These are geometry emulations, not model-serving measurements.

### What the successful traces establish

New derived artifact:
`results/deepep_async_20261030/job-3801971/interim-analysis/trace-critical-waits.csv`.
It contains 384 rows: four variants, two operations, two roles, eight ranks and
three captures. Each row selects that rank's latest-finishing warp for the role;
wait intervals are clipped to its lifetime and unioned rather than summed twice.

For threshold completion, medians across the 24 rank/capture observations:

| Local role | Role duration, ms | Wait union, ms | Context acquisition, ms | TX capacity wait, ms |
|---|---:|---:|---:|---:|
| Dispatch sender | 2.591 | 2.187 | 1.720 | 0.034 |
| Dispatch forwarder | 2.632 | 2.552 | — | — |
| Combine forwarder | 3.430 | 3.071 | 2.747 | 0.021 |

Dispatch sender completion-flush intervals total 0.435 ms on this selected warp;
CT writeback wait accounts for 0.374 ms within those intervals. The dispatch
forwarder's wait is predominantly waiting for incoming progress. It is not evidence
that copying over NVLink takes 2.552 ms. Combine's latest warp can wait on a context
while another warp owns it and performs completion work; its own short CT-wait time
does not eliminate completion handling as a cause of lock contention.

These local role medians overlap and **must not be added to each other or to the
ordinary latency**. They do not identify NIC wire timestamps. Threshold tracing
changes dispatch from 2.791 ms (hooks disabled in trace build) to 2.990 ms (enabled),
about 7.1%; combine changes 3.655 to 3.738 ms, about 2.3%. Use ordinary builds for
performance claims and traces for diagnosing dependencies. Ordinary combine builds
show zero spills for all four variants, so register spilling does not explain the
untraced asynchronous-combine regression.

### Why a 17.7 MB aggregate still incurs many waits

`hybrid_dispatch.cuh` uses 256 scale-out channels in this configuration and
`kScaleoutUpdateInterval=3`. Each channel handles 16 tokens at 4K/rank. The kernel
issues a separate remote payload PUT per token and publishes its progress after
three tokens, plus a final update. This produces 1536 channel updates per rank,
plus two control updates. Trace counts show 4100 payload calls (4096 token PUTs
plus metadata), 1538 signal calls, and 7176 TX command publications per rank.
Three V4 FP8 rows are only 12,960 bytes, despite the 17.69472 MB aggregate payload.

The CXI backend currently ignores `ncclGinOptFlagsAggregateRequests`, rings a
doorbell per command, and implements `add_locked()` by waiting for preceding
context transfers to complete before publishing the signal, **while holding the
context lock**. Threshold completion reduces repeated CT queries but preserves
that serialization. This explains a concrete producer/consumer dependency;
the traces alone do not prove all excess latency is removable lock overhead.

### Next optimization, in order

1. **Keep the pending size sweep unchanged.** Fit warmed `T = alpha + beta*bytes`
   and examine residuals, NIC counters and all three repeats. This separates a
   roughly fixed component from size-dependent overhead without changing transport.
2. **First controlled dispatch experiment: reduce progress-update frequency.**
   Compare intervals 3/6/8/16 using threshold completion, with the corresponding
   forwarding chunk size and unchanged final notification. Retain the shared-context
   lock and ordering rules. Measure context waits, completion calls, forwarding
   starvation and untraced latency. Larger batches may delay forwarding, so success
   requires a net improvement, not merely fewer commands.
3. **Then honor request aggregation in the CXI backend.** Batch queue publication
   and doorbells, forcing publication before completion waits, signals, capacity
   waits or an operation requiring immediate progress. Test separately before
   combining it with step 2. This follows the useful GDAKI principle without copying
   mlx5-specific descriptors or assuming aggregation removes completion waits.
4. **If lock-held completion remains dominant, implement asynchronous completion
   epochs/ordered signaling.** Validate the exact CXI ordering and completion
   guarantees first. Simply releasing the lock or deleting the pre-signal flush is
   unsafe: later completions must not satisfy an earlier batch's completion test,
   and the receiver must never observe readiness before payload visibility.

For every change: public GIN semantics checks, all-rank dispatch/combine correctness,
three untraced repeats, then targeted tracing. No claim of reaching 0.708 ms is
justified yet: that number is a payload serialization lower bound, not the cost of
the complete MoE dispatch. No new optimization job was submitted during this status
and analysis review.

## Resumed 24-hour optimization campaign — 2026-10-30 23:27 CET

User renewed SSH access and explicitly requested iterative patch/test/debug work
for 24 hours. Authentication succeeds. Campaign window: **2026-10-30 23:27 through
2026-10-31 23:27 CET**. The active agent diagnoses and prepares revisions; the
detached collector only retrieves evidence, and the allocation controller executes
declared gates and pauses on failures. Each allocation has its own Slurm deadline;
holding it for debugging does not extend that deadline. Use subsequent allocations
only when required, within the authorized campaign window.

### Size sweep completed: the gap is predominantly size-dependent

Job **3806153 completed 20:55:23–21:21:02 CET**, elapsed 25:39. All 24 cases passed
correctness. Three repeats, same node pair, routing seed and threshold transport:

| Tokens per rank | FP8 fresh dispatch median, ms | Payload serialization bound, ms |
|---|---:|---:|
| 2048 | 1.486 | 0.354 |
| 4096 | 2.781 | 0.708 |
| 6144 | 4.065 | 1.062 |
| 8192 | 5.316 | 1.416 |
| 10240 | 6.601 | 1.769 |
| 12288 | 7.910 | 2.123 |
| 14336 | 9.157 | 2.477 |
| 16384 | 10.462 | 2.831 |

Fit: **T(ms) = 0.2124 + 0.14468 × payload_MB**, R²=0.9999768, maximum residual
0.0355 ms. Incremental effective throughput is **6.912 GB/s**; combine's is
**9.396 GB/s**. This is software-inclusive effective throughput, not a measured
NIC DMA limit. The warmed per-call intercept is much smaller than the approximately
2-ms excess at 4K. Merely increasing message volume does not amortize the main gap.
Complete report and figure: `results/deepep_size_sweep_20261030/job-3806153/size-analysis/`.

### First isolated patch and validation sequence

`tools/cxi_gin/experiments/pipeline_v1/package.py` prepares immutable snapshots
under `results/deepep_pipeline_20261030/`. Source remains based on DeepEP bd1e1669.
The first snapshot leaves the qualified CXI transport byte-identical and changes
only the dispatch progress-update interval and matching forwarding chunk, through
explicit JIT compiler defines recorded in compiler reports and case metadata.
Default 3 preserves prior behavior. Candidates: 6, 8, 16.

Twenty gates in one two-node normal allocation:

1. Public GIN checks at 1/4/129 contexts, including reset, self and negative cases.
2. Each interval: correctness at 257 and 4096 tokens with mixed, uniform, hot-rank,
   local-only and remote-only routing, including final partial chunks.
3. Three counterbalanced untraced repeats per interval at 4096 and 16384 tokens;
   20 warmups and 100 timed calls, fresh/cached dispatch and combine controls.
4. Separate detailed traces at intervals 3/8/16, all eight ranks, three captures.

JIT caches are private to each request so different compile-time settings cannot
reuse a previous kernel. The ordinary and traced archives retain final progress
notification and all flush/lock semantics. Local manifest, unchanged-transport,
sequence dependency, header and Python syntax checks passed before staging.

Subsequent changes will be separately qualified: honor GIN request aggregation and
batch doorbells; inspect context sharing (129 contexts versus 256 data channels);
then consider asynchronous completion epochs only with validated ordering. The
GDAKI reference maps AggregateRequests to SKIP_DB_RINGING. The CXI implementation
must use CXI queue descriptors and completion semantics, not mlx5 descriptors.

If full EP measurements leave attribution unclear, add a staged transport probe:
prepacked payload PUT plus final completion; add periodic readiness signals; add
multiple producers sharing contexts; compare with separate contexts; then compare
against packing/forwarding in full EP. Keep bytes, request sizes, concurrency and
correctness explicit. Differences between these experiments are interventions,
not additive timestamps for overlapping stages of the original kernel.

### Additional source evidence: delivery completion granularity

The existing CXI `put_locked()` sets `event_ct_ack=1` and `flush=1` on every payload
PUT. The local libfabric `prov/cxi/src/cxip_rma.c` sets the corresponding flush bit
when FI_DELIVERY_COMPLETE or FI_MATCH_COMPLETE is requested. This is distinct from
the GPU polling function named `flush_locked()` and from ringing a queue doorbell.

The clean local CLIC checkout, commit `e80f60c059e1e5f272fc630eb15d60b5b09d8391`,
contains `clic_ki_emit_flush_q()` in `src/transport/clic_device_transport.h`. Its
documented scheme uses restricted CT_SEND payloads followed by a delivery-complete
CT_ACK PUT per source endpoint/target, then waits for completion. This is a useful
CXI-specific reference for amortizing delivery completion. It is **not yet proof**
that removing per-PUT delivery completion is safe in our GIN implementation: source
lifetime, cross-queue ordering, strong readiness signals, self operations and the
actual driver/NIC contract still need validation.

The prepared `gin_stage_ladder.cu` compiles with the existing SM90 SDK and public
NCCL GIN headers. It holds 256 producer channels and 4320 bytes/token constant,
compares coalesced PUTs, row PUTs with final notification, and readiness intervals
3/8/16, and varies 129 versus 257 contexts. It validates every received 64-bit word
with rank/iteration-dependent data, records local per-channel submission/completion/
receive timestamps, and uses CUDA events for the full transfer kernel. Preparation,
validation and the host collective are outside those events; an initial GPU
readiness exchange remains inside. This is a transport intervention experiment,
not a production EP measurement. GPU execution is pending.

Ladder snapshot `source-ladder-v1` is prepared separately and has its own evidence
validator. The original allocation controller imports its validator at startup,
so these new `ladder` gates must **not** simply be appended to that controller's
request queue. Execute them through their own validated runner while the original
controller is idle, or in a subsequent allocation using the new controller/validator.
No ladder gates have been queued yet.

**Submission:** job **3809401** started at **23:35:16 CET** on
`nid005423,nid006716`, normal partition, four-hour limit. The live collector is
PID **500740**. Remote compile checks and the CPU queue model passed. At 23:35:51
the allocation was executing `01-threshold-gin`; GPU qualification of the new
intervals was still pending. Local evidence is under
`results/deepep_pipeline_20261030/job-3809401/`. A human-readable source diff is
`results/deepep_pipeline_20261030/progress-batching.patch`.

`tools/cxi_gin/experiments/pipeline_v1/run_ladder.py` is prepared to run the ladder
inside the same allocation **only after** the original controller is idle and all
its gates passed. It uses the ladder snapshot's own validator and records separate
`EXTERNAL_STATUS.json` plus per-step results, avoiding changes to the running
controller. It checks allocation time and stops on failures for inspection.

### 23:41 CET continuation: qualified control and next transport patch

Authoritative evidence in job 3809401 now shows:

- `01-threshold-gin`: PASS on eight ranks, 1/4/129 contexts, including reset,
  self-signal and negative cases.
- `02-interval3-correctness`: PASS, ten routing/size cases per rank.
- Interval 6 was running; no candidate timing claim is made yet.

Seven additional immutable requests (`60`–`66`) were queued in the same allocation:
257-context EP correctness followed by three counterbalanced 129-versus-257 context
comparisons at interval 3. `get_theoretical_num_qps()` selects the full allocated
count in this configuration. The mapping gives each of 256 dispatch channels its
own data context at 257, plus the notify context. This tests contention without
changing the transport or removing locks. Larger resource use still needs GPU
qualification; allocating more contexts is not assumed to improve performance.

The staged ladder snapshot is now **source-ladder-v2**, which includes its external
runner. Its preflight is in progress; the earlier v1 was never executed.

Prepared **source-aggregate-v1** implements a separate bounded publication change:

- Honor `ncclGinOptFlagsAggregateRequests` for payload PUTs; compare maximum batch
  sizes 1 (control), 8 and 32 descriptors.
- Force publication before a completion check, before waiting for ring capacity,
  and on nonaggregated submission. Signals still flush preceding payloads.
- Keep every payload's delivery-complete bit, context locks, and per-descriptor
  system fence. This first patch isolates doorbell amortization; it does not claim
  to remove the completion bottleneck.
- Private ABI version 2 adds pending-publication and cumulative publication counters
  inside the existing struct padding. CPU compilation verifies the 192-byte size
  and original field offsets are preserved. Host/plugin/device headers are staged
  together; existing ABI-v1 releases are untouched.
- GPU gates cover public GIN, explicitly aggregated queue-wrap/source-reuse probes,
  contention, EP correctness, and three untraced timing repeats against the unchanged
  threshold control. Cumulative command/doorbell counts are printed at teardown,
  outside the timed operation; they include all operations and reused context history.

Local snapshot/hash/syntax and ABI layout checks passed. The first remote compile
attempt failed because the login node's `/tmp` was full. It is being retried with
`TMPDIR` in a private campaign scratch directory, without altering or restarting
the running GPU job. This is an environment failure, not a GPU correctness result.
Aggregation gates have not been queued pending successful compile checks and the
first campaign's results.

At **23:43 CET**, the ladder and bounded-aggregation compile checks both passed.
Intervals 3/6/8/16 all passed ten EP correctness cases on all eight ranks, and
`06-interval3-repeat1` began ordinary timing. A **planned inter-gate hold** was
requested after that step so the transport ladder can run before completing the
remaining EP sweeps. This is an allocation-controller scheduling hold, not a failed
test or a pause of the 24-hour agentic goal.

The separately versioned control script `run_ladder_paused_v1.py` accepts this hold
only if `PAUSED.json` contains `external_ladder=true` and the controller reports
`PAUSED_FOR_DEBUG` after the current Slurm step has terminated. All already finished
EP gates must have passed; the ladder's explicit GIN prerequisite must also pass.
The executor SHA256 is saved in every ladder result. Test sources and runtime remain
the immutable, compile-qualified **source-ladder-v2**. After the ladder, an explicit
RESUME reason and the existing GPU-health check will restart the remaining EP steps.
Any ladder failure leaves the allocation available for diagnosis.

Analysis scripts now separate interval, context-sharing and aggregation experiments
so additional requests cannot accidentally be pooled into the interval repeat
statistics. `analyze_ladder.py` reports rank-max CUDA timers and local producer
timestamps, excludes five warmups, and labels missing cases; cross-node clock
synchronization is never assumed.

**23:46 CET:** the first ordinary control completed and passed: fresh dispatch
**2.7616 ms at 4096 tokens/rank** and **10.4811 ms at 16384**, with combine
3.6632/14.0644 ms. These are one repeat on the new node pair, consistent with the
earlier size sweep; they are not final three-repeat candidate results. The
controller reached the planned inter-gate hold, and the detached external executor
PID **124679** started `21-ladder-coalesced-4096` inside job **3809401**.
`EXTERNAL_STATUS.json` is the live status for this phase; the main controller's
`PAUSED_FOR_DEBUG` is expected during the scheduled transport probe. Remaining EP
and context-sharing requests are preserved. Aggregation's CPU/SM90 compile gates
passed with scratch TMPDIR, but no aggregation GPU test has run yet.

## Completed transport ladder and delivery batching — 2026-10-31 00:01 CET

The ladder finished at **23:55:50 CET**. All **20 configurations** (two token sizes,
five submission/signaling modes, two context counts) passed full payload validation
on eight ranks. Each configuration has 30 calls, with five excluded as warmup.
The ordinary EP sequence resumed through the existing GPU-health check. All 24
bounded-doorbell aggregation gates were queued in the same allocation.

Selected rank-max median CUDA times:

| Prepacked public-GIN experiment | 4K, 129 contexts | 4K, 257 contexts | 16K, 129 contexts | 16K, 257 contexts |
|---|---:|---:|---:|---:|
| Coalesced PUTs, final signal | 0.909 ms | 0.894 ms | 3.330 ms | 3.294 ms |
| Row PUTs, final signal | 2.317 ms | 2.258 ms | 9.067 ms | 8.958 ms |
| Row PUTs, progress every 3 | 2.660 ms | 2.586 ms | 10.313 ms | 10.340 ms |
| Row PUTs, progress every 8 | 2.457 ms | 2.428 ms | 9.742 ms | 9.711 ms |
| Row PUTs, progress every 16 | 2.386 ms | 2.321 ms | 9.414 ms | 9.417 ms |

Coalesced payload throughput reaches **19.46–19.78 GB/s at 4K** and
**21.26–21.49 GB/s at 16K**. Row PUTs remain near 7.6–7.9 GB/s even without
intermediate progress signals. Context doubling helps only slightly in this probe.
Thus long context waits in the earlier traces are not evidence that removing
context sharing alone will remove the latency gap. Most of this probe's gap is
associated with operating on many small requests; periodic signals add a smaller
but measurable cost. These are controlled interventions, not additive phase times.

The coalesced case has prepacked, contiguous channel data and no NVLink forwarding.
DeepEP's existing channel walks a strided input-token sequence; it cannot simply
replace its puts with one large put without also addressing source layout. Do not
report the coalesced number as complete EP performance or a transparent patch gain.

Figure: `results/deepep_pipeline_20261030/job-3809401/ladder-analysis/transport-granularity.pdf`
(PNG alongside); CSV and local channel timestamps are in the same directory.
The figure was visually checked. It includes the payload serialization bound and
the ordinary full-EP control, and states the different measurement scope.

The first interval-6 full-EP timing repeat gives 2.558 ms at 4K and 10.068 ms at 16K,
versus 2.762/10.481 ms for interval 3. These are preliminary one-repeat values;
remaining repeats are still running.

### CXI-specific hypothesis and revised candidate

Local libfabric documentation (`tools/clariden_deepep/libfabric/man/fi_cxi.7.md`,
FI_DELIVERY_COMPLETE section) explains that delivery completion performs an
unconditional target-side zero-byte PCIe read before the acknowledgment. Our
baseline requests that operation for every payload PUT. Together with the ladder,
this motivates testing batched delivery completion; it does not yet prove it is
the only bottleneck.

The first local design, **source-delivery-v1**, was **rejected before remote staging
or GPU execution**. It used a marker in a separate scratch registration. Inspection
of `cxi_memory_register()` showed that every registration allocates its own CXI
domain/PID, so such a marker did not establish the required same-endpoint ordering.
The rejection record is `source-delivery-v1-REJECTED.json` outside the snapshot.

Revised **source-delivery-v2** keeps one destination-window/peer epoch per context:

- Payload PUTs request CT_SEND rather than per-PUT delivery completion.
- Before signaling or returning completion, append a delivery-complete CT_ACK PUT
  to the **same destination PID/PTE**, repeating the final payload byte from its
  original registered source IOVA. Source lifetime extends through this completion.
- Changing destination window or peer first closes the previous epoch. Keep the
  context lock through the complete epoch so later transfers cannot satisfy its
  completion threshold.
- Both the control and candidate use batch-8 publication. Private ABI version 3
  adds pending-epoch metadata inside the existing 192-byte layout. No scratch MR,
  signal-memory resizing, or global driver change is required.
- Every marker is counted as an actual command/completion; the raw wrap-test
  validator expects the additional marker rather than normalizing it away.

This is based on the CLIC same-endpoint delivery-flush pattern, with explicit
adaptation to our registration model. GPU semantics remain unqualified. Both
variants passed CPU/SM90 compile checks, and matched public-GIN qualification
requests `06a-delivery-control-gin` and `06b-delivery-batched-gin` were queued ahead
of further timing. At 00:00:29 the control was running. No GPU timing improvement
from delivery batching is claimed yet.


**00:06 CET:** `06a-delivery-control-gin` and `06b-delivery-batched-gin`
both passed public-GIN qualification on all eight ranks (1/4/129 contexts,
28 rounds, reset, self-signaling, timeout recovery). This qualifies those API
cases, not full EP or bulk source reuse. Interval-8 repeat 1 also completed.
The main controller is deliberately held between gates while the external
executor runs 12 matched delivery-control/candidate gates in the same allocation:
raw queue wrap with source overwrite after completion, concurrent producers,
full EP routing correctness, then three counterbalanced untraced timing repeats.
The candidate-specific validator counts the extra delivery marker correctly.
`EXTERNAL_STATUS.json` is the live phase status; no GPU tests overlap.


### Delivery v2 control failure and v3 cleanup correction — 00:11 CET

Gate `103-delivery-control-ep-correctness` failed at teardown after all eight ranks
passed the first 257-token mixed-routing payload/combine check. The new early
assertion reported `pending=(nil), unpublished=0, posted=207, completed=206` and
terminated the process group. This is not a payload mismatch and is not a qualified
EP result: the remaining routing cases never ran.

`completed` is the **last GPU-observed CT writeback**, not a fresh hardware counter.
DeepEP's barrier flushes first, then sends barrier signals and waits for incoming
signals; it need not refresh the sender's cached completion count after its last
signal. The new assertion incorrectly rejected that valid baseline cleanup case.
`source-delivery-v3` removes only the cached-count equality from this early guard.
Pending software epochs/unpublished commands still fail closed; queues with unequal
cached counts remain ineligible for reuse and follow the pre-existing checked
`cxi_channel_close()` path, with all cleanup errors still fatal. No GPU data-path
code, ABI, flags, or source-lifetime behavior changed between v2 and v3.

The source diff was checked: only `backend/host/gin_plugin.cc`, sequence and
manifest differ. Both nodes passed a subsequent GPU health check. New v3 gates
200–213 repeat public GIN, wrap/source-reuse, concurrent producers, EP correctness,
and matched timing. The unstarted v2 trace requests were preserved under
`retired-requests-delivery-v2/` with their reason; they are not silently overwritten.
The allocation is retained for the corrected run.


**00:14 CET:** corrected source-delivery-v3 passed compile checks. The qualified
interval-16 repeat ran while that preparation completed, followed by the planned
hold. The corrected 14-gate delivery sequence now runs in the same allocation.
A separate traced snapshot adds event 209 (TX publication/fence/doorbell) and event
210 (enqueue the same-endpoint delivery-completion marker); completion waiting
remains event 207. Trace work is conditional on the corrected EP gates passing.

Added `ladder-analysis/transport-local-timeline.pdf` and reproducible plotting code
`tools/cxi_gin/experiments/pipeline_v1/plot_ladder_timeline.py`. It shows all eight
ranks' latest-finishing producer channel for one representative measured iteration
in each of three transport interventions. Each row has its own rank-local origin;
these are not synchronized cross-node timelines. The colored spans are sequential
on that selected channel, not sums of independent medians. Row submission includes
context/queue waits and periodic signal completion, while the final flush includes
network progress. Moving work from submission into final flush does not by itself
reduce total latency. No NIC wire timestamps or NVLink forwarding are claimed by
this prepacked probe.


The read-only collector was upgraded (PID **518947**) to report both the main
controller and external executor plus an explicit `effective_phase` in
`job-3809401/live-status.json`. A planned main-controller hold is no longer
presented as the active experiment being paused. The remote jobs, source snapshots,
and qualification policies are unchanged by this monitor update.


**00:21 CET:** corrected control gate `203-delivery-control-ep-correctness`
passed all ten cases on all eight ranks, including cleanup. The candidate is now
running gate 204 public GIN, followed by source-reuse, producer and EP checks.

Before any trace execution, local reader validation found that the strict decoder
also needed event IDs 209/210 in its event catalog. `source-delivery-trace-v3`
fixes that Python catalog; its host/device/CUDA test inputs and installed runtime
hash maps are identical to compile-qualified trace-v2. The actual decoder was
checked with the new events. Remote compile-equivalence evidence records this
explicitly rather than claiming another CUDA compilation. The unstarted trace-v2
requests were retired with their reason; new requests `09c-delivery-control-trace`
and `09d-delivery-batched-trace` require successful corrected EP gates 203/207.


### Next isolated ordering candidate: native CQ fence

Local primary source `tools/clariden_deepep/libfabric/prov/cxi/src/cxip_cmdq.c`
uses `cxi_cq_emit_cq_cmd(..., C_CMD_CQ_FENCE)` before the C_STATE and AMO when
FI_FENCE is requested. The installed Clariden header, saved with SHA256 under
`tools/cxi_gin/reference/clariden-installed-20261031/`, defines its exact 64-byte
CQ command encoding. This suggests a direct counterpart to the useful GDAKI
principle of NIC-ordered submission without a GPU polling wait per notification.

Prepared **source-hw-fence-v1**, initially unqualified. Before a strong signal it
queues the existing same-endpoint DC marker when batching is enabled, then a
native CQ fence, then C_STATE/AMO on the same TX queue. It retains per-PUT DC in
one candidate and batched DC in another. Explicit flush and counter completion
still use closed, lock-held CT observation; source lifetime is unchanged. Fence
commands do not increment transfer-completion counts. A matched software-wait
control is included. CPU preflight will compare the command builder against the
installed libcxi helper, followed by the full GPU correctness gates before timing.
The provider source motivates the test; it is not itself a hardware correctness
or performance result. No GPU CQ-fence success is claimed yet.


**00:26 CET:** delivery candidate gates 204–206 passed public GIN, queue wrap with
source overwrite after explicit completion, and concurrent producer checks. Gate
207 is running full EP correctness. The native-fence candidate is now
**source-hw-fence-v2**: v1's CPU-only descriptor test needed `<cstring>` before the
installed libcxi header. v1 never ran on GPUs. The corrected CPU comparison passed
and confirms that the GPU-used 64-byte command builder matches
`cxi_cq_emit_cq_cmd(C_CMD_CQ_FENCE)` exactly. Full CPU/SM90 preflight is running;
this encoding check does not establish NIC ordering correctness.


**00:29 CET:** delivery-v3 candidate gate 207 passed all ten full-EP cases on all
8 ranks. Matched ordinary timing gates 208–213 are running. The first control
repeat is 2.842/3.870 ms dispatch/combine at 4K and 10.699/14.736 ms at 16K; these
are one-repeat control values, not a candidate speedup. Both ordinary dispatch
builds report the same 103/124-register variants and zero register spills; the
candidate combine has a larger stack frame (296 vs 208 bytes), still zero spills.
The native CQ-fence snapshot **source-hw-fence-v2** passed CPU/SM90 preflight,
including the exact installed-helper descriptor comparison. It is ready for GPU
gates after the current sequence, but remains GPU-unqualified.


**First matched delivery timing pair (one repeat, preliminary):** at 4K, fresh
FP8 dispatch is 2.842 ms control versus 2.846 ms batched delivery; combine is
3.870 versus 3.326 ms. At 16K, dispatch is 10.699 versus 10.596 ms and combine
14.736 versus 12.864 ms. Completion batching alone has not closed the dispatch
gap. Finish the counterbalanced repeats, then run the matched prepacked ladder to
separate row PUT cost from progress-signaling cost, followed by the compile-ready
native CQ-fence gates. The latter retain delivery ordering while replacing the
GPU pre-signal writeback wait with a queued NIC dependency; correctness is still
unproven until its own GPU gates pass.


A detached, bounded phase scheduler `run_tail_v1.py` now waits for all 14 corrected
delivery gates to pass, then runs the 12-case matched prepacked ladder and the
21 native CQ-fence gates in the same allocation. Every phase uses its immutable
source and its own validators. Any missing/failed gate or allocation deadline stops
the chain and leaves the hold in place. Only after every declared gate passes does
it request the original controller's health-checked resume. This scheduler does
not infer fixes; the active agent continues inspecting results and modifying new
candidate snapshots. `TAIL_STATUS.json` records its phase.


### Completed matched delivery repeats — 00:38 CET

All 14 delivery-v3 gates passed. Median of three ordinary repeat medians:

| Tokens/rank | Operation | Per-PUT DC control | Batched delivery | Reduction |
|---:|---|---:|---:|---:|
| 4096 | fresh FP8 dispatch | 2.8420 ms | 2.8458 ms | -0.14% |
| 4096 | combine | 3.8562 ms | 3.3436 ms | 13.29% |
| 16384 | fresh FP8 dispatch | 10.7061 ms | 10.6006 ms | 0.99% |
| 16384 | combine | 14.7360 ms | 12.8534 ms | 12.78% |

These are matched batch-8/ABI-v3 variants on one node pair, not cross-allocation
replication. Dispatch improvement is negligible; combine improves consistently.
Full summary: `job-3809401/delivery-analysis/summary.md`, with per-repeat CSV in
`variant-analysis/`. The matched prepacked transport ladder started automatically
at 00:37:14. The CQ-fence candidate follows only after its declared prerequisites.

A stronger command-ABI check also passed: separate translation units compiled the
candidate with our private Cassini header and the reference with the installed
libcxi/Cassini headers, then compared all 64 command bytes. The private and
installed Cassini headers additionally have identical SHA256 hashes. Evidence is
`hw-fence-command-abi.log`; this still does not replace GPU ordering tests.


The matched native-fence trace builds also passed CPU/SM90 preflight.
`source-hw-fence-trace-v1` retains the public/ordinary source and adds event 211
for CQ-fence enqueue, alongside events 209/210 for publication/DC-marker enqueue.
The reader catalog and instrumentation transformations were checked locally.
Requests 09e/09f/09g are queued behind the full native-fence EP correctness gates
403/407/411. They will run after the external phases finish and the original
controller resumes. The trace capture records tracing-disabled before/after
latencies as well as three enabled captures per operation/rank; the ordinary
build remains the performance reference. NIC fence execution and wire transfer
are not directly timestamped by these GPU enqueue events.


### Conservative NIC credit cache candidate — 00:45 CET

The installed libcxi implementation provides a concrete optimization our device
submission loop does not yet use: `__cxi_cq_free_slots()` caches `rp32` and refreshes
the NIC-written status only below 16 free 32-byte slots (installed
`cxi_prov_hw.h:608`). Our current `emit()` reads that status for every descriptor.
This is independent of delivery/CT completion and is a plausible small-request
submission cost, not yet a measured bottleneck attribution.

Prepared immutable `source-credit-cache-v1`, based on GPU-qualified delivery-v3,
with matched `credit-control` and `credit-cached` variants. Both retain batch-8
publication, batched delivery, lock ownership, system fences, CT completion and
strong-signal ordering. Only the cached-credit switch differs. ABI4 uses the
existing four-byte gap at offset 140; context size remains 192 bytes. Initialization
uses the allocated CQ cursor, and recycling preserves it. Fresh error/status
checks occur at explicit flush boundaries in both variants. Low credits or the
optional pending-command limit force a refresh before waiting. No cached value
is treated as remote delivery completion.

The independent monotonic tagged-ring simulation passed 4,243,799 writes and
432,774 wraps across five queue sizes, four pacing limits, delayed NIC status
updates, delayed software refreshes, and initial zero/nonzero cursors. This is
host-model evidence only. Remote CPU/SM90 compilation is in progress; no GPU
qualification or speedup is claimed. The prepared sequence contains public GIN,
wrap/source-reuse, concurrent producers, EP routing correctness, a matched
transport ladder, and three counterbalanced ordinary timing repeats. It will
follow current evidence rather than alter an active source/runtime.


### Matched ladder completed; native-fence gates running — 00:48 CET

All 12 delivery-ladder gates 300–311 passed, and the scheduler started native
CQ-fence gate 400 in allocation 3809401. At 4K rows, coalesced transfer takes
0.924/0.931 ms (control/batched), row PUTs with only a final signal take
2.404/2.266 ms, and progress signaling every three rows takes 2.771/2.826 ms.
At 16K, coalesced transfer takes 3.322/3.331 ms and row PUTs with only a final
signal take 9.113/8.798 ms. These interventions reproduce much of the dispatch
gap without NVLink relay or expert computation. Completion batching helps
row-final modestly but does not help the frequent-signal case. Request granularity
and submission/completion ordering remain the leading optimization targets;
these comparisons do not isolate a NIC wire interval or an additive function
decomposition. Full tables are in `job-3809401/delivery-ladder-analysis/`.

`source-credit-cache-v1` now passed remote CPU/SM90 preflight, including both
variant public-GIN, producer, compile-probe and ladder builds, both raw wrap
probe builds, and the independent cached-credit simulation. It remains
GPU-unqualified and has not altered the current native-fence run.


### Raw probe startup failure and bounded fix — 00:51 CET

Native-fence control public GIN gate 400 passed on all eight ranks. Gate 401
failed before its first payload epoch: rank 6 reported diagnostic 30 waiting for
the initial readiness signal (`cases=0`, `posted=1`, `completed=0`). Rank 2 had
not logged CQ setup completion before Slurm killed the peer processes; ranks
0/1/4/5/7 completed their four epochs without payload errors. The failed gate
remains failed and preserved. Slurm confirmed the step drained, and both nodes
passed `nvidia-smi -L` inside allocation 3809401.

The raw harness publishes peer memory descriptors **before** allocating queues
and device descriptors. Thus one rank can enter its short GPU timeout while
its peer is still doing host/CUDA setup. This is a suspected startup race, not
proof of a network-ordering defect or proof of payload correctness on all ranks.
New snapshots `source-hw-fence-v3` and `source-credit-cache-v2` add a pairwise
host handshake after all allocations, explicit CUDA kernel loading, and device
synchronization. Setup duration is logged per rank. The GPU timeout and payload
checks remain unchanged; the host descriptor/readiness deadline is bounded at
120 seconds. Only `burst_probe.cu`, the sequence, and manifest differ from their
parents. Rebuild/compile-equivalence checks precede a distinct gate
`401b-fence-control-wrap`; existing gate 400 is reused only because its source
and installed runtime inputs are byte-identical.


Both readiness-fixed snapshots passed compile-equivalence verification and rebuilt
every selected SM90 raw-probe variant. All other source compilation inputs and
installed runtime file hashes equal their compiled parents. The new bounded
phase executor `run_followup_v1.py` (PID 157820) started at 00:55:04 CET: native
fence-v3 gates first, then credit-cache-v2 gates, then a health-checked resume of
the original queued requests. Gate 401b is running as Slurm step 3809401.57.
The original failed gate 401 is retained; successful reruns will not rewrite it.


**Corrected raw gate 401b passed at 00:55:22 CET:** all eight ranks completed
four epochs (16,384 payload commands/rank), reported zero payload/diagnostic
errors, and ended with posted=completed=16,396. Logged setup durations were
about 3.77 s on node 0 and 5.05 s on node 1 (each process's own elapsed clock;
not synchronized cross-node timestamps). This validates the corrected harness
for this run; the earlier incomplete logs do not prove every detail of the
initial startup stall. Gate 402 concurrent-producer testing is now running.


### First native NIC-fence GPU gates passed — 01:01 CET

Control gates 402 (concurrent producers) and 403 (ten EP cases per rank) passed.
The actual native CQ-fence/per-PUT-DC candidate then passed gate 404 public GIN
(1/4/129 contexts, reset/self/timeout recovery) and gate 405 queue-wrap/source
reuse, on all eight ranks. The raw gate covers 16,384 payload commands/rank.
Gate 406 is now checking concurrent producers. These are bounded correctness
results, not yet complete EP qualification or a performance improvement.

Prepared `prepare_release_checks.py` for the eventual measured candidate. It
requires three ordinary, qualified repeat gates for the exact source/variant/
context/progress configuration before generating 24 follow-up requests: separate
FP8/BF16 correctness processes for V4 Flash/Qwen3/MiniMax fixture geometries,
three counterbalanced geometry timing repeats, the 2K–16K V4 Flash sweep repeated
three times, and actual SGLang scatter/gather plus reduced-width expert smoke.
The prepared delivery-v3 request set is **not submitted**; it exercises the
preparation path using an already measured candidate and will be regenerated
for the selected transport after current comparisons. SGLang smoke is not full
model serving or TTFT qualification.

Separate correctness processes also bound CT-resource lifetime: gate 403's
service inventory reported 1,294 CTs in use after ten buffer constructions even
when only four software channels remained allocated. Cached final completion
state can make those channels ineligible for reuse; this observation does not
yet establish the precise driver-side release mechanism. Track it separately
from timed transport and avoid a single oversized multi-geometry lifecycle test.
The ordinary result analyzer now keeps experiment families separate, so size
sweep repeats will not silently merge with geometry or transport repeats.


### Native fence/per-PUT-DC EP qualification and NIC counter audit — 01:03 CET

The `fence-dc` variant passed gates 404–407: public GIN, raw wrap/source-reuse,
concurrent producers, and ten EP cases per rank on all eight ranks. EP covers
257/4096 tokens with mixed/uniform/hot-rank/local/remote routing and exact dispatch
payload/metadata plus combine-reference checks. This supports the translated
NIC-ordering mechanism for this matrix. It is not universal ordering proof or a
speedup claim. The combined `fence-batched` variant is starting gate 408.

Added `analyze_nic_windows.py` and audited telemetry deltas/timestamps for qualified
ordinary repeats. For the completed delivery-v3 comparison, median TX rate per
port is 6.729 versus 6.754 GB/s for fresh FP8 dispatch, and 9.782 versus
11.258 GB/s for combine (control versus batched delivery, three repeats).
TX bytes per call are 19.110 versus 19.208 MB for dispatch and 35.877 versus
35.903 MB for combine. Thus combine's rate gain is accompanied by nearly equal
traffic volume, while dispatch's rate barely changes. RX remains separate in
the tables; TX and RX are not added.

These are independent 600-call counter windows, including protocol/control
traffic and synchronization. Their ms/call values differ from the separate
100-call CUDA-event samples and must not be substituted for those latency
measurements. Counter-window rates do not reveal instantaneous link occupancy
or isolate wire time. Evidence: `job-3809401/nic-analysis/{summary.md,ports.csv,repeats.csv}`.


### Next isolated hypothesis: NIC credit-writeback policy — 01:08 CET

Source audit found another difference from the production CXI path. Our host
allocator selects `CXI_CQ_UPDATE_ALWAYS` for both the TX command queue and CT
trigger queue. The installed `uapi/ethernet/cxi-abi.h:274` says ALWAYS updates
status whenever the hardware read pointer advances, whereas HIGH/LOW_FREQ_EMPTY
also update when the queue empties. The checked libfabric CXI default in
`cxip_info.c:638` is LOW_FREQ_EMPTY for endpoint queues; `cxip_cntr.c` keeps
ALWAYS for counter command queues. This suggests testing amortized NIC credit
writebacks in addition to cached GPU reads. It does not establish that those
writebacks are currently the limiting cost.

Prepared `prepare_cq_policy.py` and a **host-only preview**, with no GPU snapshot
submitted. `CXI_TX_CQ_POLICY` accepts always/high_empty/low_empty, defaults to
always, logs the actual enum values, and rejects other values. TX queues may
use the selected policy; the CT trigger queue explicitly retains ALWAYS.
Pooled channels must match the requested policy. Device ABI, CT completion and
strong-signal behavior are unchanged. The preview passed the installed-header
policy check and compilation of the full modified host resource allocator.
Evidence: `cq-policy-preview-preflight.log`. The first transformation attempt
was rejected locally because a replacement also matched a different queue's
allocation; the corrected transformation is specific to the TX channel site.
No active runtime was changed. The installed ABI header and hash are saved in
`tools/cxi_gin/reference/clariden-installed-20261031/`.

The running fence-batched candidate has passed public GIN, wrap/source-reuse,
and concurrent producers; gate 411 is testing its full EP matrix. Finish the
current matched timing comparisons before selecting a parent for the policy
experiment, then require policy-specific inventory evidence and the same
correctness gates before comparing performance.


**Both native-fence variants are correctness-qualified for the declared matrix.**
Gate 411 completed successfully at 01:09:26 CET, validating the combined
NIC-fence/batched-delivery path on all eight ranks and ten EP cases per rank.
All prerequisite public-GIN, raw wrap/source-reuse and concurrent-producer gates
also passed. The executor started ordinary gate 412, followed by the remaining
counterbalanced timing repeats through 420. These tests use 4K/16K tokens per
rank and unchanged routing/progress settings; no performance result is inferred
from the correctness-run timings.


### First native-fence timing pair — preliminary, one repeat

Gates 412/413 passed with ordinary timing data. At 4K tokens/rank, control versus
native fence with per-PUT DC gives fresh dispatch **2.8413 vs 2.6849 ms** and
combine **3.8345 vs 3.8096 ms**. At 16K, fresh dispatch is **10.7233 vs
10.4829 ms** and combine **14.7341 vs 14.8342 ms**. These are one-repeat
observations; the remaining counterbalanced repeats and combined batching
variant are pending. The provisional gain is modest and does not close the
payload-serialization gap.

The independent 600-call NIC windows show the same dispatch direction: TX rises
from 6.716 to 7.221 GB/s per port with unchanged 19.110 MB/call. Combine TX is
9.737 versus 9.859 GB/s, also with unchanged 35.877 MB/call. Do not merge these
window measurements with the separate CUDA-event latency samples.

Hardened live analysis after observing that rsync can collect FINISHED.json before
its summary/data files. Ordinary and NIC analyzers now exclude missing/incomplete
collected matrices explicitly, rather than crashing or counting a partial case as
a repeat. Existing completed results were re-analyzed successfully. This changes
local reporting only, not the GPU runs.


### Combined native-fence result and next isolated policy test — 01:23 CET

The first two ordinary repeats of native fence plus batched delivery agree at
4K: fresh dispatch **2.8181/2.8156 ms**, combine **3.3316/3.3324 ms**. This retains
the combine gain, but largely loses the modest dispatch gain of native fence
with per-PUT delivery completion. At 16K the combined variant is about
10.59–10.60 ms dispatch and 12.85–12.97 ms combine. These remain partial repeats;
do not combine independent patch gains or select a winner yet. Gate 416 is
running in the same held allocation, followed by the remaining repeats through
420 and then the cached-credit qualification phase.

Prepared and staged `source-cq-policy-v1`, a separate immutable snapshot of the
correctness-qualified native-fence/batched-delivery implementation. Both arms
use the same GPU code and differ only in host TX CQ allocation policy:
ALWAYS versus LOW_FREQ_EMPTY. CT queues retain ALWAYS. Every rank must report
the expected TX and CT policy before the gate can pass. This tests whether
NIC read-pointer writeback frequency adds avoidable work; it is a hypothesis,
not an established bottleneck. Gates 600–619 cover public GIN, queue wrap/source
reuse, concurrent producers, full EP correctness, matched transport ladders,
and three ordinary timing repeats. They require the parent correctness gate and
all three parent timing repeats. Staging/compilation does not submit these GPU
tests, and does not alter the currently running source or scheduler.

The current priority is to finish these isolated queue/completion comparisons
and collect their existing detailed traces before restructuring the DeepEP
packing layout. The transport ladder already demonstrates that this direct CXI
path can reach roughly 21 GB/s for large contiguous transfers. It also shows
that small row requests retain a substantial cost even with only a final signal.
Moving the same bytes therefore does not guarantee the same achievable rate:
request processing and required visibility/ordering operations must be measured.


**TX policy preflight passed.** `source-cq-policy-v1-preflight.log` records
successful host resource compilation, SM90 public-GIN/producer/ladder/device
probes, all raw-probe fence/delivery combinations, the CQ-fence descriptor check,
and the policy parser test. Local checks verified exact identity of all GPU
transport files, both DeepEP archives, and the ABI header against the qualified
parent. The evidence validator rejects missing GPU inventories and incorrect CT
policy. No GPU policy run has started, and the current allocation is unchanged.


**Pre-submission schedule correction:** the immutable native-fence sequence
orders its third round as 418 fence-dc, **419 fence-batched**, 420 control.
The prepared policy snapshot accidentally named its dependency
`420-fence-batched-repeat3`, which does not exist. No policy test was launched.
Its embedded sequence is retired; use the separately hashed
`prepared-cq-policy-v1-sequence.json` and its provenance sidecar. The package
generator now derives the four prerequisites from the parent's actual sequence
and verifies that all dependency edges resolve before execution. This correction
changes no source/runtime binaries and does not require GPU requalification of
the parent. Current Slurm execution and its existing schedule are unaffected.


### Native CQ-fence comparison complete; cached credits running — 01:31 CET

All nine ordinary timing runs (412–420) and the preceding correctness gates
passed on eight ranks. The executor automatically advanced to
`source-credit-cache-v2`, starting gate 500 in the held allocation. The main
controller still reports its intentional external-executor hold; the job is
actively testing GPUs, not paused for lack of access.

Medians of three counterbalanced repeats, milliseconds:

| Variant | 4K fresh FP8 dispatch | 4K combine | 16K fresh FP8 dispatch | 16K combine |
|---|---:|---:|---:|---:|
| Matched control | 2.8413 | 3.8485 | 10.7233 | 14.7341 |
| Native fence, per-PUT delivery completion | 2.6804 | 3.8456 | 10.4547 | 14.8342 |
| Native fence plus batched delivery completion | 2.8181 | 3.3324 | 10.5982 | 12.8814 |

Native fencing alone reduces dispatch by **5.66% at 4K / 2.51% at 16K**, with
no useful combine gain. The combined variant reduces combine by **13.41% /
12.57%**, while dispatch improves only **0.82% / 1.17%**. The gains do not add.
None approaches the 0.7078 ms 4K rail-payload serialization lower bound. All
results use one node pair; a fresh-allocation replication is still required.

Independent NIC windows support the direction of the changes: 4K fresh-dispatch
TX is 6.716 / 7.226 / 6.886 GB/s per port for control / fence / fence+batch;
combine TX is 9.685 / 9.838 / 11.262 GB/s. These include protocol/control bytes
and separate 600-call measurement windows; they are not instantaneous NIC
occupancy or the exact CUDA-event intervals in the table.

The two-point dispatch slope remains about 6.7–6.8 GB/s of incremental useful
payload across these variants. This is descriptive, not an eight-size fit of
the new patches. It reinforces testing per-request submission costs before
claiming the remaining gap is fixed startup overhead. The cached-credit test
isolates repeated GPU reads of NIC status; the prepared writeback-policy test
isolates NIC status publication. If these fail to recover the row-PUT gap,
consider a separate EP8-specific packing/coalescing experiment, retaining the
same routing, payload, progress intervals and completion semantics. That would
change DeepEP's source staging layout and request granularity, so it must be
reported separately from a transport-only patch and pass irregular-size/routing
correctness checks before timing. No coalescing kernel patch has been made yet.

Full repeat ranges and gate identities:
`job-3809401/native-fence-analysis/{summary.md,summary.json}`, generated by
`summarize_fence.py` after the complete qualified matrix was collected.
NIC audit: `job-3809401/nic-analysis/`. Device traces are queued after the
cached-credit phase; no new per-stage trace result is asserted here.


### EP8 packed-row dispatch prototype — prepared, not GPU-qualified

The qualified transport ladder motivates a separate request-granularity test.
Prepared `source-packed-rows-v2` from the native-fence/batched-delivery parent.
The entire CXI backend/ABI and combine implementation remain unchanged. A
compile-time switch controls only hybrid-dispatch source staging and PUT size:
each sender channel packs remote-bound rows contiguously into its own slice of
the existing send allocation, then submits that range immediately before the
existing progress-tail notification. Routing, metadata, row bytes and notification
cadence are unchanged. With interval 3, most remote submissions carry three rows
instead of one; final partial batches are explicitly flushed before the finish
notification. This is an EP8/two-scale-out-node prototype, not a generic transport
optimization or a result yet.

Channel slices use the exact prefix of their strided input capacities, avoiding
padding beyond the original allocation for irregular sizes such as 257. The
independent CPU ownership/layout test passed 6,020,400 channel cases, 10,156,230
remote rows and 4,811,071 batches. Those tests prove model/layout properties,
not GPU memory visibility or payload correctness. A static audit caught the
no-destination-token mask corner case in v1 before GPU execution; v1 is retired.
V2 adds an explicit remote-mask write guard and a dropped-token routing test.
The GPU sequence requires irregular sizes, FP8/BF16, local/remote/uniform/hot-rank
routing, dropped-token cases, then three matched ordinary timing repeats. Existing
per-row tracing is explicitly disabled for this prototype until its relocated
PUT instrumentation is adapted; prior trace events must not be misinterpreted.

Host/primitive preflight proceeds separately from actual dispatch-template
compilation. The first template compile exposed the login node's default GCC
7.5, which cannot handle the required C++20 dialect. The revised checker uses
the installed GCC 13.3.1 explicitly and retains failed compiler logs. This is a
preflight environment issue; no GPU run has failed and no running source changed.


### Cached credits qualified; packed-row compile preflight complete — 01:44 CET

Authoritative FINISHED records for gates **500–507** all report return code 0
and PASS. Both ABI4 control and cached-credit variants passed public GIN
(three context configurations), raw queue wrap/source reuse (16,384 payload
commands per rank), concurrent producers (three configurations), and the full
EP matrix (ten cases per rank), on all eight ranks. Gate 509 is now comparing
the cached variant's coalesced transport case. This establishes correctness for
the declared matrix; the matched ladder and ordinary timing series are unfinished.
No cached-credit performance gain is claimed yet.

`source-packed-rows-v2` completed host/primitive/model preflight and all **32**
actual SM90a dispatch-template compilations with explicit GCC 13. The matrix is
fresh/cached × FP8/BF16 × 32/257/4096/16384 tokens × packing off/on. All compile
reports show zero spill stores/loads. At 4K, packing changes fresh FP8 register
use from **124 to 146**, cached FP8 from **103 to 128**; BF16 changes 120→146
and 96→128 respectively. Reduced PUT count therefore has a GPU resource cost
that must be measured. No packed-row GPU gate has run and no speedup is implied.

The source audit confirms that the ordinary DeepEP archive changes only
`hybrid_dispatch.cuh` and adds its small packed-channel index helper. All eleven
CXI host/device/ABI source files and the combine implementation are unchanged.
The inherited trace archive is unchanged and prohibited by this prototype's
runner to avoid misleading per-row instrumentation. Reviewable artifacts:

- `packed-row-dispatch-v2.patch`: kernel/helper diff against the pinned parent.
- `packed-rows-source-audit.json`: changed/unchanged source inventory.
- `packed-rows-preflight/`: failed default-compiler evidence and successful
  checker-v2 template logs/manifest/PASS.
- `packed-rows-compiler-summary.csv`: all 32 register/spill reports.

Finish the cached-credit comparisons and collect the already queued native-fence
traces before selecting the next GPU phase. The prepared packed-row and TX-policy
experiments remain separate, with their own correctness gates. Prefer whichever
intervention the completed evidence supports, and combine changes only after
measuring them individually. Continue in the existing allocation when its
remaining wall time permits; preserve incomplete work for the next allocation.


### Next experiments scheduled within the held allocation — 01:47 CET

Queued immutable `post-trace-plan-v1.json`: after cached-credit repeats and all
five delivery/native-fence traces pass, hold the main controller at a GPU-step
boundary, then run `source-packed-rows-v2` (its correctness gates before timing),
followed by `source-cq-policy-v1` using the corrected external sequence. No new
Slurm allocation was requested and no current GPU step is interrupted. Each
phase uses its own source validator; failures remain held for agent diagnosis,
and insufficient remaining wall time defers work rather than weakening checks.
After all scheduled phases pass, the original queue resumes through its GPU
health check.

The detached scheduler is PID **266599** on **clariden-ln001.cscs.ch**, verified
with a live process listing. The `clariden` alias reaches different login hosts,
so an absent PID on a different host is not proof of process termination. Runtime
status/log: `POST_TRACE_STATUS.json` / `post-trace-executor.log`. The existing
cached-credit executor remains the only active GPU-step owner. Its first 4K
coalesced pair is 0.9320/0.9296 ms (18.985/19.035 GB/s control/cached), a negligible
change in this probe; small-row and full-EP comparisons are still pending.


**First small-row cached-credit pair:** at 4K with only a final notification,
control/cached takes **2.2436/2.2329 ms** (7.887/7.925 GB/s). Along with the
unchanged coalesced pair, this does not support repeated NIC-status reads as
the dominant cause of the row-PUT gap in these probes. The 16K, frequent-signal
and full-EP comparisons are still required; do not extrapolate a final result.

Release-check preparation now selects an exact experiment family when multiple
arms share a compiled variant, and preserves packing, TX policy, SM count and
forward-chunk settings from the qualified repeats. It rejects inconsistent
settings and dropped-token diagnostics as ordinary serving prerequisites.
This prevents a later SGLang/geometry campaign from silently reverting to the
default transport settings. A dry run against the qualified native-fence arm
prepared `prepared-release-checks-fence-dc` (24 requests, **not submitted**).
Selection of the final candidate remains pending.

### Additional source audit: command publication mechanisms

The installed CXI header also exposes `cxi_cq_ll_ring` and 64/128-byte low-latency
command-write regions (`cxi_prov_hw.h:671–815,1537–1539`). Our direct backend
currently maps the command-memory queue and ordinary write-pointer doorbell;
it does not use those low-latency regions. The local GDAKI/DOCA source contains
regular doorbell and BlueFlame command-push functions (`doca_gpunetio_dev_verbs_qp.cuh:420–474`).
This is another mechanism to audit if command publication remains dominant.
It is not evidence that NCCL's default GDAKI path always uses BlueFlame: its
handler is configured as AUTO, and the ordinary submit dispatcher has distinct
regular-doorbell/no-doorbell-record/proxy branches.

Do not translate the CPU low-latency-ring helper into scalar GPU MMIO writes
without establishing GPU mapping, transaction-width, ordering and wrap behavior.
The CPU helper's write-combining assumptions and the GPU's cooperative/TMA
command-push mechanism are different. No low-latency command-push patch or GPU
test has been made; finish the currently scheduled measurements and use trace
evidence to decide whether this additional transport change is justified.


**All three 4K cached-credit transport pairs are collected (6/12 ladder cases).**
Control/cached latencies are 0.9320/0.9296 ms for coalesced transfer,
2.2436/2.2329 ms for row PUTs with final notification, and 2.8644/2.8253 ms
for row PUTs with progress every three rows. The corresponding reductions
are about 0.3%, 0.5%, and 1.4%. These small changes do not recover the large
coalesced-versus-row gap. The 16K ladder and three full-EP timing repeats remain
active; results are in `job-3809401/credit-ladder-analysis/summary.md`.

### Where context contention moves the wait — 01:57 CET

The transport-ladder analysis now includes boundaries over **all 256 producer
channels**, rather than only the channel that finishes last. For each rank and
iteration, the origin is its first ready channel; submission ends after every
producer returns from its payload-PUT/periodic-signal loop. These markers do not
prove that every descriptor has already been published: request aggregation can
defer publication. The tail also contains final signal, flush/completion and peer
readiness, so it is not an isolated NIC transfer interval.

For the original, qualified `source-ladder-v2` row-PUT/final-notification probe:

| Tokens/rank | Contexts | Rank-max CUDA ms | All-submission span ms | Tail after last submission ms |
|---:|---:|---:|---:|---:|
| 4096 | 129 | 2.3170 | 1.5598 | 0.6475 |
| 4096 | 257 | 2.2576 | 0.2090 | 1.9656 |
| 16384 | 129 | 9.0675 | 6.1015 | 2.4201 |
| 16384 | 257 | 8.9577 | 0.7453 | 7.9066 |

Doubling contexts removes sharing between producer channels and greatly shortens
the submission envelope, but reduces total latency only about 2.6% at 4K and 1.2%
at 16K. Much of the observed wait moves into completion/readiness instead of
disappearing. This argues against treating the sum of context-lock wait durations
as recoverable latency. It supports testing larger requests and the completion
mechanism separately, as already scheduled. It does **not** establish whether the
remaining tail is NIC command processing, delivery acknowledgement, deferred
publication, or remote progress; the new traces must distinguish those causes.

The envelope columns are medians over rank/iteration-local measurements; the
CUDA column is the median of rank maxima. They must not be added or treated as a
clock-aligned eight-rank trace. In particular, the submission duration of the
latest-finishing channel alone cannot stand in for the submission time of every
producer. Updated evidence: `ladder-analysis/summary.csv` and
`local-channel-times.csv`. The analyzer also rejects incompletely copied gates
until all eight rank files and all channel records arrive.

### Request-count scaling in the completed cached-credit ladder

All twelve ladder cases are now locally collected and qualified. Holding payload
bytes, 256 producer channels, 129 contexts and final-only notification constant,
the coalesced probe uses 256 PUTs/rank; the row probe uses one PUT/token/rank.
For ABI4 `credit-control`, the additional elapsed time divided by additional PUTs
is almost identical at the two sizes:

| Tokens/rank | Coalesced ms | Row PUTs ms | Extra PUTs | Extra elapsed µs / extra PUT |
|---:|---:|---:|---:|---:|
| 4096 | 0.932032 | 2.243648 | 3840 | 0.34157 |
| 16384 | 3.342912 | 8.854176 | 16128 | 0.34172 |

The cached-credit arm gives 0.33940 and 0.33501 µs/extra PUT respectively.
These are effective marginal costs in a concurrent transport probe, **not**
measurements of a serial NIC service time or of one GPU instruction/function.
Changing request size also changes publication/completion behavior. Still, the
agreement across sizes strengthens the request-granularity explanation and
justifies the already queued packed-row experiment. It does not justify applying
the coefficient unchanged to full EP with periodic signals, packing and NVLink
forwarding. The packed-row test will measure that directly.

`analyze_trace.py` is ready for the queued traces: it requires complete qualified
eight-rank captures, reports recording-disabled before/after versus enabled
timing, and computes clipped per-category and combined wait unions on each
latest-finishing sender/forwarder warp. On the previous baseline capture it
reproduces all 96 existing role durations and wait unions. Recording-disabled
instrumented builds remain separate from ordinary-build performance.

### Sustained cached-credit failure and recovery — 02:01–02:03 CET

Gate **521-credit-cached-repeat1** stalled after the 16K correctness record and
before the first 16K timing record. All eight ranks recorded PASS for both 4K
and 16K correctness; the 4K timing records exist, but no 16K timing operation
completed. Source inspection shows an additional cycle check before timing, so
the current records cannot distinguish that dispatch from fresh-dispatch warmup
or timed calls. Logs show NVLink
barrier timeouts on node 0 and missing remote dispatch tails/metadata on node 1.
These are downstream symptoms; they do not establish the initiating fault or
prove that cached credit arithmetic is its cause. Short correctness gates and
the twelve transport probes therefore do not qualify this candidate for sustained
EP use. Its partial timing data is excluded from the qualified comparison.

Stopped only Slurm step **3809401.98**, preserving the source, logs and failed
FINISHED record (return code 137 after cancellation). The external executor and
follow-up scheduler stopped on failure. All eight GPUs then reported 0% use and
13–54 MiB allocated; the allocation remains live. Gates 522–525 are not run.
The cached-credit candidate is quarantined pending a reproducer/diagnosis;
it is not carried into any subsequent optimization or serving qualification.

The new traces, packed-row and NIC writeback-policy experiments all use earlier,
independently qualified ABI3 sources, without cached credits. Resume those via
the main controller's GPU-health check. Replaced the waiting post-trace scheduler
with **PID 106150 on clariden-ln001.cscs.ch**, immutable
`post-trace-plan-v2.json`. The previous plan/status are retained. The new plan
requires the successful control repeat and all five traces instead of the
unfinished cached-credit repeat; all actual candidate parent correctness and
timing dependencies remain unchanged. This does not turn the failed gate into
a pass or relax its validator. Scheduler log: `post-trace-executor-v2.log`.

### Trace decoder packaging repair — 02:06 CET

`09c-delivery-control-trace` stopped after the first capture with decoder
`AssertionError (..., ..., 209)` on all ranks. The timestamps were ordered;
the active event-name dictionary omitted the new TX-publication event.
`package_delivery_trace.py` had updated `runner/trace_capture.py`, but the
benchmark imports the sibling `backend/tests/trace_capture.py`. No new transport
failure is inferred from this reader assertion, and the incomplete trace is not
promoted as evidence.

Prepared immutable decoder repairs `source-delivery-trace-v4` and
`source-hw-fence-trace-v2`. Both active and runner maps now include 209/210/211.
GPU archives, transport source and private runtime contents must remain
byte-identical to their parents; `preflight_decoder_update.py` verifies that
equivalence and exercises valid new events, reversed timestamps and unknown
events. Local decoder checks passed for both packages. The generator now copies
the updated reader into the active import location, preventing recurrence.

Replacement requests are `09c2` through `09g2`, with `-decoder` suffixes. Preserve
the failed `09c` result and retire its request plus the four unrun incompatible
trace requests; never overwrite old results. `post-trace-plan-v3.json` names the
new trace prerequisites and retains all packed-row/CQ-policy correctness gates.
The v2 waiting scheduler was stopped before this replacement.

Also staged `source-credit-debug-v1`, a diagnostic-only reproduction of the
cached-credit failure. Its GPU archives, transport host/device/ABI sources and
both runtime manifests match `source-credit-cache-v2` byte-for-byte. It adds
host entry/return markers around the extra cycle check and warmup/timed calls,
plus a thread reading the existing mapped diagnostic page every 100 ms. The
observer never calls CUDA or submits NIC work. Its timings are diagnostic and
must not be used as ordinary performance; requests are not named as repeats.
Both zero-error and injected-error observer tests passed, as did remote host/
SM90 primitive preflight. A GPU reproducer remains to be scheduled separately.

Both decoder-repair remote preflights passed. The five replacement requests are
installed and the main controller has been asked to resume through its GPU
health check. The old request files and their hashes are retained under
`retired-requests/decoder-209/`; failed result `09c` remains untouched.
Post-trace scheduler **PID 6825 on clariden-ln001.cscs.ch** now follows
`post-trace-plan-v3.json`, waiting for `09g2-fence-batched-trace-decoder`.

### Dependent follow-up allocation — 02:11 CET

Submitted **3810110**, two GH200 nodes in `normal`, four hours, with dependency
`afterany:3809401`; it cannot overlap the current allocation. Its immutable
host-only `controller-followup-v1` starts with the previously qualified
`source-hw-fence-v3/fence-batched` public GIN, wrap/source-reuse, producer and EP
correctness gates, followed by three ordinary 4K/16K timing repeats. It then
holds for further debugging within the requested campaign window. This provides
fresh-allocation qualification; whether Slurm assigns a different node pair
must be recorded when it starts. No new GPU source was introduced for this job.

Submission and dependency are recorded in `submission-followup-v1.json`; the
read-only collector writes `job-3810110/live-status.json` and `latest.txt`.
Follow-up tests retain source/sequence manifests and stop on failure. Select and
qualify additional packed-row/CQ-policy/geometry/SGLang work from actual results;
do not transfer old PASS records into the new allocation as if rerun there.

### Prepared request-size follow-up, conditional on packed-row results

`prepared-packed-intervals-v1-sequence.json` contains 24 dependency-checked gates,
**not staged or submitted**: row PUTs versus packed PUTs at progress intervals
8 and 16, each with irregular/4K/dropped-token correctness and three timing
repeats. It requires the pending interval-3 packed-row qualification and all six
matched baseline/packed timing runs. Select this follow-up only if those results
justify it; do not silently combine it with the queue-policy experiment.

For this all-remote-bound mixed fixture, source-derived per-rank counts are:

| Tokens/rank | Progress interval | Packed payload PUTs | Remote tail signals |
|---:|---:|---:|---:|
| 4096 | 3 | 1536 | 1536 |
| 4096 | 8 | 512 | 768 |
| 4096 | 16 | 256 | 512 |
| 16384 | 3 | 5632 | 5632 |
| 16384 | 8 | 2048 | 2304 |
| 16384 | 16 | 1024 | 1280 |

These counts cover the dispatch sender loop's payload/tail operations, not all
metadata, barriers or NIC commands. With 256 channels, packed PUT count is
`256*ceil((tokens/256)/interval)`; the original final finish notification is
unconditional, so tail signals are `256*(floor((tokens/256)/interval)+1)`.
When the last periodic update lands exactly on the last row, a separate finish
signal still follows. This is a potential later optimization, but no finish-
signal suppression patch has been made. Counts explain why larger PUTs alone
need not reach the final-only coalesced probe's latency.

### First repaired trace collected: delivery control

`09c2-delivery-control-trace-decoder` passed all eight ranks, three captures each
for fresh dispatch and combine, with payload correctness and zero trace overflow.
Recording-disabled before/after latency is 2.8748/2.8720 ms for dispatch and
3.8636/3.9068 ms for combine; enabled latency is 3.2055/3.9853 ms. Recording adds
about 12%/3% relative to the disabled instrumented build. Ordinary-build timings
remain the performance reference.

For the latest-finishing sender/forwarder warp per rank/capture, medians are:

| Local selected role | Duration ms | Wait union ms | Context-lock wait ms | CT-writeback wait ms |
|---|---:|---:|---:|---:|
| Dispatch sender | 2.6241 | 2.2580 | 1.4811 | 0.4672 |
| Dispatch forwarder | 2.8019 | 2.7242 | 0 | 0 |
| Combine forwarder | 3.4999 | 3.1687 | 2.8185 | 0.0346 |

The dispatch forwarder's wait is remote/local tail arrival, rather than its own
GIN context acquisition. On the selected dispatch sender, pack scopes total a
local union of about **0.0099 ms**, actual TX-publication scopes **0.0401 ms**,
and inclusive tail-signal scopes **2.2310 ms**. Its remote and local signals are
both represented. The selected dispatch forwarder's NVLink-copy scopes cover
about **0.0055 ms**; this is the instrumented copy-issue scope, not an independent
measurement of physical-link serialization.

These local stage scopes overlap and their medians cannot be added. In particular,
the rank-wide TX-publication union is 2.2258 ms because publications from many
warps span the pipeline; attributing that whole union to one sender would be
wrong. Its own publication union is only 0.0401 ms. Likewise, a context-lock wait
can reflect another producer's completion wait; it is not all intrinsic lock
overhead that disappears when context count increases. The remaining repaired
traces will test how native fencing and batched completion change those waits.

Evidence is under `09c2-delivery-control-trace-decoder/trace-analysis/`:
`timing.csv`, `critical-role-waits.csv`, `critical-role-stages.csv`, and
`stage-observations.csv`. All clipped stage unions are checked against their
selected role duration. No cross-node timestamp equality or NIC wire timing is
assumed.

### Repaired batched-delivery trace

`09d2` also passed all eight ranks with all captures complete. Disabled before/
after fresh dispatch is 2.8719/2.8697 ms, enabled 3.2031 ms: essentially unchanged
from the control capture. Combine is 3.3811/3.3988 ms disabled and 3.3782 ms
enabled. The slightly lower enabled combine value is variation, not evidence
that tracing has negative cost. Ordinary three-repeat comparisons remain primary.

On the selected combine forwarder, median role duration decreases from
3.4999 to 3.0244 ms, combined wait union from 3.1687 to 2.6633 ms, and context-lock
wait from 2.8185 to 2.4631 ms. Dispatch sender/forwarder waits remain large.
This supports the earlier measured combine improvement while reinforcing that
delivery batching alone does not address the dispatch bottleneck. These are
separate per-capture local medians, not an additive causal attribution.

`compare_traces.py` is prepared to generate matched timing bars and per-role
stage heatmaps after all five repaired captures are qualified and analyzed.
It requires all five gates and the three corresponding ordinary timing repeats;
it will not fill missing variants with inferred values.

### Linking lock waiters to context owners on the same GPU

The existing trace carries the context pointer in events 200–205 and 207–211.
Source inspection confirms that the payload/signal/emit/flush/publication scopes
execute while holding that context lock. `analyze_lock_owners.py` intersects each
selected role warp's event-200 interval with another warp's lock-held scopes on
the **same context pointer, same rank and same capture**. This needs no cross-node
clock assumption. Combined coverage removes nested overlap and reproduces the
independently computed lock-wait union for all 96 selected role observations.

| Variant / selected role | Lock wait ms | Known owner work overlap ms | Owner CT-writeback wait overlap ms | Unclassified lock interval ms |
|---|---:|---:|---:|---:|
| Delivery control / dispatch sender | 1.4811 | 1.4423 | 1.0980 | 0.0391 |
| Delivery batching / dispatch sender | 1.7482 | 1.6867 | 1.2900 | 0.0397 |
| Delivery control / combine forwarder | 2.8185 | 2.7768 | 2.6475 | 0.0395 |
| Delivery batching / combine forwarder | 2.4631 | 2.4200 | 2.2569 | 0.0423 |

These local medians show that much of the apparent lock cost is a producer
waiting behind **another producer's completion observation**, especially for
combine. The lock itself is not a separate multi-millisecond operation to remove.
The unclassified remainder includes uninstrumented ownership and acquisition/
publication gaps. This identifies a software dependency; it still does not
separate NIC command handling, transfer, remote delivery and writeback inside
the owner's CT wait. Nor does it prove the wait disappears when locking changes.
Native-fence captures and the request-granularity intervention test those next.

Per-rank records and individual waiter/owner/context pairs are preserved in each
gate's `lock-owner-analysis/`. Categories overlap; median columns are not an
additive decomposition.

### Native trace validator repaired — 02:24–02:27 CET

`09f2` completed its GPU process with return code **0**, all payload checks and
all 48 captures, but the old controller rejected native dispatch because its
generic rule required events 203/207. Native NIC fencing deliberately removes
that GPU flush/writeback wait before dispatch signals. Event **211** is present
instead. Combine still includes explicit completion handling and records 203/207.

The new `validate_trace.py` checks actual variant definitions: all paths require
the common queue/payload/role events; native paths require 211; batched-delivery
paths require 210; GPU flush/writeback events remain mandatory for non-native
dispatch and for combine. It also checks all eight ranks, three captures per
operation, zero overflow, timestamps, payload qualification and disabled timing
summaries. Rechecking `09f2` passed; `REQUALIFICATION_REVIEW-v1.json` records that
review and the hash of the untouched original rejection. Negative tests reject
missing 211 for native fencing, missing 203/207 for the control, and missing 210
for batched delivery.

Fresh attempts **09f3** and **09g3**, with `-validated` suffixes, verify the entire
execution/qualification path under `run_external_v2.py`. The old failed and
unrun request files are retained in `retired-requests/native-trace-validator/`.
No GPU source or transport binary changed for this correction. Future trace
packages now include the configuration-aware controller helper as well as the
correct active decoder.

Stopped the old waiting scheduler and replaced it with **PID 203535 on
clariden-ln001.cscs.ch**, `run_ready_plan_v1.py`, immutable **ready-plan-v4.json**.
It owns an explicit held-allocation pause and runs the two native trace attempts,
then packed-row correctness/timings, then the corrected CQ-policy sequence.
It stops on failure or insufficient allocation time, and resumes the original
queue only after every declared phase passes. Status/log:
`READY_PLAN_STATUS.json` / `ready-plan-v4-executor.log`. Job 3810110 remains
pending on the current allocation's completion.

### Native fencing moves the dispatch bottleneck downstream

Fresh attempt **09f3-fence-dc-trace-decoder-validated** passed all correctness,
capture and configuration-aware checks. Recording-disabled fresh dispatch is
2.6793/2.6810 ms before/after, with enabled latency 2.8921 ms (about 8% recording
overhead). Compare its selected-role medians with the matched fence-control
capture `09e2`:

| Traced dispatch observation | Fence control ms | Native fence ms |
|---|---:|---:|
| Sender role duration | 2.6194 | 0.8004 |
| Sender wait union | 2.2147 | 0.4409 |
| Sender context-lock wait | 1.5411 | 0.4011 |
| Sender CT-writeback wait | 0.4639 | 0 |
| Forwarder role duration | 2.7953 | 2.3958 |
| Forwarder arrival-wait union | 2.7164 | 2.3216 |

Native fencing does remove most of the sender's observed blocking: signal scopes
shrink from 2.2231 to 0.3557 ms. Yet the operation as a whole remains much slower
than payload serialization. The native forwarder still waits for arriving tails/
data, while the sender can issue its work much earlier. These are local role
durations with overlapping lifetimes, so their difference is not a measured
wire-transfer tail.

The result supports moving the next optimization toward request/notification
granularity and NIC queue/completion processing, rather than pursuing context
lock removal as if all its wait were independent overhead. It does not isolate
wire time from NIC-fence execution, command processing, delivery or tail
publication. The packed-row and queue-policy interventions test that distinction.
Combine retains explicit completion handling: its selected forwarder's 2.8585 ms
lock wait still overlaps another owner's CT wait for 2.6846 ms, consistent with
native fencing alone giving little ordinary combine improvement.

### Next source-backed transport candidate: reuse unchanged IDC state

The installed `cxi_cq_emit_c_state()` helper emits a 32-byte setup command
(`tools/cxi_gin/reference/clariden-installed-20261031/cxi_prov_hw.h:1002`). The
local libcxi `utils/atomic_bw.c` emits CSTATE once during allocation/setup
(around line 126), then its bandwidth loop issues repeated IDC AMOs (around
line 249) without repeating CSTATE. Our `state_locked()` currently emits setup
before every signal/inline value, padded to 64 bytes by our generic emitter.

This provides a concrete next candidate after the queued interventions: reuse
unchanged IDC state under the existing context lock, emitting a new setup whenever
any relevant state field changes. The current variable fields are index extension,
write LAC, CT and EQ identifiers; the checked ABI widths are 5/3/11/11 bits.
Their combined key plus a valid bit fits the unused 32-bit context padding, but
any implementation needs a new explicit private ABI version and matched control.
Constant restricted/flush/event flags must also remain accounted for. Preserve
state correctly across healthy context reuse and invalidate it for fresh queues.

This caches programmed IDC state, **not TX consumer credits**, and must not
inherit the quarantined cached-credit candidate. No patch or GPU qualification
has been made yet. Validate alternating windows/peers, source reuse, wrap,
concurrent producers and sustained EP before interpreting timing. The code audit
does not establish how much elapsed time redundant CSTATE commands currently cost.

### Five-way trace comparison complete; packed-row GPU tests active

All five repaired trace configurations now pass payload, all-eight-rank capture,
zero-overflow and configuration-aware event checks. Plots (visually checked) and
CSV are in `results/deepep_pipeline_20261030/job-3809401/trace-comparison/`:
`dispatch_fresh-trace-comparison.pdf` and `combine-trace-comparison.pdf`.
Each plot separates ordinary three-repeat timing, instrumented recording-disabled
timing, and recording-enabled timing. The stage heatmaps are nonadditive local
GPU intervals, not a measurement of NIC wire occupancy.

The final native-fence + delivery-batching capture gives dispatch disabled
2.8172 ms, enabled 3.0807 ms; ordinary median is 2.8181 ms. Its sender role lasts
0.9058 ms, while the forwarder arrival-wait union is 2.6271 ms. Combine disabled
is 3.3479 ms, enabled 3.3188 ms, ordinary 3.3324 ms; the small enabled/disabled
inversion is run variation, not evidence that instrumentation speeds up the code.
Its combine forwarder lock wait is 2.2788 ms, overlapping another producer's
CT wait for 2.0821 ms. The standalone native-fence configuration remains faster
for dispatch, while batching helps combine. Their benefits are not additive.

Job 3809401 has moved to `800-rows-irregular-correctness` in the packed-row matrix.
This is the control arm, followed by candidate correctness before timing. The
allocation remains held for debugging; job 3810110 waits on its completion.

### IDC command-state reuse candidate prepared (GPU-unqualified)

`source-idc-state-v1` implements the previously audited CSTATE reuse as a separate
transport intervention based on `source-hw-fence-v3`. Both arms use private ABI5,
native fencing, batched delivery, and the same existing TX credit checks. The
candidate skips only an unchanged IDC setup command under the context lock;
new state is emitted after any index-extension/LAC/CT/EQ change. The command's
constant fields remain identical. DFA and remote offset stay in every IDC
operation. Fresh queues start with an invalid key; healthy queue reuse preserves
both hardware state and its key. No cached-credit code is inherited.

The helper's lossless field key and ABI layout passed one million randomized
transition checks against the installed command bitfields, including changed-field
and invalid-range cases. Remote host/SM90 compilation is in progress. This is not
GPU correctness or performance qualification. The prepared 900–927 sequence
requires the next allocation's baseline gates, then tests public GIN/window
changes, wrap/source reuse, concurrent producers, FP8/BF16 routing correctness,
sustained 16K EP, a matched transport ladder, and three ordinary timing repeats.
It has not been scheduled yet. Implementation/generator:
`tools/cxi_gin/experiments/pipeline_v1/prepare_idc_state.py` and
`package_idc_state.py`.

### Packed-row control gate 800 failed; allocation retained for diagnosis

At 02:38 CET, `800-rows-irregular-correctness` produced NVLink barrier tag-6
and remote dispatch-tail timeouts. All eight ranks had passed payload/cached/
combine correctness for 32-token mixed, uniform, hot-rank and local routing.
All eight recorded all four timing operations through hot-rank routing, but none
recorded a local-routing timing result. This places the stall after the local
correctness record and before its first fresh-dispatch timing record; the extra
cycle check versus warmup/timed calls is not yet distinguished.

**Packing was disabled.** This is a control-path failure, not evidence that the
packed-row candidate failed. The 257-token cases and candidate gates did not run.
Stopped only Slurm step `3809401.109`, preserved return code 137/FAIL and all logs.
The ready-plan executor stopped, as designed. Both nodes subsequently showed all
GPUs idle with 15–55 MiB allocated; job 3809401 remains held for debugging.

Prepared `source-packed-debug-v2` with read-only mapped-diagnostic polling and host
phase markers, including separate entry/return for dispatch/combine inside the
extra cycle check. GPU/transport/runtime inputs are unchanged. It first isolates
32-token local routing, then repeats the original five-route progression. These
are diagnostic runs, not ordinary performance samples. The initial local package
v1 was incomplete because the validator insertion anchor differed; v2 fixes the
host-only generator and v1 was never staged. Remote preflight is pending.

The diagnostic v2 snapshot passed source/runtime byte-equivalence and Python
syntax checks. Started its external executor **PID165078 on clariden-ln004**,
`packed-debug-v2-executor.log`, inside job3809401. Gates850/851 use bounded
12-minute steps and stop on failure. The old ready-plan executor is stopped;
there is one GPU test owner. The normal collector remains active for this job
and the dependent next allocation.

IDC-state v1 remote preflight completed successfully at about 02:42 CET: both
private runtime arms, host resource code, SM90 public-GIN/producer/compile/ladder
probes, raw wrap probes and the million-case state-key test compile/pass.
`source-idc-state-v1-preflight.log` retains the evidence. GPU scheduling remains
held until the existing tiny-token control timeout is understood; compilation
alone does not establish correctness or speedup.

### Isolated tiny-token replay passed; checking timing-sensitive reproduction

Gate850 passed all eight ranks: 32-token local routing alone completed payload,
cycle, fresh/cached dispatch and combine checks/timings; all observers stopped
normally with no GPU diagnostics. Gate851 then completed the original five-route
progression (final qualification still pending at this entry). This does not
resolve gate800: a history-dependent or timing-sensitive issue remains possible.

Prepared ready-plan-v5 with three follow-ups: diagnostic 32-token routes across
seeds1/2/3, the same sequence with the ordinary harness, then ordinary 257-token
routes across seeds1/2. The two source/runtime sets remain unchanged. Each step
has its own dependency and failure stop; the plan holds the allocation at the end
rather than automatically resuming the unrelated older queue. The new runner
v2 adds this explicit `resume_original:false` option; earlier immutable executor
versions and failed evidence remain intact.

Gate851 is now fully qualified PASS: all eight ranks completed all five routes,
with clean observer termination and no diagnostic code. Started ready-plan-v5,
**PID42753 on clariden-ln004**, using `run_ready_plan_v3.py`. Gate852 is live;
853/854 follow sequentially. The first launch check ran before851 had finalized
and correctly refused to start anything; it was retried only after PASS and no
active GPU steps were confirmed. The new held/resume behavior passed local
positive tests for both choices and rejection of a non-boolean setting. The
staged v2 runner was never used; v3 adds early flag validation.

Gate852 passed all15 route/seed cases on each rank with no diagnostic errors.
Gate853 now repeats the same32-token matrix using the ordinary harness, followed
by257-token control854. The original800 failure remains unresolved.

Prepared a lower-perturbation observer in `source-packed-debug-v4`. Main-thread
markers append to a bounded host-memory queue; a separate read-only thread
flushes records every100ms and reads existing GPU diagnostic pages. It never
submits NIC work or calls CUDA. Local tests preserved10000 ordered markers,
verified no submitting-thread file writes, and exercised diagnostic-code reporting.
Overflow or writer failure prevents qualification. GPU timings remain diagnostic.
Unique gates855/856 are sustained32/257-token replays (three seeds,20warmup,
100timed calls). They are not scheduled yet; source/runtime equivalence is being
checked remotely. Prepared v3 reused oldgate names and was retired before staging;
v4 uses new identities. No transport or GPU source changed.

### NIC packet/queue telemetry available for the next controlled measurement

Read-only inspection of both allocated nodes found all eight CXI ports at
`BS_200G` with **link MTU2112 bytes**, as reported by `cxi_stat`. Installed
counter definitions and per-port inventories are preserved with hashes under
`tools/cxi_gin/reference/telemetry-20261031/{nid005423,nid006716}/`.
`nic-counter-catalog-v1.json` selects20 additional counters available on every
port: frame types/size bins, DMA PUT and CQ-fence command counts, IDC command
pools, ordered/unordered request packets and hardware stall cycles.

The installed definitions identify `cq_cq_oxe_num_stalls` as cycles blocked by
full OXE flow queues, `cq_cq_tou_num_stalls` as missing TOU command credits,
`oxe_stall_idc_cmd_no_deq` as IDC dequeue arbitration stalls, and
`oxe_stall_hdr_arb` as header arbitration waits. These are NIC-domain cycles,
often unions across internal engines. Do not add them or equate them to GPU
wait milliseconds without the clock/domain semantics. DMA PUT opcode counts
exclude IDC operations (the description explicitly notes Errata3194).

The configured MTU makes packetization another measurable part of the gap
between large contiguous transfers and thousands of4320-byte rows. It does
**not** by itself explain the measured slowdown. Next telemetry windows should
capture these counters alongside existing octets, then compare rows/coalesced,
control/native-fence and state-reuse variants with identical workloads. No such
operation-window counter result has been collected yet; this entry records
capabilities and definitions only.

### Ordinary controls passed; sustained buffered replay running

Gate853 passed all15 ordinary32-token cases per rank. Gate854 passed all10
ordinary257-token cases per rank. The original800 timeout is still preserved and
unexplained; successful retries do not establish its cause or erase it.

Started ready-plan-v6 with **PID120033 on clariden-ln003**. Gates855/856 use the
buffered observer with20warmup/100timed calls per operation and three routing
seeds, first32then257tokens. The plan holds the allocation on completion.

Prepared (not launched) ready-plan-v7 to continue unrun packed-row gates801–811
only after ordinary controls853/854 and sustained buffered855/856 all pass.
Its separate immutable sequence replaces the failed800 prerequisite with those
explicit controls; failed800 remains FAIL. All GPU/transport/settings stay the
same. Declared bounds are15minutes for correctness and8minutes for timing,
with the existing three-minute allocation reserve. For context, successful
native-fence timing gates412–420 took112–168seconds each, and recent ordinary
control853 took91seconds. These bounds leave substantial margin while avoiding
an idle final25minutes caused by the old universal1500-second limit. Any timeout
still fails the gate; no result is accepted merely because the allocation ends.

### NIC-window harness prepared with unchanged GPU code

`source-nic-telemetry-v1` adds the20 source-described counters to separate
600-operation NIC windows for fence-control, fence-dc and fence-batched at4K.
It preserves the ordinary CUDA-event loop and the original octet records, and
writes extra snapshots/deltas to `nic-extra-node{0,1}.jsonl`. Each counter uses
its own hardware telemetry timestamps; boundary read spans are also recorded.
The qualifier requires all80 port/counter combinations, both nodes, all four
operations, and independently recomputed deltas. Resets, nonpositive periods
and nonfinite values fail qualification. Local synthetic parsing/delta/window
checks passed; remote source/runtime equivalence is in progress. Gates1000–1002
are prepared, not yet run.

The local libcxi `cxi_stat.c` uses a1GHz system-clock constant for HNI pause
percentages. That is useful context but is not yet evidence that every selected
CQ/OXE stall counter can be converted to critical-path milliseconds. Keep raw
cycles/counts separate until their domains and overlap are established.

### 2026-10-31 03:06 CET — sustained control failed; observer repaired

Gate855 (`source-packed-debug-v4`, PACK_ROWS=0) failed with GPU timeouts and
SIGABRT at03:03. All eight ranks had passed the first32-token mixed-route
payload/cached/combine checks, but no timed-operation record completed. Node0
reported the next-dispatch NVLink entry barrier (tag6, counter208, three local
ranks waiting for the fourth); node1 reported forwarding waits for remote empty
channel finish signals. This is a control failure, not evidence against the
unrun packed-row candidate. Gate856 and packed continuationv7 remain unrun.
The executor stopped normally, retained FAIL, and left both allocated nodes idle.

The buffered observer has a limitation: a blocking Python/C++ call can retain
the GIL, preventing its Python writer thread from draining queued phase markers.
Seven ranks' files therefore ended at `case_start` despite their later correctness
PASS records; rank3 had flushed through fresh-dispatch timed call78. Those stale
file tails do not identify the other ranks' execution position.

`source-packed-debug-v5` preserves GPU/transport/runtime bytes and writes phase
markers to a bounded64MiB local tmpfs journal before entering each call. An
independent stdlib-only subprocess copies it to shared storage every100ms.
Existing read-only GPU diagnostic polling remains advisory and may be GIL-delayed.
No observer component advances CUDA or NIC work. Local tests preserved10000
ordered markers and demonstrated copying while the parent held the GIL for800ms.
Remote source/runtime equivalence passed. This is diagnostic timing only.

Started held ready-plan-v8, PID108704 onclariden-ln002, gate857:32-token mixed
route, three seeds,20warmups/100timed calls. Gate858:257-token five-route matrix
follows only if857 passes. Both are bounded900seconds; plan retains the allocation.
NIC telemetry source-v1 also passed remote source/runtime equivalence; its GPU
measurement gates1000–1002 remain prepared, not run.

### Delivery-marker destination mutation: a concrete correctness hazard

Source inspection found a semantic hole in the experimental batched-delivery
path. `delivery_flush_locked()` repeats the final payload byte from its original
source to the original destination, with flush/CT_ACK enabled. That is unsafe if
the receiver consumes and clears a self-describing notification before the
sender flushes. DeepEP hybrid dispatch does precisely this with rank/expert
counts: `recv_and_reduce()` waits for encoded positive readiness, reads the
count, then clears the destination. These metadata PUTs use the same provider as
token payloads. A late repeated byte can resurrect part of an already-cleared
counter. No source-lifetime violation is needed. This is a source-level hazard;
it is not yet proven to be the cause of gate800 or855.

Prepared `source-marker-probe-v1`: matched nonbatched control, the current
one-byte replay marker, and an experimental zero-byte PUT delivery marker on the
same destination PID/PTE. HPE libcxi `utils/send_bw.c` explicitly emits a
zero-length DMA PUT, which supports testing command legality but does not itself
prove restricted delivery-completion semantics. The zero-byte candidate still
needs GPU tests for legality, ordering, payload completion, queue wrap and EP.

The new public-GIN microprobe uses separate data and handshake contexts. Each
receiver waits for a four-byte self-describing value, clears it, and acknowledges
the clear. Only then does the sender flush. After both flushes, the receiver
checks whether zero was preserved. The old replay diagnostic explicitly expects
`0xff000000` corruption; that expected-negative outcome is evidence of the hazard,
not transport correctness qualification. Control and zero-byte candidates must
preserve zero. Repeat100times on all eight ranks. Ordinary GIN payload tests
precede this diagnostic. Preflight is in progress; no mutation-probe GPU result
has been collected yet. Ready-plan-v9 is prepared to run after the current
executor releases the allocation, with six-minute bounds and no automatic resume.

Marker-probe packaging correction before GPU execution: v1's existing context
record filter also selected the new mutation record because both contain
`rounds`. v2 filters context records by the explicit `context` key. Synthetic
eight-rank qualification tests now accept the two distinct expected outcomes
(preserve versus deliberate reproduction of clobbering) and reject an incorrect
observed byte. v1 and ready-plan-v9 are retired without GPU runs; use v2 and
ready-plan-v10. The GPU probe and transport code are identical between these two
packaging versions. Existing delivery-batched and cached-credit failures may be
related to this hazard, but that connection remains a hypothesis pending tests.

After the failing process unwound, gate855's buffered logs finally flushed:
seven ranks had entered fresh-dispatch timed call79, while rank3 remained inside
call78. Rank3's exception was a CPU wait for receive counts, all zero at timeout;
the other ranks' GPU errors followed the protocol stall. This narrows the
observation to a one-call divergence, but does not yet identify the initiating
instruction or prove that the delivery marker caused it.

Prepared (not submitted) zero-marker full-qualification sequence1200–1208 and
ready-plan-v11. It depends on1102 passing, then requires public GIN, wrap/reuse,
concurrent producers, sustained32/257-token five-route matrices with three seeds,
FP8/BF16 EP checks at257/4096, sustained16K, and three ordinary4K/16K timing
repeats. This uses the same source-marker-probe-v2 GPU/runtime inputs. No candidate
performance is accepted before the correctness sequence completes.

Optimization order remains: resolve delivery semantics first; then rebase the
already compiled contiguous-row staging prototype onto the qualified transport;
then vary notification/chunk sizes with matched controls. The transport ladder's
row-versus-coalesced gap still supports aggregation as a performance hypothesis.
A correctness fix alone is not expected to remove the entire dispatch bandwidth
gap, and successful small probes alone cannot establish full-EP safety.

Gate857 reproduced the control failure and exited with FAIL;858 was not run.
The independent copier preserved live host markers through the stall (first
mixed case, fresh-dispatch warmup call7). Node0 again reported tag6 local-barrier
waits on three ranks; node1 reported missing remote forwarder finish signals.
The allocation remains held; no failed result was converted to PASS.

Marker-v1 GPU preflight completed at03:12:48. V2 changes only its host qualifier
and source-specific sequence; GPU/transport files are identical. Its redundant
runtime installation blocked in Lustre `cl_sync_io_wait` while hashing a copied
DOCA header. The unused installer was stopped, its incomplete runtime preserved,
and recovery verifies exact GPU-source/runtime hashes before aliasing the
immutable already compiled v1 runtime. This avoids changing GPU code or bypassing
compilation. V2's corrected qualifier has independent positive/negative tests.

The Lustre read stall also affected an unused copied unit-test file in the v2
source directory. Before any GPU execution, the stalled verifier was stopped and
the staged objects preserved. V2 was reconstructed from hard links to the verified
v1 source files, replacing only the new directory entries for the two changed
files and manifest with hash-checked v2 contents. Parent inodes were not modified;
the v2 source digest remains unchanged. Verification is repeated on this storage
recovery before launch.

Prepared zero-marker sequence-v2 / ready-plan-v12 with tighter execution bounds:
public GIN and producers480seconds, wrap420, tiny/stress600, full FP8/BF16 matrix
900, timing480. Previous full public-GIN gates400/404/408/500/504 took107–136seconds;
producer gates502/506 took39–107seconds. These bounds preserve substantial margin
plus the executor's three-minute allocation reserve. They change only scheduling,
not GPU/settings/qualification. Planv11 remains an unused earlier preparation.

Storage recovery verification completed successfully at approximately03:19 CET:
actual source hashes and all runtime hashes match the compiled v1 GPU inputs;
only v2's qualifier and sequence differ. V2 runtime is an immutable alias to the
verified v1 runtime; its incomplete unused installation is retained separately.
Ready-plan-v10 is now being launched for the three controlled mutation probes.

Ready-plan-v10 executor is **PID148579 onclariden-ln001** (plan SHA256
`d6ecf7957dec196f5fa94728aecf291a7701c17735968c1e8271872256c25b87`).
Gates1100/1101/1102 run sequentially and stop on an unexpected outcome. The plan
holds the allocation afterward. No claim of zero-marker GPU success is made yet.

### 03:21 CET — test-selection correction; actual wrap results retained

The v3 hardware-fence source sequence starts at401b, not400. Positional template
selection therefore picked raw queue-wrap tests for gates1100–1102 despite their
names. All three completed PASS as **raw wrap/source-reuse checks only**, including
the zero-byte marker. They did not run the receiver-mutation probe. Their original
specification/result records remain intact, with explicit interpretation notes;
no notification-preservation claim is derived from these passes.

Corrected generation now selects templates by exact names and asserts each
qualification/test-kind pair. New sequence-v3 / ready-plan-v13 uses gates1110–1112
for the actual GIN notification probe. It is running under **PID114690 on
clariden-ln003**. The earlier full-qualification plansv11/v12 also had shifted
selection and were retired before execution. Corrected ready-plan-v14 contains
exactly public GIN, raw wrap, producers, then six EP gates; its generator reproduces
the staged sequence and plan byte-for-byte. No GPU source/runtime change was needed.

The ordering distinction is important: CLIC's checked KI dispatch/combine code
flushes its count-header location, waits for completion, and only then publishes
an independent readiness signal (`dispatch_ki_common.cuh:360`,
`combine_common.cu:361`). DeepEP's notification counts themselves encode readiness;
`recv_and_reduce()` consumes and clears them without waiting for another signal.
Copying a byte later is therefore not a generally safe provider-level completion
mechanism, even if it works for a payload guarded by a separate readiness signal.

| Controlled probe order | Sender context0 | Receiver |
|---|---|---|
| 1 | PUT four-byte encoded value; retain source | Wait until the value arrives |
| 2 | Wait on separate handshake context1 | Clear destination; acknowledge clear |
| 3 | Flush context0, forcing pending delivery marker | Wait for flush-done handshake |
| 4 | Keep source unchanged until completion | Verify destination remains zero |

The replay variant deliberately expects its final byte to reappear as
`0xff000000`; this is a negative diagnostic. The nonbatched and zero-byte variants
must preserve zero. All handshakes are GPU GIN operations; the CPU only launches
and checks the completed kernel. This isolates notification-buffer mutation from
DeepEP's packing, NVLink forwarding and host output-size synchronization.

### Notification probe initialization corrected before transport conclusions

Gate1110 failed: six ranks stopped in initial readiness/data arrival (stages1/2),
while two ranks completed100 preservation checks. The probe initialized its
handshake target by reading a live signal. A faster peer could already increment
that signal, making the slower peer wait for an extra increment that would never
arrive. This is an initialization race in the new test;1110 does not establish a
transport failure. Gates1111/1112 were not run.

`source-marker-probe-v3` resets signals under two host collective barriers before
launch, then uses fixed zero-based targets in the GPU kernel. The transfer,
clear/acknowledge, flush and verification operations are otherwise unchanged.
Only `gin_smoke.cu` and the source-specific sequence differ fromv2; all transport,
DeepEP archives and runtime definitions remain byte-identical. The corrected
probe compiled for all three variants. Existing native control builds are reused
only because their complete DeepEP/runtime inputs are identical; the changed
standalone GIN kernel is compiled anew. No failed GPU qualification is reused.

Current allocation: ready-plan-v17, **PID180280 onclariden-ln003**, attempts only
corrected control1120, with a180-second bound and the existing three-minute job
reserve. Its native control build is already complete, avoiding rebuild time.
Failure or insufficient allocation time is retained as such; it is not a pass.

Pending allocation3810110 now has a planned startup hold. Its older seven-gate
replay-marker sequence remains intact but will not automatically execute.
`ready-plan-followup-v2.json` instead prepares:
1. Fresh-node nonbatched native-fence public GIN, wrap, producer and EP correctness.
2. Corrected control/replay/zero notification probes1120–1122 on that node pair.
3. Full zero-marker qualification1200–1208, including sustained small-token and
   FP8/BF16 checks,16K stress and three ordinary timing repeats.
All dependencies are local to that allocation. The updated plan still needs to
be launched after Slurm actually allocates the nodes and its controller reports
the planned hold; no pending-job execution is claimed.

### 03:30 CET — corrected control passed; clean allocation handoff

Gate1120 passed all100 receiver-clear/flush iterations on each of eight ranks:
800 verified checks, all observed values zero, no errors. Normal public-GIN
payload checks and teardown also passed. The local `marker-analysis.json` records
the result. This validates the corrected probe's nonbatched control; replay-byte
corruption and zero-byte preservation remain untested by this corrected probe.

With every GPU step drained and ready-plan-v17 COMPLETE_HELD, the controller was
asked to exit cleanly because no further declared test fit the remaining bounded
window. Slurm records job3809401 **COMPLETED, exit0:0, elapsed03:55:30**. This means
the allocation ended cleanly, not that the optimization campaign is complete.
Failed and deferred experimental gates remain preserved.

Job3810110 became eligible and is pending (latest reason `QOSGrpNodeLimit`, after
an earlier Priority observation). Its planned startup hold and updated
ready-plan-followup-v2 are staged. The 24-hour campaign remains active. No partition
or QOS limit was bypassed, and no unrelated job was altered.

### 03:35 CET — continuation allocation running on a fresh node pair

Job3810110 is RUNNING on **nid006898,nid007571**. The planned startup hold worked:
none of the superseded initial replay-marker requests ran. Launched
ready-plan-followup-v2 under **PID172226 onclariden-ln003**, plan SHA256
`8804c6c6514210994f69402eb34ee004185ce469f5a2e7790708c3f558be62d1`.
The first active gate is `newnode-00-fence-dc-gin`. Subsequent baseline checks,
corrected probes1120–1122 and candidate qualification1200–1208 remain explicitly
gated and stop on failure. The existing read-only monitor PID570847 continues
collecting this allocation. The 24-hour goal remains active.

### 03:40 CET — zero-marker dispatch aggregation prepared, GPU gates not launched

Prepared immutable `source-zero-packed-v1` from `source-marker-probe-v3`.
The CXI device, host and ABI files are byte-identical to the marker parent;
`marker-zero` retains native fencing, batch limit8 and zero-byte delivery markers.
An archive audit confirms that the only modified existing ordinary DeepEP file
is `hybrid_dispatch.cuh`, plus the new channel-capacity helper. Combine is unchanged.

The experiment packs each channel's remote rows contiguously and submits their
pending range immediately before the existing progress notification. Notification
interval3,64SM,129contexts and payload/routing semantics remain unchanged. This
isolates fewer PUT requests from less frequent notification. It is EP8-only;
relocated-PUT tracing is deliberately rejected until its instrumentation is adapted.

Local Python/shell syntax and source-delta checks passed. Remote CPU/host/GPU
compilation preflight is running under PID256226 onclariden-ln001, with log
`zero-packed-preflight-v1.log`. The preflight requires transport/runtime identity,
CPU capacity tests, and32 actual FP8/BF16 fresh/cached templates across32,257,4096
and16384tokens. No compilation or GPU qualification success is assumed yet.

Staged `ready-plan-zero-packed-v1.json` with gates1300–1311, but did not launch
another executor. It requires1203–1208 to pass first. Both original-row and packed
variants must pass irregular routing stress,4K FP8/BF16 correctness and dropped-token
checks before either contributes performance results. Then three interleaved ordinary
4K/16K repeats compare latency and separate600-call NIC-counter windows.

Job3810110 remains RUNNING; newnode-00 is still building/testing the fresh-node
baseline. Node1 has reached the GIN smoke test, while node0 is finishing its native
build. No new performance conclusion or causal claim about the earlier EP stalls
is justified yet. The24-hour campaign remains active.

### 03:44 CET — fresh-node baseline transport gates passed

Job3810110 has passed all three initial transport gates onnid006898,nid007571:

- `newnode-00-fence-dc-gin`: eight ranks, three context configurations per rank
  (1,4,129),28rounds, including reset/self/negative checks; exit0.
- `newnode-01-fence-dc-wrap`: eight ranks,16,384payload commands/rank, queue-wrap
  and source-reuse checks; exit0.
- `newnode-02-fence-dc-producers`: eight ranks,1/2/8producer-block configurations,
  256rounds; exit0.

Slurm step3810110.3 is now running `newnode-03-fence-dc-ep-correctness`.
The corrected marker probes and zero-marker EP qualification have not run yet.

The zero-packed preflight process256226 and its template compiler child282662
were verified live onclariden-ln001. CPU queue/descriptor/layout checks passed;
all16 original-row FP8/BF16 templates compiled. Packed-row compilation remains
in progress. Do not treat a live process or partial compilation as full PASS.
The read-only collector570847 is also live and collecting gate evidence locally.

### 03:47 CET — same-node comparison added; request budget audited

Staged `ready-plan-marker-matched-v1.json` / `marker-matched-v1-sequence.json`
(gates1400–1407), without launching another executor. After zero-marker
qualification passes, this adds nonbatched-control tiny/sustained stress and
three interleaved control-versus-zero ordinary4K/16K repeats on the current node
pair. Historical native-fence timings came from a different pair and cannot by
themselves establish the new marker's performance effect. This comparison should
precede the prepared zero-packed plan. Runtime/source bytes are unchanged.

`dispatch-request-budget-v1.json` records source-derived token-path request counts
for the all-remote-token fixture (one deduplicated remote row/token,256channels).
At4096tokens and interval3, packing changes4096PUTs to1536PUTs, while1536remote
progress notifications remain. Each notification still issues a fence, CSTATE
and atomic command. Context sharing can merge delivery epochs, so the budget
labels delivery-marker/total-command counts as upper bounds. It excludes metadata,
explicit completion commands, local NVLink work and barriers; it is neither a
NIC measurement nor a latency prediction. A partial batching gain would justify
separately testing notification intervals after correctness, rather than assuming
PUT aggregation removes all request overhead.

The packed4K FP8 templates compile with146registers fresh /128cached and zero
spill stores/loads (original-row fresh124registers). Full32-template compilation
is still pending. The active EP baseline gate is progressing through routing
cases; no marker candidate GPU result is available yet.

Reconciled `campaign.json` with the live allocation/executor and archived its
previous contents under `campaign-history/`. Retired executor fields and broad
batched-transport qualification flags were stale; historical PASS records remain
intact, while general batched qualification stays reopened. No executable plan,
source snapshot, or running job was modified by this metadata correction.

### 03:50 CET — packed compilation complete; executor advanced to marker probes

The zero-packed preflight finished. Collected and checked all32 compilation
records against the exact checker SHA256: both layouts, FP8/BF16, fresh/cached,
32/257/4096/16384tokens. All32 report zero spill stores and loads. Evidence is in
`preflight-source-zero-packed-v1/`, including the raw logs and
`compiler-summary.json`. This is compile qualification, not GPU correctness.

Slurm still reports3810110 RUNNING. Verified live ready-plan PID172226 and its
new child224635 executing `newnode-marker-v3-probes-sequence.json` onln003; the
executor has advanced past the fresh-node baseline. Some shared-filesystem reads
and local collection are delayed, so the final baseline gate record still needs
to be collected directly. An observation delay did not trigger any restart,
resubmission, source mutation, or competing GPU step. The original allocation
and stop-on-failure executor remain authoritative.

### 03:51 CET — final baseline ledger verified

Retrieved `newnode-03-fence-dc-ep-correctness/FINISHED.json` directly: exit0,
qualificationPASS,8ranks ×10cases, custom direct GIN type6, ending02:48:25UTC.
Coverage is V4Flash FP8 dispatch/BF16 combine at257and4096tokens across mixed,
uniform,hot-rank,local and remote routing; this baseline gate is not a BF16
**dispatch** qualification. All four fresh-node baseline gates are now verified.
Corrected nonbatched marker control1120 is running. Candidate marker preservation,
full candidate stress/performance and SGLang release checks remain pending.

### 03:56 CET — control preservation confirmed; isolated CSTATE publication patch

Fresh-node corrected control1120 passed:100notification-clear/flush checks per
rank,800total, observed0 on all eight ranks, errors0. `marker-analysis.json`
contains the per-rank records. Independently verified all80baseline EP correctness
rows from the local collection. Replay diagnostic1121 is now executing on GPUs;
its expected corruption is a negative diagnostic, not a transport qualification.

Prepared `source-cstate-defer-v1`, a separate, smaller transport experiment based
on the zero-marker parent. `state_locked()` currently publishes CSTATE, then
`add_locked()`/`value_locked()` immediately publish the following atomic/IDC PUT.
The candidate passes the existing aggregation flag for CSTATE so its following
nonaggregated operation can publish both. Both known callers keep the same context
lock throughout. Existing capacity-wait publication and batch-limit publication
remain intact; command order, native CQ fences, DC markers, completion accounting,
credits, ABI, host code and DeepEP archives are unchanged. This targets redundant
doorbells, without attempting IDC state caching or changing notification cadence.

The exact source delta is limited to the primitive header, variant definitions,
preflight script and gate sequence. Control has`CXI_DEFER_CSTATE=0`; candidate=1.
Private runtime installation uses verified parent files and atomic replacement
of changed headers/manifests, then rechecks the parent's hashes. No running source
or runtime is modified. Compile preflight PID271106 is running onclariden-ln003,
log`cstate-defer-preflight-v1.log`; GPU qualification is not asserted.

Staged but did not launch `ready-plan-cstate-defer-v1.json` (1500–1517). Each arm
requires notification preservation, wrap/source-reuse, concurrent producers,
tiny-token stress, FP8/BF16 correctness,16K sustained operation, then three
interleaved ordinary repeats. Zero-marker1203–1208 must pass first. This experiment
uses ordinary row staging and stays separate from the zero-packed patch, so its
performance effect can be measured independently. Actual execution order will
follow the marker/packed results and allocation time remaining.

### 03:57 CET — repeated-byte corruption reproduced on every rank

Gate1121 completed its expected-negative diagnostic:100iterations on each of8ranks,
800total, each reporting the final value`0xff000000` after the receiver had cleared
its notification to0. Gate1120's matched nonbatched control preserved0 in all800.
The analyzer records the distinction explicitly:1121's PASS means the corruption
reproduction behaved as expected, **not** that this transport is correct.

This proves the existing repeated-byte delivery marker can overwrite consumed
notification storage. It does not yet prove that all previously observed full-EP
stalls share this cause. Those failures and historical timing data remain preserved.
Job3810110 is now running1122, the zero-byte-marker preservation test; only after
it passes can full zero-marker correctness/stress and performance checks proceed.

### 04:00 CET — zero-byte marker preservation passed; full qualification running

The corrected three-arm probe is complete on job3810110:

| Arm | Checks | Observed value after receiver clear and sender flush | Interpretation |
| --- | ---: | --- | --- |
|1120nonbatched control|800across8ranks|0|Preserved|
|1121repeated-byte marker|800across8ranks|0xff000000|Corruption reproduced; expected-negative diagnostic|
|1122zero-byte marker|800across8ranks|0|Preserved|

Normal public-GIN payload checks and teardown also passed in each gate. The
per-rank evidence and `marker-analysis.json` files are collected locally. This
validates the zero-marker fix for the notification-clear probe, not general EP
qualification. The existing executor has advanced to1200public-GIN checks, then
wrap/producers and1203–1208 EP stress/correctness/ordinary repeats.

CSTATE deferral preflight also completed: host checks and actual SM90 smoke,
bounds, producer, device and raw-wrap probe compilation passed for both variants.
Collected evidence is in `preflight-source-cstate-defer-v1/`; the installer verified
that parent runtime hashes remained unchanged. No CSTATE candidate GPU test ran.

Added `vendor-command-sequencing-evidence.json` with local primary-source hashes:
`cxip_cmdq.c` queues CSTATE and its following IDC operation without an intervening
successful-path ring; queue-full/error paths ring to prevent deferred-publication
deadlock. Its fetching-AMO delivery-flush path constructs a zero-initialized PUT
with flush enabled, leaving request length0. The provider manual describes FI_MORE
batch publication and target PCIe flushing reads for delivery completion. These
support the design rationale but do not substitute for qualification of our
restricted GPU-initiated marker, which is a distinct path.

### 04:02 CET — broader zero-marker transport checks and combine scope

Collected and verified1200public-GIN PASS (eight ranks,1/4/129contexts,28rounds,
reset/self/negative checks) and1201queue-wrap/source-reuse PASS (16,384payload
commands/rank). Producer stress1202 remains active at the latest observation;
full EP stress and timing gates have not passed yet.

Audited the pinned archive's `hybrid_combine.cuh` while these gates run.
`flush_last_tma_and_issue_rdma()` submits one reduced token row at a time; its
remote destination uses the original source-token position. These destinations
are strided within a channel, so dispatch's contiguous-row packing patch cannot
simply be applied unchanged to combine. The completion block explicitly flushes
before publishing final remote tails and waiting for incoming tails. Removing
that wait requires a separate source-buffer-lifetime/ordering argument and tests;
no such removal was made. Both dispatch and combine remain required release
metrics. The staged CSTATE-publication experiment changes only publication of
adjacent commands and preserves these completion semantics.

### 04:03 CET — zero-marker producer stress passed; sustained EP started

Gate1202 passed all8ranks for1/2/8producer-block configurations,256rounds each,
with clean context teardown. Job3810110 is now executing1203:32and257tokens,
five routing patterns, three seeds,20warmup/100timed iterations. This ordinary
untraced gate targets the small-token sustained workload where earlier controls
stalled. The zero-marker public-GIN/wrap/producer prerequisites are complete;
full EP correctness, larger-message stress and three timing repeats remain open.

### 04:06 CET — sustained gate stopped at CT-ID exhaustion, not payload failure

Gate1203 failed during creation of its16thcase,257tokens/mixed/seed2, after all
8ranks had completed15correctness cases and60operation timing records each.
The harness loops seed first, so these include both32and257tokens. All8ranks
report `created=2047`, `ct_in_use=2047`, then `cxil_alloc_ct ... rc=-28` (ENOSPC).
The failed gate remains FAIL; its partial results are not promoted as a complete
stress qualification. The allocation is held, with no subsequent gates launched.

Source diagnosis: `cxi_channel_recycle()` requires the GPU-cached completed count
to equal posted. A final signal can have acknowledged in hardware without another
GPU flush updating that cached field. Such a healthy queue is closed instead of
pooled. The driver defers CT-ID reclamation until LNI cleanup, but the long-lived
NCCL bootstrap retains contexts, so repeated buffer construction reaches the limit.

Preparing a lifecycle-only fix: after the existing GPU synchronization and state
capture, query local NIC completion counters for otherwise healthy, published,
unlocked channels, verify queue drain/counts, and preserve the refreshed CT cursor
when pooling. No TX payload/signal commands or steady-state CPU progress are added.
Errors, pending software publication and invalid contexts still fail closed. Full
matrix and resource-plateau validation are required before promotion.

### 04:13 CET — lifecycle-only patch resumed in the held allocation

`source-retire-refresh-v1` changes only `backend/host/cxi_resources.cc`, the gate
qualifier and sequence. It refreshes stale completion accounting for otherwise
healthy retired contexts using local CT_GET commands after the existing
cudaDeviceSynchronize/state-copy boundary. It waits for queue consumption,
rejects counter failures/regression/overshoot, preserves updated CT queue cursors,
and pools only a fully completed state. No TX payload, remote signal, delivery
marker or steady-state CPU progress operation is added. Pending publication,
locked/errored contexts and unsuccessful teardown remain rejected.

Host compilation passed with warnings treated as errors. Manifest audits show
GPU headers, ABI, DeepEP archives and runtime libraries are unchanged. The native
DeepEP extension was reused only after input/runtime/binary SHA verification;
`direct_node.sh` freshly compiles the changed host GIN plugin for every gate.
Evidence is in `preflight-source-retire-refresh-v1/` and the job's
`builds/source-retire-refresh-v1/marker-zero/NATIVE_BUILD_REUSE.json`.

Launched `ready-plan-retire-refresh-v1.json` under PID91326 onclariden-ln001,
SHA256`f1fd0e0f798ed590e554a402de58c1d1e83bd2c4576a3b514dc8295266ab7cce`.
Verified Slurm step3810110.11 and the executor live. Gate1600public-GIN is running;
1601–1608 cover wrap, producers, the full30-case tiny matrix,40-case FP8/BF16
correctness,16K stress and three ordinary repeats. The large matrices additionally
require observed queue reuse and CT resource usage bounded well below the service
limit. Failed1203 is retained unchanged; it is not silently relabeled or resumed.

Prepared marker comparisons, packed-row and CSTATE-publication experiments must
be rebased onto the lifecycle fix after qualification. Their original dependencies
include failed1203 and deliberately cannot pass. The active24-hour objective and
allocation remain intact; no extra Slurm allocation was requested for this repair.

### 04:20 CET — retirement check corrected before another GPU attempt

1600–1602 passed all public-GIN/wrap/concurrent-producer checks. Gate1603
completed its first correctness case and four timing records on each rank, then
failed closed at teardown. The new queue-status check incorrectly treated any
nonzero return code as an error. The installed `cassini_user_defs.h` defines
`C_RC_OK=1`; the captured status281474976710916 is a successful queue status,
not a NIC error. Failed1603 is retained, and no later gates from that plan ran.

`source-retire-refresh-v2` uses the installed `c_cq_status` named fields and
`C_RC_OK`, with an ABI size assertion. Preflight now checks the actual captured
status and rejection/error cases. GPU/device/runtime bytes remain unchanged.
A login-node /tmp-full condition was handled using a campaign-owned TMPDIR;
the new standalone header check also needed cstring before the HPE header.
These are preflight failures, not GPU results. New1800–1808 gates will rerun
transport checks, the complete matrices, resource plateau and ordinary repeats.
The allocation remains held. Packed-v2 is compile-only and depends on failed
1603, so it will be rebased again before any execution. Same-node marker
comparison1900–1907 has been prepared with dependencies on1803–1808.

Corrected preflight passed, including the captured CQ status and negative status
cases. Launched `ready-plan-retire-refresh-v2.json` PID83175 onclariden-ln001,
SHA256`7d28c115bee918d99427953cdf4c8964f1634c4f93fc903dcdc906519964542a`.
Verified1800 public-GIN running in3810110. The changed host plugin is freshly
compiled for every gate; only the hash-identical native DeepEP extension is reused.

### 04:25 CET — corrected retirement refresh is exercised successfully

1800/1801/1802 passed public-GIN,16,384-command queue wrap and concurrent producer
checks across8ranks. In1803, all8ranks have completed the first5EP cases. Logs now
show actual teardown-only CT refreshes completing in one query, followed by pool
reuse: created/CT-in-use stay133 while reused reaches645. The earlier run instead
allocated new channels for every case. This is evidence that the repair is being
exercised; the full30-case stress and larger matrices must still finish.

An overlapping read-only Slurm inspection showed ranks waiting on Lustre/JIT
compilation, with compilers active; it did not run GPU kernels or change the
benchmark. It finished cleanly. Slow observation/startup was not treated as a
transport failure. Login compilation also encountered Lustre waits and was left
running without duplication.

`source-zero-packed-v3` has passed exact32-template GPU-source/cubin/runtime
comparison with the already compiled packing candidate and uses corrected host
lifecycle code. No packed GPU execution yet. `ready-plan-marker-then-packed-v1`
contains same-node marker comparisons followed by separately gated packing
checks, depending on1803–1808. `source-cstate-defer-v2` is independently compiling
against the corrected lifecycle parent; it remains a separate future experiment.

### 04:26 CET — full tiny-token regression passed

1803 completed30correctness cases and all associated timings on each of8ranks,
including the case16 boundary where1203 exhausted2047counter IDs. The lifecycle
qualifier passed: created/CT-in-use remained133, with3741queue reuses per rank.
Retirement completion queries ran only after GPU synchronization at teardown;
there is no CPU NIC-progress loop in timed dispatch/combine. This resolves the
observed CT exhaustion for this matrix. The40-case FP8/BF16 gate1804 is running;
16K stress and3ordinary timing repeats remain before optimization comparisons.

### 04:31 CET — larger matrix exposed a distinct first-call timeout

1804 failed during cached dispatch in its first257-token FP8/mixed/seed1 case,
before any context teardown or complete correctness record. Node1 ranks5–7
reported the cached-dispatch NVLink entry barrier with signal3/target4/counter5;
other ranks reported forwarding waits for remote arrivals. Rank4's missing local
barrier participation is a useful lead, not a proven transport root cause.
Cached cubins on both nodes were written around04:27:58; timeout was04:28:59.
Lustre/JIT stalls were independently observed, but these times alone do not prove
that storage caused this failure. The passed30-case1803 is retained with its
scope;1804 remainsFAIL and all downstream performance plans remain blocked.

Prepared `source-first-call-debug-v1`: unchanged GPU/transport/native code plus
host entry/return markers for initial fresh dispatch, both combine calls, cached
dispatch, validation and destruction. Records go first to /dev/shm and a separate
read-only copier persists them; this adds no CUDA synchronization or NIC progress.
Separate2200zero-marker and2201nonbatched-control replays use257tokens,FP8,mixed,
seed1. Diagnostic timing will not be promoted to ordinary performance evidence.

2200zero-marker replay launched under PID100492 onclariden-ln001,
planSHA256`02f6d252e5833ddd354d392a7d145c6b0b217ef68500d04a19eb5327b69ee008`.
Compilation-equivalence preflight passed for every GPU/runtime/native input.
A nonbatched control replay2201 is prepared separately, so a failed zero replay
will not silently skip the control or be overwritten. Both use the same observer.

### 04:34 CET — isolated zero-marker replay passed; control running

2200 passed on8ranks with1001host-journal records each, one complete payload/
combine/cached correctness case, four operation timing sets and clean teardown.
No GPU diagnostic code was reported. It does not reproduce1804, so the failure
remains unresolved; diagnostic timings are excluded from performance promotion.

Cold host entry/return durations (including JIT and API work) were roughly9.1s
for first fresh dispatch,12.0s for first combine,0.00017s for the second combine,
and8.2–9.47s for first cached dispatch. These are **not** GPU/network latencies.
Cached host entry spread within each node was under0.13ms. Evidence:
`job-3810110/results/results/2200-marker-zero-first257-diagnostic/first-call-analysis.json`.
We have no corresponding host journal for failed1804, so this cannot attribute
that failure to JIT skew or any specific transport operation.

2201nonbatched-control replay runs under PID226006 onclariden-ln003,
planSHA256`fdecac4e9afa4d061b486faf30f0964d104e0e9fdec8ba291ceae4819f379f05`.
Prepared2210/2211 repeat the full40-case matrix without the observer or source
changes, in independent processes/JIT caches. Only if both pass will2212–2215
continue16Kstress and three ordinary timing repeats. No failed gate is overwritten.

### 04:38 CET — both diagnostic arms passed; ordinary cold matrices resumed

2201 nonbatched control passed the same257-token case on all8ranks with complete
journals and clean teardown. Cold host fresh-call duration ranged30.22–51.16s;
first combine ranged0.017–20.94s, and cached dispatch took about21.15s. Host
entry/return includes JIT/load and synchronization, so this is startup skew, not
network-transfer latency. One live process was observed in Lustre osc_extent_wait;
shared journals lagged and later caught up. This is evidence to investigate
storage-related launch skew, **not proof** that it caused1804.

Launched `ready-plan-retire-refresh-cold-v1.json` PID205250 onclariden-ln002,
SHA256`ddf8bea482bbd87d5a67b37b727802489a2a6a4212cfdffa956b6a79f5663a99`.
2210/2211 independently repeat the original40-case matrix without observers,
followed only on success by2212 stress and2213–2215 ordinary repeats. Source,
runtime and transport are unchanged from failed1804. The failure remains recorded.

New externally hashed scheduling sequences (sources unchanged)2400–2407 marker
comparison,2300–2311 packing and2500–2517 CSTATE depend on these cold requalification
gates. The previous sequences still depend on failed1804 and were not modified.
No pending performance experiment has been launched or promoted.

### 04:45 CET — ordinary matrix failed at a different entry barrier

2210 passed five257-token FP8 routing cases, then passed BF16/mixed correctness
and fresh/cached dispatch timing. All ranks produced6correctness records. Rank2 produced21timing records; the
other7ranks produced22. The first subsequent combine warmup stopped at entry: node0
local ranks0/1/3 reported NVLink barrier tag8,signal3/target4,counter30; localrank2
was the missing participant. Remote ranks waited for scale-up data. No teardown
had started for this case.2211–2215 were not run. This is another synchronization
failure, not evidence of bandwidth loss, and no performance candidate can advance.

Prepared2260 to repeat the entire40-case sequence with the existing tmpfs host
journal, including every correctness/warmup/timed entry and return. Transport,
GPU source and API ordering remain unchanged. This is needed to distinguish
host-side progress stalls from a launched GPU collective wait. The output writer
currently appends directly to Lustre between operation groups; that is a concrete
hypothesis to examine, not an established cause or a reason to hide the failure.

Source-only audit `cstate-pairing-source-audit.json` records a possible later
optimization: the vendor supports32-byte CSTATE/small-atomic commands while our
emitter reserves64bytes for each. Pairing them is not implemented or benchmarked;
correctness and the already prepared row-packing tests retain priority.

A subsequent complete remote inventory sharpened the lead: rank2 has21timing
records, missing the BF16 cached-dispatch timing record that the other7ranks
wrote. It is also the missing participant at the next combine barrier. Thus the
journal should distinguish cached completion/measurement return from a blocked
result append before combine. Partial local collections must not be mistaken for
complete per-rank evidence; all counts above were rechecked remotely.

2260 full-matrix diagnostic launched under PID47676 onclariden-ln001,
planSHA256`b59164309aa2b33b83a95fcb4dc269c6f56faf3b0570dfb54b161d1e2c0c7993`.
The same allocation remains held and the observer never submits NIC operations.

### 04:52 CET — direct process observation; host-I/O isolation prepared

2260 is still running and has progressed beyond257-token cases into4096 FP8/BF16.
Read-only CPU steps inspect each benchmark process's own tmpfs phase journal via
`/proc/PID/root/dev/shm`, avoiding the shared copier's delay. The samples show
`osc_extent_wait`/`osc_io_fsync_end` while ranks hold JIT `kernel.cu`/`kernel.cubin`
files open. Other ranks wait in `pipe_read` during the same first-call phase.
This confirms storage stalls during JIT; it does not yet establish the cause of
1804/2210's missing collective participants. The raw samples are
`job-3810110/2260-process-observation{,-2,-3}.jsonl`.

Prepared `source-local-io-v1`, with unchanged GPU/transport/native/runtime input
bytes. Independent switches put JIT in an attempt-private tmpfs directory and
append JSON result records to a bounded tmpfs journal. A separate stdlib process
copies records to Lustre; it never calls CUDA/NCCL/CXI or advances network work.
Final persistence is checked before the final result barrier; failed copies fail
qualification, and partial journals are retained on failure. Eight local test
producers persisted9600 records in exact order. GPU validation is still pending.
Gates2600/2601 isolate JIT-only versus JIT+result-spooling with phase observation;
2602/2603 are ordinary repeats with the observer disabled. These are diagnostic
harness experiments, not evidence of a transport optimization or release readiness.

### 04:54 CET —2260 reproduced entry timeout; failed step stopped

At04:52:05,2260 reported tag6 hybrid-dispatch entry-barrier timeout with signal3
of4 on node0, during4096 BF16/mixed cached correctness. Rank3 was sampled in
Lustre waits with the same JIT kernel.cu open across53.298s (discrete samples,
not a continuous off-CPU measurement). Rank0 was subsequently also sampled with
a JIT file open, so phase-level evidence alone cannot identify each outstanding
kernel. The entry barrier is upstream DeepEP's local-rank signal counter;
this is not yet proof of a CXI completion defect. Full raw evidence is retained.
Stopped only failed step3810110.26 after torchrun had begun aborting; allocation
3810110 remains held. Local-JIT isolation2600 is next, with exact native/GPU input
identity checked before execution. No failed result is promoted or overwritten.

### 04:55 CET — blocked kernel identity recovered

The retained compiler report for rank3's sampled temporary path identifies
`hybrid_dispatch_impl<false,true,...8192,...4096...>`: the main BF16 cached
hybrid-dispatch kernel. PTXAS itself reports545.088ms compilation, while our
filesystem-wait samples span53.298s. Rank0's later open file identifies
`dispatch_copy_epilogue_impl<false,true,...8192,...4096...>`, which is compiled
after launching the main dispatch. Together with the tag6 entry timeout, this is
strong evidence of host-side JIT/storage launch skew in2260. It is not a measured
53s NIC delay, and it does not explain ordinary warmed-up3ms dispatch performance.
Evidence: `2260-rank3-blocked-compile.txt` and `2260-host-io-evidence.json`.

### 04:57 CET — local-JIT diagnostic2600 launched

The ln003 preflight process blocked reading a453557-byte shared header. The same
file read and hashed correctly onln001; terminated the stalled audit before any
runtime/build aliases existed, then completed the full identity audit onln001.
`local-io-preflight-v1-ln001.log` isPASS. Gate2600 now runs the original40-case
matrix with local JIT and shared result appends; host phase observer remainson.
GPU/transport/native/runtime inputs are unchanged. ExecutorPID104007 onln001,
planSHA256`df1e580f3a67d148ed51f195473da5a84eb969e49016c665dbf9ce8945367fa2`.
The allocation remains3810110; no concurrent GPU test was started.

Follow-up job3811125 submitted with afterany:3810110: two GH200 nodes, four hours, held startup, no overlapping allocations. Read-only monitor PID645186.

### 05:00 CET —2600 stopped during startup; common-file staging repaired

2600 never completed startup on both nodes. A read-only process inspection found
node0 verifierPID223311 in`cl_sync_io_wait`, reading the new snapshot copy of
`backend/include/cassini_user_defs.h`. The file hashes correctly onln001 but its
new inode also stalled the ln003 audit. Stopped only step3810110.32; this is a
startup/storage failure, not a failed EP payload check or bandwidth result.

Prepared`source-local-io-v2` with the exact same code asv1. Byte-identical parent
files are hardlinked into a new immutable snapshot; changed harness files are
written to new inodes and atomically replaced, never written through parent
links. Both parent and candidate hashes are verified. New2610–2613 gate names
retain separate evidence. This avoids redundant cold copies of unchanged headers;
GPU/transport code and the proposed local-JIT intervention remain unchanged.

### 05:03 CET —2610 running; subsequent experiments explicitly gated

2610 started underPID84382 onln001, planSHA256
`13a344e20b75f580006314b60a0cf95c3445288276e1635c035a71f34ed68233`.
Both nodes passed the105-source-file/77-runtime-file audits and entered EP
correctness. Initial FP8 routes progressed into257BF16. The common-file inode
reuse avoided the observed startup header stall; full EP correctness remainspending.

Prepared2620 sustained16K and2621–2623 ordinary repeats, requiring both2612/2613
ordinary full matrices. Prepared2630–2637 matched marker controls and2700–2711
row-packing, requiring the complete new qualification chain. Source-zero-packed-v4
passed the exact GPU/archive/runtime equivalence audit and reuses97 immutable
common input files. These candidate jobs have not run. Local result-copy traffic,
if enabled, is host result persistence and not NIC progress; NIC counter windows
remain labeled inclusive of control/background traffic, independently of CUDA
event timing. The original failed attempts and their gates remain preserved.

### 05:07 CET — first complete40-case local-JIT matrix PASS

2610 formallyPASS at05:06:24 CET:8ranks ×40cases;160 timing records/rank;
all3162-record host journals end cleanly; no GPU diagnostic codes. CT usage and
created queues plateau at133/rank, with5031 queue reuses. This qualifies the tested
matrix and repairs the earlier CT-resource-exhaustion scope; broader release,
ordinary-repeat and SGLang qualification are still pending.

For the previously failing4096BF16/mixed case, cached host-call durations are
7.608–8.093s with local JIT; the shared-JIT failure had no cached return and rank3
was sampled in filesystem waits across53.298s. These cold host values include
compilation and launch; they are not network or steady-state dispatch latency.
`matrix-host-analysis.json` pairs1600 mandatory host calls without gaps.

2611 (local JIT plus local result spool, observer enabled) launched underPID97164
onln001, planSHA256
`158a77cda58a10b0518da1a4785790f9baf79747d09cad66c93d194193e2a0ee`.
It will be followed by2612/2613 ordinary matrices before2620–2623 stress/timing.
No claim of improved steady-state throughput follows from this harness fix.

### 05:18 CET — post-run copy delay isolated; prepared sequence continues automatically

2611 has complete40-case GPU data on all8ranks, clean plugin destruction and
1600paired mandatory host calls. Its overall gate is stillRUNNING because both
node wrappers are copying the JIT artifacts. Live samples show`cp -a` repeatedly
in`osc_io_setattr_end`; later samples show different files, so copying is slow,
not evidence of an active GPU or a fixed stuck filename.

Prepared`source-local-io-v3` and`source-zero-packed-v5`, each differing from its
parent only in the post-GPU copy command and scheduling metadata. The copy uses
`cp -r --no-preserve=all`: file/symlink contents remain intact while ownership,
timestamps and other archive metadata are not reproduced. A local content test
and exact source/runtime/native equivalence auditsPASS. Artifact mtimes now
represent collection, not compilation; journal timestamps remain authoritative.

`ready-plan-local-io-through-packing-v2.json` is prepared, not yet launched. It
explicitly requires2610/2611PASS and chains2612/2613 ordinary matrices,2620–2623
stress/timing,2630–2637 matched markers, then2800–2811 packing. Any failure stops
later steps and leaves the allocation held for diagnosis. All GPU inputs are
unchanged by the copy repair; the packing candidate remainsGPU-unqualified.

### 05:20 CET —2611 PASS; ordinary-to-packing executor launched

2611 formallyPASS at05:19:52CET. All8ranks completed40cases with160timing records
perrank, complete1600-call host pairing and no GPU diagnostic errors. Cold4096BF16
cached host-call durations are7.854–8.225s (JIT/API, not network). Slow post-run
metadata-preserving copies accounted for the late overall completion.

Launched `ready-plan-local-io-through-packing-v2.json` underPID213633 onln001,
planSHA256`6c96e7f21a965d0a2bcdb13f6a6a69e5ec7f5c35a18c77567dc16b2fc6ad75dc`.
It starts2612/2613 observer-disabled matrices withsource-local-io-v3, then
2620–2623 qualification/timing and2630–2637 matched controls. Only on success does
it run2800–2811 withsource-zero-packed-v5. All phases have immutable sequence
hashes; failures or insufficient allocation time stop advancement. The main
controller remains intentionally held. Follow-up3811125 staysdependent, with
read-only monitor645186; current collector570847 remainsactive.

### 05:28 CET —2612 host logging stall; local-runtime-log repair prepared

2612 did not finish qualification. Its current processes all had local result
journals through4096FP8/mixed/seed1 cycle (sequence55), while shared copies lagged.
Read-only `/proc` evidence identified all four node1 ranks in AArch64 syscall64
(`write`), fd2, targeting the shared `direct/node1/smoke.log`: one was in
`ldlm_completion_ast`, three in`__fdget_pos`. Node0 processes were running.
This directly identifies host logging/storage blockage; it does not measure
steady-state NIC throughput or prove a GPU transport failure. Stopped only
step3810110.40; the step drained and the plan stopped, preserving the allocation.
No later2613/262x/263x/280x gates launched.

The v2 process sampler could select an old same-rank journal left by a failed
attempt. Its2612 phase fields are invalid and must not be used. v4 now requires
a journal to be open by the exact current PID and also reads that process's local
result spool. The wchan/PID/fd evidence is independent of the stale phase fields.
Evidence: `2612-process-observation-v4.jsonl`, `2612-syscall-observation.jsonl`,
`2612-step-stop.json`. Earlier diagnostic analyses use their gate-specific
collected journals, not this live watch0 phase attribution.

Prepared`source-local-logs-v1` and`source-zero-packed-v6`: runtime stdout/stderr
are directed to node-local tmpfs, copied after torchrun exits, and removed only
after successful persistence. Return codes remain unchanged; no PASS marker on
failure. Host tests verified both output streams, success and failure, persistence
and cleanup. GPU/transport/runtime/native source bytes are unchanged relative to
their respective parents. Local result/JIT handling remains enabled.

New immutable plan`ready-plan-local-logs-through-packing-v1.json`, SHA256
`a876a301bfd50f2e442abadf2a01504d20cd1f0bf3cab93f5794b293fd80e1cc`,
is prepared, not yet running. It starts2912/2913 ordinary full matrices, then
2920–2923 stress/timing,2930–2937 matched markers,3000–3011 packing. Preflight
PID157921 onln001 is running. Old plans and failed attempt evidence remain intact.

### 05:27 CET —local-log repair preflightPASS;2912 launched

Bothsource-local-logs-v1 andsource-zero-packed-v6 passed exact source/runtime/
compiled-input equivalence audits. Launched the immutable local-logs-through-
packing-v1 plan underPID170763 onln001 with the recordedSHA256. The old step has
drained; no competing GPU executor exists.2912 starts the observer-disabled
40-case matrix, followed by2913. This is still qualification, not a demonstrated
steady-state performance improvement. The current allocation has about2h7m left;
3811125 remainsdependent and will hold for fresh-node qualification if needed.

### Next candidate prepared only — larger notification/packing intervals

Host-only compilerPID195870 onln001 is checking64 actual fresh/cached SM90a
FP8/BF16 dispatch templates for32/257/4096/16384 tokens, packed0/1 and intervals8/16.
Forward chunk remains3. This does not mutate the immutable source or change its
GPU qualification. Prepared3100–3123 correctness and three matched repeats,
not staged/launched; they require3000–3011PASS, performance review and compilation.

Source-derived counts for the all-remote-eligible mixed4K fixture: interval3
packing reduces payload PUTs4096→1536; interval8→512; interval16→256. Average
packed request sizes are11.52/34.56/69.12KB respectively. Remote tail atomics are
1536/768/512: the final finish notification is sent even if the last normal batch
ends exactly on an interval. These exclude barriers, CXI delivery/CSTATE commands
and local tails; they are not measured NIC command counts. Payload stays
17.69472MB/rank, with0.7077888ms serialization bound at25GB/s. See
`packing-command-model-v1.json`. Reduced commands may trade earlier forwarding
for larger batches; correctness and end-to-end measured latency decide promotion.

Host-only interval preflightv1 was stopped during archive extraction:
PID195870 was in`osc_io_setattr_end`, restoring tar attributes on Lustre.
v2 underPID248937 extracts exact regular-file bytes/directories without archive
attribute restoration. It uses a separate checker-hash evidence directory and
leavesv1 partial evidence intact. No GPU/source/runtime mutation. Prepared interval
sequences explicitly set`CXI_EP_FORWARD_CHUNK=3`; without that setting, the wrapper
would default forwarding chunk to the notification interval and confound the test.

### 05:30 CET —2912 ordinary full matrixPASS;2913 running

2912 passed at05:29:47CET, start05:27:11:155.879s total wall time including cold
JIT and persistence. All8ranks completed40cases;320correctness records,
1280operation records,3840CUDA-event samples, noNICwindows. This is the first
complete observer-disabled full matrix after the host-log isolation repair.
2913 is running as an independent cold repeat. Host-only interval compilationv2
has started producing actualSM90a templatePASS records. No steady-state speedup
claim follows from the host-I/O fixes;2921–2923 will provide ordinary timings.

Release-preparation audit: `prepare_release_checks.py` now carries the qualified
local JIT/results/log settings and rejects observer-enabled repeats. The actual
SGLang smoke script writes `rankN.json` directly through`CASE_OUT`, rather than
using the standalone EP result spool. Before running that phase, use a separately
audited local CASE_OUT directory with post-GPU persistence (or equivalent local
journal) to prevent reintroducing shared-storage skew between iterations. This
is pending harness work; no SGLang integration qualification is claimed yet.

### 05:34 CET —both ordinary matricesPASS; sustained16K started

2913 formallyPASS at05:33:50CET (242.915s including cold JIT/persistence).
Again8×40correctness cases,1280operation records,3840CUDA-event samples.
No benchmark processes remained in the end-of-run sample; the small copy-process
sample caught no active copy. Thus its extra wall time is not assigned to any
particular component without further evidence.2912 and2913 together qualify the
tested ordinary matrix after local runtime logging isolation.2920 sustained16K
is nowrunning;2921–2923 ordinary timing/NIC repeats follow. Larger-batch compiler
has passed all32 interval8 templates; interval16 compilation remainspending.

### 05:36 CET —sustained16K PASS; first ordinary timing repeat running

2920 completedPASS at05:35:39CET:3seeds perrank at16384tokens,8ranks,
24correctness records,96operation records,9600CUDA-event samples.2921 is now
collecting ordinary4K/16K timings and separate600-call NIC windows. No averaging
of the earlier3-iteration correctness matrices into the performance estimate.

### 05:38 CET —first ordinary timing repeatPASS,1/3 only

2921 passed;2922 running. Fresh/cached dispatch and combine medians of per-call
rank-max CUDA latency (ms):4K=2.7524/2.7582/3.2975;16K=10.3708/10.3866/12.9399.
Separate600-call4K NIC windows give fresh dispatchTX7.037GB/s,19.208MB/call,
2.72946ms/window-call; combineTX11.376GB/s,35.903MB/call,3.15611ms/window-call.
RX rates are separate, not added. Window octets include protocol/control traffic;
CUDA and NIC runs are different samples. This1/3repeat result is provisional.

The host-I/O repairs restored reliable test progress but did not remove the
ordinary dispatch bandwidth gap. Useful FP8 serialization bound remains0.7078ms.
The next substantive optimization remains contiguous PUT batching, with correctness
and matching controls required before any speedup claim. Evidence in
`job-3810110/variant-analysis` and`nic-analysis`.

### 05:43 CET —interval8/16 compilationPASS, GPU tests still gated

All64 actualSM90a templates passed with zero spill stores/loads. At4K FP8,
row layout uses124fresh/103cached registers; packed layout146fresh/128cached,
identical forinterval8 and16 and consistent with the earlierinterval3 compilation.
This is compilation evidence, not GPU correctness or a performance result.
Artifacts: `preflight-source-zero-packed-v6-intervals-v2/compile.json` and
`register-summary.json`, checkerSHA256prefix`3e74077477ed`.
Prepared interval tests remain unstaged until3000–3011 qualify and timings are
reviewed. Forward chunk is explicitly3 in both compiler and proposed GPU plans.

### 05:46 CET —2923 post-run report-copy blockage isolated

All GPU processes had exited. A live read-only sample found node0cpPID265782
in`osc_extent_wait`, reading a just-persisted JIT compiler report from the shared
`jit/node0/compiler-reports` directory and copying it into the separate shared
`compiler-reports/node0` directory. This post-GPU readback is redundant and outside
the communication timer.2923 still lacks formal completion; its timing data are
not yet admitted as the third qualified repeat.

Held only the ready-plan parentPID170763 withSIGSTOP to prevent the next phase
from starting while fixing post-run persistence. Its external child continues
2923; the allocation and autonomous goal remainactive. Newimmutable snapshots
`source-local-reports-v1` and`source-zero-packed-v7` copy reports directly from the
original local JIT cache before bulk persistence/removal. Batchedfind-exec propagates
copy errors; failure retains the local cache. Local success/failure testsPASS,
and exact source/runtime/native input auditsPASS. Onlyrunner/node.sh and scheduling
metadata differ; no measured GPU/transport behavior changes.

Prepared new plan`ready-plan-local-reports-through-packing-v1.json`, SHA256
`882924dbedf8029102a234d7162f9629e9a70c08cc3f886ddcaa827a763ac4db`:
3230–3237 matched marker controls then3300–3311 packing. It requires2920–2923PASS
and is not yetlaunched. Existing failures/artifacts and prior plans remainpreserved.

### 05:49 CET —three baseline repeatsPASS; repaired matched/packing plan running

2923 completedPASS; the external qualification phase finished04:46:58UTC.
After checking all2920–2923PASS, no active Slurm steps and no external lock,
retired the held parent170763 and its lock. Launched the repaired plan under
PID121256 onln001 withSHA256`882924dbedf8029102a234d7162f9629e9a70c08cc3f886ddcaa827a763ac4db`.
3230 matched control tiny-stress isrunning;3230–3237 then3300–3311 advance only
on qualification. Maincontroller remainsheld; no competing GPU executor.

Three-repeat medians (ms):4Kfresh2.76782,cached2.75824,combine3.32830;
16Kfresh10.37077,cached10.38658,combine12.85611.4Kfresh range2.75240–2.76909;
combine3.29750–3.35134. Separate4KNIC TX-window medians:dispatch7.03984GB/s,
combine11.35471GB/s. Useful payload, wire octets and CUDA times remain distinct.
The repaired harness is qualified for this matrix; bandwidth optimization remains
unfinished. See refreshedvariant-analysis/nic-analysis for allrepeats.

Prepared interval planv3 now references source-zero-packed-v7 and3300–3311
prerequisites, with3400–3423 newgate names. It is not staged/launched. v7has exact
GPU/archive/runtime identity to the64template-compiledv6; only post-GPU report
copying and scheduling metadata differ. Earlier prepared plans remainunexecuted.

### Control startup3230 —runtime header inode stall, not EP failure

Read-only live inspection identified node0verifierPID269716 in`cl_sync_io_wait`,
reading`runtime/source-marker-probe-v1/marker-control/include/nccl_device/gin/proxy/gin_proxy.h`.
Node1 was waiting at torchrun rendezvous. No EP workers/correctness cases existed.
Stopped onlystep3810110.57 and retained the allocation. The old attempt will
remain a failed startup; it is not counted as a payload or bandwidth failure.

The header's manifestSHA256 is
`1a597ba931239b31bf2dcaed31e26020f0b756c8794b25562e6c05c15dd8c995`, identical
in the testedmarker-zero runtime.76of77 runtime files match betweenvariants.
Prepared`source-local-runtime-v1`: executable source bytes identical to
source-local-reports-v1; a new immutable runtime namespace hardlinks only
hash-matching common files from the provenzero runtime and preserves the distinct
control file. No old source/runtime inode is modified. PreflightPID85549 onln001
checks every selected file and nativebuild byte identity.

Prepared plan`ready-plan-runtime-repair-through-packing-v1.json`,SHA256
`0e382686b504c9147ecf61673a43585fc9a3fc624409ce24d94cbf961ed48dd0`:
3530–3537 retry matched control qualification/timing, then previously unrun
3300–3311 packing. Same GPU mechanisms; only startup storage materialization
changes. This plan is not yet launched; the existing baseline three repeats remain
qualified and the throughput gap remainsunresolved.

Runtime inode-reuse preflightPASS:76commonfiles each forcontrol/replay,77forzero,
with every destination byte hash checked. The failedstartupstep57 drained after
TERM/KILL; its executor stopped normally. Launched the replacement plan under
PID118352 onln001,SHA256`0e382686b504c9147ecf61673a43585fc9a3fc624409ce24d94cbf961ed48dd0`.
3530 nowrunning. Allsource/runtime contents remain identical to their respective
qualifiedparents; this is a storage materialization repair, not a network change.

Prepared a private packed-trace generator (`prepare_packed_trace.py`) and checked
source generation against the exactv7 archive without mutating ordinary sources.
New events113/114/115 encode packed-batch submission (channel,peer,oldtail,rowcount),
notification submission (old/newtail,finishflag), and receiver-observed consumed/
availabletail ranges. They augment the existing lock/command/completion and role
scopes. Receiver observation can cover several earlier submissions; it is not a
per-packet arrival timestamp. Cross-rank comparisons retain calibration bounds.
This is source-generation-only evidence: separate trace packaging, decoder/
validator adaptation, SM90compilation, correctness and disabled/enabled overhead
measurements are still required before any trace claim. Current ordinary packed
snapshots continue to reject tracing.

Matched control3530 completedPASS;3531 sustained16K nowrunning.3530 ran30cases
perrank across8ranks (32/257tokens,5routes,3seeds),240correctness records,
960operation records and96000CUDA-event samples. Both nodes ended with clean
context destruction, CTusage133/rank and3741queue reuses. The new runtime cleared
the observed startup blockage without changing any communication code.

### 2026-10-31 06:06 CET — private packed tracing prepared

Matched marker controls passed tiny and sustained 16K stress; the timing sequence
is running before the ordinary packed-row gates. A separate `source-packed-trace-v1`
snapshot adds packed payload batch submission (113), tail notification ranges (114),
receiver-observed consumed/available tails (115), TX publication (209), delivery
markers (210), NIC fences (211), CSTATE submission (212), and atomic notification
submission (213). The ordinary packed archive and parent runtime remain unchanged.
Private source generation and dependency validation passed; host SM90a compilation
is running, with no trace GPU execution or performance claim yet. Captures retain
per-rank clock bounds and tracing-disabled before/after measurements. These scopes
measure GPU submission/observation, not actual NIC wire timestamps, and overlap.

Private trace preflight subsequently passed all 12 actual SM90a FP8 4K
dispatch templates (row/packed, fresh/cached, notification intervals 3/8/16).
Evidence: `preflight-source-packed-trace-v1/`. No trace GPU run yet.
`analyze_packed_chains.py` matches each packed batch to notification ranges and
receiver observations, allowing several batches to share one observation.
Clock sign and cumulative-range tests pass; real-trace validation is pending.
Cross-rank delay bounds assume offset remains inside the pre/post calibration
envelope; they do not isolate packet transit or guarantee exact clock synchronization.

First matched repeat (preliminary, not the final three-repeat comparison):
control/zero fresh dispatch 2.676/2.764 ms at4K and10.654/10.411ms at16K;
combine3.785/3.288ms at4K and14.734/12.859ms at16K. These indicate an
operation-specific completion-policy tradeoff rather than uniform acceleration.

### 2026-10-31 06:20 CET — matched controls complete, packing entered

All3530–3537 gates passed. Same-node three-repeat medians:

| Policy | 4K fresh / cached / combine ms | 16K fresh / cached / combine ms |
|---|---:|---:|
| Payload delivery ACK (marker-control) | 2.670 / 2.662 / 3.785 | 10.623 / 10.643 / 14.715 |
| Send completion + zero-byte delivery marker | 2.764 / 2.764 / 3.309 | 10.388 / 10.378 / 12.725 |

The executor advanced to3300, the row-wise control stress gate in
`source-zero-packed-v7`; packed-layout GPU qualification remains pending.
A future `source-packed-delivery-control-v1` compares the same packed archive
with these two delivery policies. Only variant definitions and the sequence
change; compilation is running and no GPU step has been submitted for that
comparison. Hypothesis: when packing leaves one payload per notification,
acknowledging that payload directly may remove a redundant explicit marker.
It is not yet a measured optimization, and combine currently favors batching.

Read-only `watch_status.py` now records `live-status-fast.json` every20seconds
independently of the potentially slow bulk collector. The main controller's
intentional `PAUSED_FOR_DEBUG` does not mean GPU work has paused when the
external executor is RUNNING and holds its lock. No competing GPU executor exists.

### 2026-10-31 06:31 CET — first packed-layout GPU gate running

The new snapshot's row-wise controls3300–3302 passed:30 irregular/stress
cases per rank,20 4K FP8/BF16 routing cases per rank, and12 dropped-token
cases per rank.3303 now runs the packed layout for the first time on all
eight ranks. No packed-layout PASS or performance result is claimed yet.
The initial3300 gate included a cold native build; sampled processes showed
compilers running. Its GPU logs ended in clean context teardown with133
allocated CTs and3741 queue reuses per rank.

The optional delivery-control preflight is running asPID203010 on
clariden-ln001. Its upload was delayed in `osc_io_setattr_end`, then completed
without intervention; no GPU job was affected. The prepared plan remains
unsubmitted and depends on successful completion/review of3300–3311.

### 2026-10-31 06:37 CET — packed correctness passed, ordinary timing started

All six layout qualification gates3300–3305 passed. For the packed layout,
this is30 irregular/stress,20 4K FP8/BF16 routing, and12 dropped-token
cases per rank, across eight ranks. The matched ordinary timing sequence
3306–3311 is now running (4K and16K FP8, three repeats per layout).
There is no three-repeat packed performance conclusion yet.

`source-packed-trace-v2` passed12 actual SM90a dispatch-template compilations.
It adds event214 for the already-read queue RP/WP cursors at admission, after
the capacity-wait scope ends; it adds no NIC-register read. The trace has not
run on GPUs. Its prepared external gates are3620–3621 to keep the superseded,
compile-only v1 namespace distinct.

The optional `source-packed-delivery-control-v1` passed48 actual packed
FP8/BF16 fresh/cached templates, sizes32/257/4096/16384 and intervals3/8/16.
GPU qualification is pending. The interval sweep was reordered in prepared v4:
finish the interval16 correctness and three matched repeats before interval8,
with new gate names4000–4023 and forward chunk3 fixed. It is not launched yet.
The release-check generator additionally includes16K correctness for both
formats in every model; final SGLang/model release checks remain outstanding.

### 2026-10-31 06:43 CET — first matched packed timing pair (preliminary)

Both3306/3307 are formally PASS. This is one repeat per layout, not the
final three-repeat result:

| Tokens/GPU | Row fresh dispatch | Packed fresh dispatch | Row combine | Packed combine |
|---:|---:|---:|---:|---:|
|4,096|2.7573ms|2.1980ms|3.3129ms|3.3236ms|
|16,384|10.3693ms|8.6983ms|12.8579ms|12.8042ms|

Packing reduces dispatch by about20%/16%, while combine remains essentially
unchanged. Fresh and cached dispatch are very close. This supports request
aggregation as a useful optimization, but it does not close the bandwidth gap.
The remaining repeats continue. The next prepared comparison holds the
forwarding chunk at3 and varies notification interval to16 and8, using both
layouts so progress frequency and payload aggregation can be distinguished.

### 2026-10-31 06:54 CET — three-repeat packing result; interval16 running

All3300–3311 passed and were collected. Packed fresh dispatch medians are
2.1980ms(4K) and8.6983ms(16K), versus2.7558ms and10.3807ms row-wise.
The4K ranges were2.1898–2.2034ms packed and2.7518–2.7573ms row-wise.
Fresh/cached dispatch are close; combine remains near3.3ms at4K.

The prepared interval16 plan was launched in3810110 with source-zero-packed-v7,
forward chunk3 fixed, trace/watch disabled, PID281252 onclariden-ln001.
Plan SHA256: `29ebdef31efe69323aa952201d0c285b9a4d882aeea193b92cf607d18ecea1a6`.
Gates4000–4011 finish both layouts' correctness and three matched repeats,
then hold for review. No competing executor runs. A follow-up allocation is
pending after this one; fresh qualification is required on new nodes.

Next hypothesis: full EP with257 contexts may reduce channel aliasing versus129.
With64SMs and four communication channels/SM,129 provides about two queues/SM,
while257 provides four. Historical combine traces contain lock waiting and
4096 row-sized8256-byte puts per rank/capture; combine has not been packed.
The raw transport ladder already tested129/257 with the same producer mapping
and showed only a small difference, so a full-EP benefit is not assumed.
A separate actual-template compiler preflight is being prepared; no257-context
EP GPU result is claimed. Final-tail notification merging is also CPU-modeled
only, with no GPU snapshot or execution yet.

### 2026-10-31 07:00 CET — interval16 correctness passed; next controlled comparisons

All4000–4005 passed: row-wise and packed layouts, irregular sizes32/257,
4K FP8/BF16 routing, and dropped tokens. The ordinary matched repeats4006–4011
are running. No interval16 performance conclusion is available yet.

The257-context preflight passed20 actual SM90a templates (fresh/cached FP8/BF16
and combine, sizes32/257/4096/16384), with no register spills. The prepared
4100–4109 full-EP comparison has not launched. Static mapping in
`results/deepep_pipeline_20261030/context-channel-mapping.json` confirms:

| Operation |129 contexts: data-channel sharing|257 contexts: data-channel sharing|
|---|---|---|
|Fresh dispatch|128 queues each shared by2 channels|256 queues each owned by1 channel|
|Cached dispatch / combine|127 queues shared by2,2 queues with1|256 queues each with1|

This excludes transient barriers and NVLink-only roles. It is a source mapping,
not proof that context sharing causes the whole latency gap. The timing analyzer
now verifies actual QPs, allocated contexts, SMs and intervals in every rank's
correctness records before admitting results. A mismatch-rejection check passed.
The supplementary lifecycle analyzer verified the prior30-case packed stress:
all ranks plateaued at133 CTs with3741 reuses and clean retirement refreshes.

`source-final-tail-v1` is staged and compiling64 actual dispatch templates.
Its only DeepEP archive change is in `hybrid_dispatch.cuh`: the last full batch
can share the existing mandatory finish update. The flag defaults off; intermediate
updates, partial-batch handling, empty-channel finish, combine, transport and
ordering are unchanged. The10,340-case CPU notification model passed earlier.
This candidate has no GPU result yet. Compilation runs on the login node;
only the interval16 experiment currently owns the GPU executor.

### 2026-10-31 07:09 CET — interval16 three-repeat result and context test launched

All4000–4011 passed and were collected. Packed interval16 fresh dispatch was
1.0602–1.0619ms at4K and3.4930–3.5031ms at16K; medians1.0606/3.4981ms.
The same source's row-wise interval16 medians were2.3761/8.9123ms.
Against row-wise interval3, packed interval16 improves dispatch by61.5%/66.3%.
Combine remains unchanged within these comparisons. This is a measured aggregation
benefit, not evidence that all synchronization overhead has disappeared.

NIC-window median TX rates at4K, three repeats: rows/I3=7.038GB/s,
packed/I3=8.762GB/s, rows/I16=8.169GB/s, packed/I16=17.906GB/s for fresh dispatch.
The packed/I16 useful-payload rate computed from17.69472MB and CUDA latency
is16.684GB/s; its16K equivalent is20.234GB/s. A two-point size fit suggests
roughly21.8GB/s slope and0.25ms intercept, but the full2K–16K sweep is still
required to distinguish a fixed term reliably.

Started `prepared-ready-plan-packed-i16-q257-v2.json` in3810110, PID124341 on
clariden-ln001, source-zero-packed-v7. SHA256:
`171a7912fe8b7bddd8dd3722904e9189e29016d01a047088d1774b3cc28e732a`.
Gates4100–4109 first qualify257 contexts (stress,4K,dropped, sustained16K),
then compare129/257 in three alternating ordinary repeats. The unlaunchedv1
plan is superseded. Timing gates use a300s step timeout after qualification:
all six just-completed matched repeats took95.8–99.7s; the180s allocation-end
guard remains. Correctness timeouts are unchanged.

The hypothesis is specific: a finishing channel can hold a shared context lock
while waiting for completion and block a partner that still has payload to issue.
257 contexts separate all256 data channels; barrier accesses remain distinct
from this steady-state ownership analysis. The raw prepacked ladder's small
129/257 difference does not establish the full EP outcome.

`source-final-tail-v1` passed64 actual dispatch templates, zero register spills;
GPU qualification remains pending. `source-packed-trace-v2` additionally passed
six actual traced fresh/cached/combine templates at129/257 contexts andinterval16.
Prepared trace gates4300/4301 have not launched. A matched8256-byte raw combine
ladder is a next diagnostic: the existing4320-byte raw ladder is not a matched
combine control and must not be presented as one.

### 2026-10-31 07:13 CET — context resources verified; dispatch mechanism quantified

4100 passed30 cases/rank at actual257 QPs on all eight ranks. Supplementary
`context-qualification.json` verifies each rank plateaued at261 CTs, reused7453
queues, and completed7710 teardown refreshes cleanly.4101 also passed;4102 is running.

At fixed interval16, packing reduces source-derived payload PUTs from4096 to256
at4K and from16384 to1024 at16K. The matched fresh-dispatch latency reductions
are1.3155ms and5.4142ms: roughly0.343/0.352microseconds per removed payload PUT.
This is an effective paired-run penalty, not the timing of an isolated function;
packing also changes layout/register use and overlap. Its near scaling with
request count strengthens the diagnosis that row-level submission granularity
was costly. Evidence: `packing-matched-request-penalty.json` in the campaign root.
The fixed-byte comparison does not establish that every remaining wait is avoidable.

### 2026-10-31 07:26 CET — context comparison complete; matched raw probes compiled

All4100–4109 passed. Three-repeat medians, packed interval16, ordinary builds:

| Contexts |4K fresh dispatch|4K combine|16K fresh dispatch|16K combine|
|---:|---:|---:|---:|---:|
|129|1.05944ms|3.30016ms|3.49856ms|12.76147ms|
|257|1.20045ms|3.41466ms|3.67626ms|12.80512ms|

Doubling contexts slows fresh dispatch by13.3% at4K and5.1% at16K, and does not
improve combine. Retain129 contexts. The context-lock hypothesis alone does not
explain the total cost: removing data-channel sharing can move the bottleneck
instead of removing it. These are three repeats on the same node pair, not an
independent-node reproduction. Evidence: `job-3810110/context-comparison-i16.json`.

`source-transport-ladder-v1` passed compilation of the actual native probe with
4320- and8256-byte rows. Its transport and DeepEP inputs are identical to
source-zero-packed-v7. The probe compares row-wise PUTs with prepacked contiguous
PUTs at4K/16K and129/257 contexts, without NVLink relay or expert reduction.
It records per-channel readiness, submission, completion and receiver-observation
boundaries on local GPU clocks. These are software observations, not NIC wire
timestamps. No GPU probe result is available yet. The analyzer now uses the
recorded row width and rejects mismatches;8256-byte accounting and rejection
checks passed.

Prepared `prepared-ready-plan-allocation2-context-ladder-v2.json` for3811125,
SHA256 `ced52213898a3d0fe5b89fbded87e11a89022f9b170bacc52a77d768129f17e9`.
It runs fresh qualification and paired repeats, private129/257-context traces,
then eight matched-width raw probes. All prerequisites belong to the new
allocation. The plan holds the allocation after completion for diagnosis.
It has not launched yet. The older allocation2-context-v1 plan is superseded.

### 2026-10-31 07:29 CET — allocation handoff and serving qualification preparation

3810110 finished COMPLETED/0:0 after all4100–4109 passed. Its executor was
COMPLETE_HELD with no GPU step active. The controller received a graceful STOP
because the next tracing/probe phase cannot fit its remaining window.3811125
is pending on scheduler priority/resources. A single-use launcher, PID226673 on
clariden-ln001, is armed for the exact reviewed allocation2-context-ladder-v2
plan hash above. It waits for RUNNING plus PAUSED_FOR_DEBUG, delegates to the
existing exclusive launcher, and exits. It does not generate code, submit jobs
or retry failed tests. Both live collection and the20-second status watcher remain active.

Prepared source-serving-local-v2, with the exact same DeepEP archive, GPU transport,
NCCL runtime and compiled inputs as source-zero-packed-v7. Its only changes are
SGLang journal/cache paths, post-exit persistence, and evidence checking. Each
SGLang case records actual adapter SMs, allocated/used contexts, token capacity
and physical topology; qualification also verifies packing/interval compiler
flags. A synthetic mismatched-QP rejection test passed. This is not GPU serving
qualification. V1 was never GPU-run; V2 supersedes it for serving checks.

Prepared24 release gates for129contexts/interval16/packed dispatch: FP8/BF16
correctness at257/4096/16384 tokens for each model, three ordinary geometry
repeats, the optimized2K–16K sweep repeated three times, then actual SGLang
scatter/gather and reduced-FFN expert-kernel checks. No full-model TTFT claim is
planned from these smoke tests. The release plan has not launched and requires
fresh per-allocation qualification. Qwen3/MiniMax actual-template compilation
is running on the login node (PID161464); GPU tests remain pending.

Combine optimization decision gate: the current kernel reduces NVLink contributions
then issues one row-sized PUT to the original token-indexed receive layout.
Those per-channel token indices are strided, so dispatch's contiguous batch PUT
cannot simply be copied into combine. A possible subsequent experiment would
permute the intermediate receive layout by channel, stage consecutive remote
rows, batch their PUTs, and undo that mapping in combine_reduce_epilogue. It
would have to preserve sparse/dropped routes, local bypass, top-k weights and
completion ordering, and pass both a layout-only control and a batched arm.
This is a design hypothesis, not implemented or qualified. First use the matched
8256-byte raw probe and new traces to establish whether that complexity is justified.

### 2026-10-31 07:32 CET — model-template preflight complete

All30 actual Qwen3/MiniMax SM90a templates passed compilation at257/4096/16384
capacity, FP8/BF16 fresh/cached dispatch and combine,129contexts, interval16,
packed dispatch. No register spills were reported. Evidence is under
`results/deepep_pipeline_20261030/preflight-source-serving-local-v1/`;
V2 has identical compiled inputs. This is compilation only: cross-model GPU
correctness, optimized full size sweeps, SGLang integration and new private
trace qualification remain pending.3811125 is still pending on priority;
the single-use reviewed-plan launcher is waiting and monitors remain active.

### 2026-10-31 07:33 CET — follow-up running on a different node pair

3811125 started on nid006152/nid007356 (previous pair nid006898/nid007571).
The single-use launcher successfully handed off the reviewed context-ladder-v2
plan at06:33:05UTC to executor PID81923 on clariden-ln001. Fresh qualification
starts at5000; private tracing and matched raw transport follow. This is a new
node pair, but reproduction is not established until its measurements pass.
The preceding goal turn made progress: completed context experiment, established
129-context preference, compiled matched-width/model probes and prepared audited
serving checks. The current turn confirms a live Slurm allocation and executor.

Prepared allocation-local final-tail gates5300–5313 for later review, retaining
both unchanged/merged arms, all correctness/stress cases and three paired
ordinary repeats. This plan has not launched; it does not modify the running
source or active sequence. The full release/SGLang plan remains separate.

### 2026-10-31 07:37 CET — new-node stress passes; finer transport controls compiled

5000 passed30 cases/rank on all eight ranks of nid006152/nid007356. Supplementary
lifecycle checks confirm actual129QPs,133CT maximum,3741queue reuses and3870
completed retirement refreshes per rank.5001 is running. The main executor is
live; no other GPU experiment executor was launched.

Prepared and compiled source-transport-cadence-v2. It retains the exact current
EP/transport inputs and extends only the raw probe/validator to separate:
individual row PUTs; nonaggregated publication every3rows;16-row PUT batches;
and16-row batches with strong notification every16rows. Tests cover both row
widths and4K/16K,129contexts,30rounds. PUTs split at requested boundaries so no
notification is skipped. A9600-case CPU boundary/count model passed, followed by
actual native probe compilation. GPU tests have not run. Localv1 packaging
failed before staging because the replacement helper did not accept a count
argument; the correctedv2 uses separate checked replacements. The incomplete
localv1 directory is explicitly excluded. No running source was changed.

This comparison is needed because the earlier coalesced raw probe sends all
rows of one channel in one PUT: at16K that is64rows, whereas current full EP
uses16-row batches. Final-only raw signals also differ from full dispatch's
periodic progress notifications. Do not assign the raw/full-EP latency difference
entirely to NVLink or reduction. New controls isolate those scheduling choices.
The updated analyzer preserves all20 historical measured results exactly.

To avoid redundant native builds, three future source snapshots reuse the
same-allocation v7 native build only after confirming identical complete DeepEP
archives and all77runtime files. New probe kernels, plugins, frontend and JIT
measurements still execute from their requested snapshots. Trace and final-tail
sources are excluded from this reuse. Evidence is
`jobs/3811125/native-build-equivalence-raw-serving.json` on Clariden.

07:38 CET update:5001 also passed on all8ranks (4K FP8/BF16 routing matrix).
5002 dropped-token correctness is running; fresh-node performance repeats and
private traces have not completed. Slurm step3811125.2 is live.

### 2026-10-31 07:50 CET — second-node-pair correctness complete

All5000–5007 passed on all eight ranks of nid006152/nid007356, including
irregular routes, FP8/BF16, dropped tokens and sustained16K at both129 and257
contexts.5007 ended06:48:05UTC with returncode0; the temporary absence of a
GPU step was normal post-run validation/transition, not a failed experiment.
5008 is now the first ordinary timing repeat. Executor81923 remains the sole
GPU experiment owner;3811125 is RUNNING with over3h40 remaining.

Prepared analysis and follow-up work, without changing the running source:
- Trace owner analysis now accepts an empty overlap table (expected to be
  possible when257contexts eliminate channel sharing). A synthetic96-role
  fixture passed. A context-comparison figure tool is ready, but new traces
  have not yet been collected; it separates ordinary, instrumented-disabled
  and instrumented-enabled measurements and labels stage intervals nonadditive.
- SM32/129contexts compiled all20 real templates with no spills. This remains
  an unrun parallelism candidate; the qualified baseline is64SM/129contexts.
- Full size-sweep analysis requires all three complete eight-size ordinary
  repeats and pinned source/configuration checks, and refuses incomplete data.
  The prepared release-v2 plan balances size order ascending/descending/mixed.
  No optimized full sweep or SGLang GPU validation has run yet.

Next: finish new-node repeats, private tracing and matched4320/8256-byte raw
transport tests; review those results, then run release-v2 cross-model/size/
SGLang checks while selecting further changes from measured evidence.

### 2026-10-31 07:53 CET — first ordinary repeat agrees on new nodes

5008 passed and its complete per-rank/source/compiler evidence was collected.
First-repeat fresh FP8 dispatch is1.0656ms at4K and3.4942ms at16K; combine is
3.3822ms and13.0246ms. This is one of three repeats, not a completed replication
study.5009 (257contexts, repeat1) is running in the same retained allocation.
The first new-node result supports retaining the existing packed/I16 candidate
while we finish the diagnostic and release gates.

Exported `results/deepep_pipeline_20261030/review-bundle-packed-i16-v1/` from
the actual immutable snapshot rather than the older developer worktree.
`DeepEP.patch` changes four files: runtime-library guard, backend-independent
barrier, packed channel helper and hybrid dispatch. Applying it to a second
clean bd1e1669 checkout reproduced every core source file; all128fmt files also
matched the separately pinned archive, giving238total source files verified.
The exact host/device transport and runner are included in snapshot/. This is
source reconstruction only: the matching private NCCL library, site container
and allocated CXI resources remain required. It is not a clean GPU rerun,
standalone generic Slingshot installer or upstream submission. Current running
sources and the original local DeepEP checkout were not modified.

## Feedback from Claude on the optimization campaign — 2026-11-01

Scope: the entries from "Runtime update and response to the second review" (13:31 CET,
2026-10-30) to "first ordinary repeat agrees on new nodes" (07:53 CET, 2026-10-31), plus
the results that job 3811125 collected after the last entry (gates 5008–5015 and
5200–5207, allocation completed 10:29 UTC). Every headline number quoted below was
recomputed from the per-gate files under `results/deepep_pipeline_20261030/` and
`results/deepep_size_sweep_20261030/`; the document's figures agree with the raw data
wherever I checked. The two packed-dispatch device traces (5014/5015) had been
collected but not analysed; I ran the campaign's own `analyze_trace.py` on them and
the outputs are now under each gate's `trace-analysis/`. No job was submitted, no
source changed.

### 1. Verdict

The campaign reached the transport target it set out with. Fresh FP8 dispatch at
4096 tokens/rank fell from 3.399 ms to 1.060 ms (−69 %), and at 16384 tokens/rank from
10.46 ms to 3.50 ms (−67 %), reproduced on a second node pair (1.066 / 3.496 ms). At
16K the useful payload rate is 20.2 GB/s, which is the "80 % of nominal" aspirational
target of the 10_29 plan. The decisive change was not in the transport at all but in
DeepEP's request granularity: packing each channel's remote rows contiguously and
issuing one PUT per notification interval. The transport changes that mattered were
Cassini-native, threshold completion and the CQ fence, plus doorbell batching; lock-free
reservation was never needed. Combine was not touched and is now the bottleneck at
2.4 times its serialization bound. The user's observation is correct: at 4K about a
third of dispatch time and about 60 % of combine time is still not wire transfer, and
the new traces say where it is (section 4).

### 2. Verified results, V4 Flash geometry, EP8, one rail at 25 GB/s

| Configuration | 4K fresh dispatch | 4K combine | 16K fresh dispatch | 16K combine |
|---|---:|---:|---:|---:|
| Original baseline (job 3801971) | 3.399 ms | 4.387 ms | — | — |
| Threshold completion | 2.766 | 3.664 | 10.46 | — |
| Native fence + batched delivery, rows, interval 3 | 2.756 | 3.328 | 10.38 | 12.86 |
| Packed rows, interval 3 | 2.198 | 3.32 | 8.70 | 12.80 |
| Rows, interval 16 | 2.376 | 3.31 | 8.91 | 12.76 |
| **Packed rows, interval 16, 129 contexts** | **1.060** | 3.30 | **3.498** | 12.76 |
| Same, 257 contexts | 1.200 | 3.41 | 3.676 | 12.81 |
| Same, second node pair (5008–5013) | 1.066 | 3.379 | 3.496 | 13.08 |
| Payload serialization bound | 0.708 | 1.353 | 2.831 | 5.411 |

Combine bytes use the 8256-byte BF16 row the campaign itself adopted for the matched
ladder. Useful-payload rates for the final configuration: dispatch 16.7 GB/s at 4K and
20.2 GB/s at 16K; combine 10.2 GB/s and 10.6 GB/s.

Two supporting measurements explain the shape of the gains:

- Size sweep before packing (job 3806153): T = 0.212 ms + 0.1447 ms/MB, R² 0.99998. The
  per-call intercept was small and the slope was 6.9 GB/s, so the old gap was a
  per-request cost, not a fixed one. The matched packing comparison later quantified it
  at 0.34 to 0.35 µs per removed payload PUT, identical at 4K and 16K.
- Raw transport ladder, final zero-marker transport (5200–5207, recomputed):

| Row width | Mode | 4K, 129 ctx | 4K, 257 ctx | 16K, 129 ctx | 16K, 257 ctx |
|---|---|---:|---:|---:|---:|
| 4320 B (FP8 dispatch) | one PUT per row, final signal | 2.211 ms (8.0 GB/s) | 2.177 | 8.689 (8.2 GB/s) | 8.714 |
| 4320 B | one PUT per channel | 0.923 ms (19.2 GB/s) | 0.886 | 3.335 (21.2 GB/s) | 3.297 |
| 8256 B (BF16 combine) | one PUT per row, final signal | 2.803 ms (12.1 GB/s) | 2.733 | 10.364 (13.1 GB/s) | 10.350 |
| 8256 B | one PUT per channel | 1.654 ms (20.4 GB/s) | 1.620 | 6.253 (21.6 GB/s) | 6.240 |

Coalesced transfers sit at 19 to 22 GB/s regardless of row width or context count. The
row-granularity penalty is the whole story for dispatch and most of it for combine.

### 3. Where the remaining time goes

From the packed interval-16 traces (5014 at 129 contexts, 5015 at 257), medians over
eight ranks and three captures of the latest-finishing warp per role. Recording adds
about 20 % to dispatch in the instrumented build, so use these as structure, not as
latency.

| Role, 4K | Duration | Wait union | Dominant wait | At 257 contexts |
|---|---:|---:|---|---|
| Dispatch sender | 0.296 ms | 0.171 | context lock 0.163 ms | lock 0.003, duration 0.232 |
| Dispatch forwarder | 1.109 ms | 0.999 | arrival wait (event 105) 0.999 ms | same, 1.024 |
| Combine forwarder | 3.062 ms | 2.702 | lock wait 2.457 ms behind a partner that is in its completion flush | lock 0.03, completion flush 2.48, CT writeback wait 2.47 |

Dispatch. The sender finishes issuing in 0.3 ms and the kernel's lifetime is set by the
forwarder waiting for remote data to arrive. The GPU-side submission path is no longer
the bottleneck; what remains is network-side: NIC command processing and packetization
of 256 PUTs of 69 KB at the 2112-byte MTU, the tail notification after each PUT, and the
start-up exchange of rank and expert counts before any payload moves. The arithmetic
is consistent: the pure-transport coalesced probe already needs 0.92 ms at 4K against a
0.71 ms bound, so about 0.21 ms of the excess is transport-intrinsic and about 0.14 ms
is EP work around it. At 16K the probe is 3.33 ms against 2.83 ms, a sustained
21.2 GB/s. Nominal 25 GB/s is the raw link rate; with 2112-byte packets and headers the
achievable payload rate is lower, so 20 to 21 GB/s is probably close to the practical
ceiling. The remaining dispatch lever is therefore the fixed 0.25 ms, not bandwidth.

Combine. Nothing has changed here since the delivery-batching patch. The forwarder
issues one 8256-byte PUT per reduced token, 4096 per rank, then waits in the final
flush for all of them to complete. At 129 contexts that wait appears as lock wait
because the partner warp holds the lock while flushing; at 257 contexts it appears
directly as 2.47 ms of CT-writeback wait. Either way the kernel is waiting for the
NIC to drain row-sized requests at 12 to 13 GB/s, exactly the rate the 8256-byte
rows-final probe shows. The 1.95 ms excess over the bound decomposes approximately
as 1.15 ms row-granularity penalty (probe rows-final 2.80 versus coalesced 1.65),
0.5 ms EP work above the probe, and 0.3 ms transport-intrinsic. These come from
interventions, not from an additive timeline.

### 4. What I would do next, in order

1. **Pack combine.** This is the single largest remaining lever: roughly 1.1 ms at 4K
   and 4 ms at 16K if combine follows dispatch's probe-to-EP ratio. The document's
   design sketch is right: permute the scale-out receive layout so each forward warp's
   remote rows are contiguous, issue one PUT per batch, and undo the permutation in
   `combine_reduce_epilogue`. The matched 8256-byte ladder requested as the decision
   gate has now been run and justifies the work. Keep the layout-only control arm.
2. **Dispatch fixed term.** Measure before patching: the trace stages 110 (signal),
   113/114 (packed payload and tail submission) and the notify phase are all there.
   The prepared final-tail merge and CSTATE deferral are small; the notify exchange
   round trips before the first payload are the more likely 0.1 to 0.2 ms.
3. **Stop spending on contexts and credits.** 257 contexts is slower (+13 % at 4K); the
   cached-credit arm is quarantined after a sustained failure and gave at most 1.4 %
   in probes. Neither is worth another allocation.
4. **Release qualification before more optimization.** The packed/interval-16 candidate
   has V4 Flash correctness on two node pairs but no Qwen3 or MiniMax GPU correctness
   and no SGLang scatter/gather run with the new transport. Those 24 release gates are
   prepared and should run before the next transport change, because every later
   comparison will be made against this candidate.
5. **Generalize the packed prototype.** `hybrid_dispatch.cuh` carries a static assert
   requiring exactly two scale-out nodes. EP16 and EP32 need the channel-slice helper
   to handle more peers before this can leave the EP8 testbed.

### 5. Correctness and process notes

- Two real defects were found and fixed and must be part of any release: the one-byte
  replay delivery marker that could overwrite a notification the receiver had already
  consumed and cleared (reproduced 800/800, replaced by a zero-byte PUT marker), and
  the CT-ID exhaustion from channels that were closed instead of pooled because their
  cached completion count lagged the hardware (fixed by a teardown-time refresh;
  usage now plateaus at 133 CTs per rank).
- The threshold trigger fields copied from `hip_cntr_test.cpp` have now survived
  thousands of cumulative flushes across every gate, so the counter-reset concern I
  raised is empirically closed for this configuration. A one-line CT_GET audit after a
  fired trigger would still make it documented rather than observed.
- Most of the night's failures were not transport failures: collective timeouts in
  1804, 2210, 2260 and 2612 traced to Lustre stalls during JIT compilation and result
  logging, and the fix was node-local JIT caches, logs and result spooling. Roughly
  half of allocation 3810110 went to this. Those settings should be the default for
  every future gate, including the SGLang path, which the document notes still writes
  through shared storage.
- The context lock was never the problem it looked like. Both the fence traces and
  the ladder's 129 versus 257 comparison showed that lock waiting was a producer
  waiting behind another producer's completion wait; removing the sharing moved the
  wait rather than removing it. The campaign drew the right conclusion and did not
  build lock-free reservation.
- GDAKI comparison, closing the loop on the 10_30 review: of the mechanisms in that
  table, the ones that paid were threshold completion and the native CQ fence, both
  Cassini-specific, plus doorbell batching. The two mlx5-shaped items, per-WQE
  completion polling and lock-free slot reservation, were correctly left out.

### 6. Document notes

- The log ends at 07:53 CET on 2026-10-31 although the allocation ran to 10:29 UTC and
  produced the new-node repeats, both packed traces and the eight-gate matched-width
  ladder. Those results are the strongest evidence in the campaign and should be
  written up; section 2 and 3 above can serve as the draft.
- At 3,582 lines the file is a running log. A consolidated results section near the
  top, carrying only the table in section 2, the ladder table, the trace table and the
  list of qualified snapshots, would let a reader find the state without reading the
  night.
- The headline "80 % of 25 GB/s" target is met at 16K and nearly met at 4K for
  dispatch. The document should say so plainly, and then say equally plainly that
  combine has not been optimized at all and is now the gating operation.
