# DeepEP v2 direct GIN on Slingshot — 2026-11-01 optimization campaign

Date: 2026-11-01. Operator: Claude (agentic session, ~20 h window authorized by the user
after the CSCS certificate refresh at about 21:45 CET). Continues
[10_30_DeepEP_v2_Slingshot.md](10_30_DeepEP_v2_Slingshot.md); its final section
("Feedback from Claude on the optimization campaign — 2026-11-01") is the starting
analysis for this file. Same conventions: every number comes from per-gate files under
`results/`, timing is the median of per-iteration rank maxima over eight ranks, and
nothing is promoted without its own correctness gates on GPUs.

## Target

For DeepEP v2 (pinned `bd1e1669`) over the private direct-CXI GIN backend (type 6,
`needsProxyProgress=0`) on two Clariden GH200 nodes (EP8, four ranks per node):

1. Bring fresh FP8 dispatch and BF16 combine as close as possible to the pure
   per-rail payload serialization time at the measured link ceiling, and account for
   whatever remains.
2. Fix the remaining defects and gaps found in the 10_30 campaign (combine unpacked,
   dispatch fixed term, EP8-only static assert, release matrix never run with the
   final transport).
3. Re-evaluate the result: V4 Flash/Qwen3/MiniMax geometries, 2K–16K size sweep,
   SGLang scatter/gather and expert smoke, on a fresh allocation.

Reference bounds (one rail, 25 GB/s nominal; coalesced raw probe sustains 21.2–21.7 GB/s):

| Operation | Tokens/rank | Bytes per rail | Bound at 25 GB/s | Bound at 21.5 GB/s | Best measured so far |
|---|---:|---:|---:|---:|---:|
| FP8 dispatch (4320 B/token) | 4096 | 17.69 MB | 0.708 ms | 0.823 ms | 1.060 ms |
| FP8 dispatch | 16384 | 70.78 MB | 2.831 ms | 3.292 ms | 3.498 ms |
| BF16 combine (8256 B/token) | 4096 | 33.82 MB | 1.353 ms | 1.573 ms | 3.300 ms |
| BF16 combine | 16384 | 135.27 MB | 5.411 ms | 6.292 ms | 12.76 ms |

"Close to pure transfer" is therefore judged against the 21.5 GB/s row, which is what
this NIC delivers for large contiguous PUTs in the matched raw probe; the 25 GB/s row is
the raw link rate and is not attainable with 2112-byte packets.

## Starting configuration (qualified candidate from 10_30)

- Transport `marker-zero` (snapshot `source-zero-packed-v7`, ABI 3): credit-based TX
  slot reuse, `C_CMD_CT_TRIG_EVENT` threshold completion, native CQ fence before
  signals, CT_SEND payloads with a zero-byte same-endpoint delivery marker, doorbell
  publication batched up to 8 descriptors. Context lock retained; 129 contexts; 64 SMs.
- DeepEP dispatch: contiguous per-channel staging of remote rows, one PUT per
  notification interval, interval 16, forward chunk 3 (`CXI_EP_PACK_ROWS=1`,
  `CXI_EP_UPDATE_INTERVAL=16`, `CXI_EP_FORWARD_CHUNK=3`).
- DeepEP combine: unchanged upstream path, one 8256-byte PUT per reduced token.
- Harness: node-local JIT cache, result spool and logs (the Lustre stalls of 10/31
  otherwise cause collective timeouts); CT lifecycle refresh at teardown.
- Measured 10/31, two node pairs: dispatch 1.060/1.066 ms at 4K and 3.498/3.496 ms at
  16K; combine 3.30/3.38 ms and 12.76/13.08 ms.

## Plan

| Allocation | Snapshot | Content | Status |
|---|---|---|---|
| A | `source-1101-release-v1` (GPU code identical to v7, SGLang local-journal harness) | Fresh qualification of the candidate, three ordinary repeats, then the 24 prepared release gates: FP8/BF16 correctness for V4 Flash, Qwen3, MiniMax at 257/4096/16384; three geometry timing repeats per model; 2K–16K size sweep ×3; SGLang scatter/gather and reduced expert smoke per model | packaging done, launching |
| B | `source-1101-combine-pack-v1` | Combine packing: channel-major permuted scale-out receive layer, contiguous per-channel send slices, one PUT per batch; matched control arm; optional dispatch final-tail merge arm | design in progress |
| C | follow-up | Dispatch fixed-term work chosen from A/B traces (notify exchange, final tail, CSTATE pairing); EP16-ready channel helper | pending |

Rules kept from the previous campaign: one immutable snapshot per experiment, exact
correctness gates (irregular sizes, FP8/BF16, local/remote/hot-rank/dropped routing,
sustained 16K) before any timing, three counterbalanced repeats, raw-file analysis, no
job of the user's own touched, allocation released when no further gate fits.

## Results so far (updated 2026-11-02 05:20 CET, final for this window)

Qualified configuration: `marker-zero` transport + packed dispatch rows (regular notification
interval 16, **first interval 4**, forward chunk 3) + packed combine (batch 16, **first batch 4**) +
final-tail merge, 129 contexts, 64 SMs, EP8 on two GH200 nodes. Each number is the median of three
ordinary repeats of the per-iteration rank maximum (100 timed calls after 20 warm-ups). Bounds use
21.5 GB/s, the rate the NIC sustains for large contiguous PUTs in the matched raw probe.

| V4 Flash, FP8 dispatch / BF16 combine | 10/30 start | 10/31 candidate | 11/02 02:00 candidate | **final (allocation F/H)** | bound | ratio |
|---|---:|---:|---:|---:|---:|---:|
| 4K fresh dispatch | 3.399 ms | 1.075 ms | 1.033 ms | **0.949 ms** | 0.823 | **1.15** |
| 4K combine | 4.387 ms | 3.439 ms | 1.802 ms | **1.814 ms** | 1.573 | 1.15 |
| 16K fresh dispatch | 10.46 ms | 3.498 ms | 3.453 ms | **3.439 ms** | 3.292 | **1.04** |
| 16K combine | — | 13.30 ms | 6.995 ms | **6.946 ms** | 6.291 | 1.10 |

Same gain on every release geometry (H geometry repeats vs C): Qwen3 4K dispatch 1.042 → 0.951 ms
(−8.7 %), MiniMax 0.831 → 0.764 ms (−8.0 %); 16K dispatch −0.3…−0.4 %; combine within ±0.7 %.
Size-sweep fits over 2K–16K (three orders): dispatch T = 0.147 ms + MB / 21.5 GB/s (was 0.196 ms +
MB / 21.8 GB/s), combine T = 0.121 ms + MB / 19.8 GB/s. The incremental bytes of both operations
move at the measured link rate; what is left per call is the 0.11 ms cross-rank entry barrier of
the DeepEP kernels, a 4K-specific NIC drain excess of about 0.18 ms (0.03 ms at 16K) and tails of
0.02–0.1 ms. The final candidate passed the full release matrix in allocation F/H on
`nid006295,nid006298` (V4 Flash irregular/4K/dropped/16K, FP8 and BF16 at 257/4096/16384 for
V4 Flash, Qwen3 and MiniMax, nine geometry repeats, three size sweeps, six SGLang gates), after
the same GPU archive passed the 28-gate first-batch matrix.

Found on the way and recorded for the implementation: packed PUT boundaries that fall on 1 or 2
rows mod 4 make the NIC transfer 1.6–1.9× (odd) or 2.8–3.8× (2 mod 4) slower with identical
GPU-side submission; multiples of 4 rows are safe (first interval 4, 8, 12 and the regular 16).
Root cause (raw single-queue probe, allocation I): PUT source/destination addresses must be
128-byte aligned; 64 bytes off a line costs ×4.3 on the wire (5 GB/s), 32 or 96 bytes off about
×2. Both dispatch rows (4320 and 8288 bytes) are 32·odd, so only multiples of 4 rows are aligned;
padding the row stride to a 128-byte multiple removes the constraint.

## Log

### 2026-11-01 22:05 CET — access verified, allocation A submitted and running

SSH to Clariden works after the certificate refresh (login node `clariden-ln003`, 20:50 UTC).
No job of mine was queued or running; the last campaign allocation (3811125) completed at
10:29 UTC on 10/31 and its final results (new-node repeats, packed traces, 8256-byte raw
ladder) were analysed in the 10_30 file. No leftover executors on the login nodes.

**Allocation A, job 3829353**, normal partition, two nodes, four hours, started
**21:03:49 UTC** on `nid006033,nid006106` (it started immediately). Snapshot
`source-1101-release-v1` = `source-serving-local-v2` (GPU code, transport and DeepEP archive
byte-identical to the qualified `source-zero-packed-v7`) with a new 31-gate self-contained
sequence: 6000–6006 fresh qualification and three ordinary repeats of the packed/I16/129-
context candidate, then 6010–6033 the prepared release matrix (FP8/BF16 correctness at
257/4096/16384 for V4 Flash, Qwen3, MiniMax; three geometry timing repeats per model;
2K–16K size sweep in ascending, descending and permuted order; SGLang scatter/gather and
reduced-expert smoke per model). Packager:
`tools/cxi_gin/experiments/pipeline_1101/package_release_1101.py`; submission via the
existing `pipeline_v1/launch.py`; local evidence under `results/deepep_pipeline_20261101/`.
Remote preflight passed (queue model, resources, SM90 probes, packed-row model).

**Allocation B, snapshot `source-1101-combine-pack-v1`**, packaged from
`source-zero-packed-v7` with two compile-time arms on an unchanged transport:

- `CXI_EP_PACK_COMBINE=1`: combine packing. Each scale-out receive layer is addressed
  channel-major (`packed_combine_slot(t) = base(t % channels) + t / channels`); the combine
  forward warp stages consecutive remote-origin rows of its channel at their channel-local
  position of the send slice and issues one PUT per run of consecutive rows (batch limit
  `CXI_EP_COMBINE_BATCH=16`, flushed non-aggregated at the end); the local bypass writes its
  own layer at the same slot; `combine_reduce_epilogue` reads every layer through the same
  permutation. Relies on: dispatch channel c owns tokens t ≡ c (mod channels) and the
  dispatch forwarder appends metadata in slot order (verified in the pinned source); with the
  two-node multiple-reduction rank layout the epilogue reads layer r for token t only when t
  has an expert on r, so unwritten slots are never read. Static asserts restrict the path to
  that configuration and to 256 channels (`4 × CXI_EP_SMS`). CPU model
  (`test_packed_combine.cc`): bijection, channel-contiguity and batch ownership for
  capacities 257/4096/8192/16384 and 64/128/256 channels: PASS.
- `CXI_EP_MERGE_FINAL_TAIL=1`: the previously prepared dispatch final-tail merge
  (`pipeline_v1/prepare_final_tail.py`), GPU-unqualified until now.

Arms control/combine/merge/both: irregular stress (32/257 tokens, five routings, three
seeds), 4K FP8/BF16 correctness, dropped-token correctness, sustained 16K with lifecycle
plateau check, then three counterbalanced ordinary repeats per arm (28 gates). Launch
through `pipeline_1101/launch_1101.py`, which adds a login-node compilation of the actual
combine, epilogue and dispatch templates for every arm before `sbatch`. Submission in
progress at the time of this entry; it will queue behind A.

### 2026-11-01 22:19 CET — candidate re-qualified on the new node pair; allocation B queued

Allocation A, gates 6000–6006 PASS on `nid006033,nid006106` (irregular stress 30 cases/rank,
4K FP8/BF16 routing matrix, dropped tokens, sustained 16K with lifecycle plateau, three
ordinary repeats). Three-repeat medians of per-iteration rank maxima, V4 Flash FP8/BF16:

| Tokens/rank | Fresh dispatch | Cached dispatch | Combine | Range (fresh / combine) |
|---:|---:|---:|---:|---|
| 4096 | 1.0703 ms | 1.0583 ms | 3.4350 ms | 1.0701–1.0719 / 3.4312–3.4688 |
| 16384 | 3.4911 ms | 3.4814 ms | 13.209 ms | 3.4887–3.4933 / 13.198–13.269 |

Third node pair in a row within 1 % for dispatch (1.060 / 1.066 / 1.070 ms). Combine is
again a few per cent slower than on the first pair (3.30 → 3.38 → 3.44 ms); still 2.5× its
serialization bound. The release matrix (6010–6033) is now running.

Allocation B: the first snapshot (`source-1101-combine-pack-v1`) was rejected by my own
login-node template preflight before any submission: the 257-token templates instantiate
`kNumMaxTokensPerRank = 257` (the receive buffer is sized per call), giving two token slots
per channel, and my guard `CXI_EP_COMBINE_BATCH <= kNumMaxTokensPerChannel` was too strict
(the batch limit is only an upper bound on a run). v2 drops the guard; nothing else changed.
`source-1101-combine-pack-v2`: transport preflight PASS, CPU models PASS, and all 24 real
templates compiled (combine/epilogue at 257/4096/16384 tokens for both arms; fresh/cached
dispatch at the three sizes for both final-tail arms), zero spills everywhere. Packed combine
keeps 216 registers with a 320-byte stack frame (control 208 B); the merged final tail uses
148 registers (control 146). **Job 3829402** submitted 21:16:37 UTC, four hours, PENDING on
priority behind A.

### 2026-11-01 22:32 CET — packed combine passes its first GPU correctness gate

Allocation B started 21:21 UTC on `nid007507,nid007531`, concurrently with A. Control arm
7000–7003 PASS. **7010-combine-irregular-stress PASS** on all eight ranks: 32 and 257
tokens, mixed/uniform/hot-rank/local/remote routing, three seeds, exact combine and cycle
checks with 100 timed iterations each. This is the first GPU evidence that the channel-major
receive permutation and batched PUTs deliver correct combine results. 4K FP8/BF16 routing,
dropped tokens and sustained 16K follow before any timing is read. Allocation A has passed
all six release correctness gates (V4 Flash, Qwen3, MiniMax; FP8 and BF16; 257/4096/16384)
and is in the geometry timing repeats.

### 2026-11-01 22:35 CET — first packed-combine timings (indicative)

B gate **7011-combine-4k-correctness PASS**: 4K tokens, FP8 and BF16 dispatch, five routings,
two seeds, exact combine checks. Its three-iteration medians, mixed routing, same node pair
as the control gate 7001 run minutes earlier:

| Arm | 4K combine (FP8 dispatch run) | 4K combine (BF16 run) | 4K fresh dispatch |
|---|---:|---:|---:|
| control | 3.342 ms | 3.437 ms | 1.117 ms |
| packed combine | **1.803 ms** | **1.812 ms** | 1.070 ms |

Three iterations are not a qualified measurement; the ordinary 100-iteration repeats
(7040–7051) decide. If they hold, combine drops by about 46 % to within 10 % of the
coalesced 8256-byte raw probe (1.654 ms) and to 1.15× the 21.5 GB/s bound.

### 2026-11-01 22:38 CET — packed combine correctness-qualified; 16K sustained timing

B gates 7010–7013 all PASS: the packed-combine arm is correctness-qualified for the declared
matrix (irregular 32/257, 4K FP8/BF16 five routings, dropped tokens, sustained 16K with
three seeds and the 133-CT lifecycle plateau). The sustained gate runs 20 warm-ups and 100
timed calls per seed, so its combine figure is a real measurement on this node pair:

| Arm | 16K combine | 16K fresh dispatch |
|---|---:|---:|
| control (7003) | 13.244 ms | 3.495 ms |
| packed combine (7013) | **6.991 ms** | 3.491 ms |

Bounds at 16K: 5.411 ms (25 GB/s), 6.292 ms (21.5 GB/s); coalesced 8256-byte raw probe
6.253 ms. Packed combine is therefore 1.11× the practical bound and 1.12× the raw probe.
The merge and both arms (7020–7033) qualify next, then the twelve counterbalanced repeats.

### 2026-11-01 22:44 CET — release geometry timings (allocation A, three repeats each)

Packed/I16 candidate, FP8 dispatch and BF16 combine, median of three ordinary repeats of the
per-iteration rank maximum, `nid006033,nid006106`:

| Geometry | 4K fresh dispatch | 4K combine | 16K fresh dispatch | 16K combine |
|---|---:|---:|---:|---:|
| V4 Flash | 1.0708 ms (1.0699–1.0745) | 3.4575 ms | 3.4919 ms | 13.299 ms |
| Qwen3 | 1.0889 ms (1.0751–1.0916) | 3.4420 ms | 3.5203 ms | 13.232 ms |
| MiniMax | 0.8720 ms (0.8715–0.8735) | 2.4163 ms | 2.7048 ms | 9.107 ms |

All three geometries carry the dispatch gain; combine remains the unpacked kernel in this
snapshot and is being replaced in allocation B. Size sweeps 6025–6027 run next, then SGLang.

### 2026-11-01 22:58 CET — 2K–16K size sweep of the packed/I16 candidate (allocation A)

Three sweeps (ascending, descending, permuted order), FP8 dispatch, BF16 combine, 20 warm-ups
and 100 timed calls per size, medians of the per-iteration rank maximum, then median over
the three repeats. Fit T = α + β·(payload MB per rail):

| Operation | α (fixed per call) | β | Incremental throughput | R² |
|---|---:|---:|---:|---:|
| fresh FP8 dispatch, packed rows, I16 | 0.207 ms | 0.0461 ms/MB | **21.7 GB/s** | 0.9990 |
| BF16 combine, unpacked (this snapshot) | 0.207 ms | 0.0969 ms/MB | 10.3 GB/s | 0.9999 |

Compared with the 10/30 sweep of the row-wise interval-3 dispatch (α 0.212 ms, β 0.1447 ms/MB,
6.9 GB/s): the fixed term did not move; the per-byte cost fell 3.1× and now equals the
coalesced raw probe's sustained rate. Dispatch is therefore at the practical link ceiling
for the incremental bytes, and the whole remaining gap is the 0.21 ms per-call term:

| Tokens/rank | Dispatch median | Bound 21.5 GB/s | Ratio | Useful GB/s |
|---:|---:|---:|---:|---:|
| 2048 | 0.605 ms | 0.412 | 1.47 | 14.6 |
| 4096 | 1.070 ms | 0.823 | 1.30 | 16.5 |
| 8192 | 1.843 ms | 1.646 | 1.12 | 19.2 |
| 16384 | 3.491 ms | 3.292 | 1.06 | 20.3 |

Combine ratios in this snapshot are 2.1–2.3× at every size (useful 9.4–10.2 GB/s), which is
the unpacked kernel that allocation B replaces. One sweep repeat showed a single hiccup at
6144 tokens (3.19 ms dispatch, 6.03 ms combine in one of three repeats); the other two
repeats and the medians are unaffected. SGLang gates 6028–6033 are running.

### 2026-11-01 23:05 CET — SGLang release gates: V4 Flash passes, Qwen3 gate hit a storage race, retried

A gates 6028/6029 PASS: SGLang scatter/gather with exact dispatch reference and the
reduced-FFN expert smoke for V4 Flash, both over the packed/I16 transport.
**6030-marker-zero-qwen3-sglang-scatter-gather FAILED after 68 s** (rc 143, controller
paused). Root cause from the rank-4 traceback on `nid006106`: `OSError: [Errno 116] Stale
file handle` while Triton's `CompiledKernel` read the cache metadata of SGLang's
`_fwd_kernel_ep_scatter_2`; rank 6 failed the same way. Two ranks compiled the same kernel
into the shared-filesystem Triton cache concurrently. This is the same class of host-storage
failure the 10/31 campaign fixed for JIT, logs and results, and the SGLang path still used the
default `~/.triton/cache`. No dispatch/combine payload check failed.

Fix without touching GPU code: request `6030b-…-retry` (same spec plus
`TRITON_CACHE_DIR=/dev/shm/triton-cache-3829353`), `6031` rewired to require it, `6032/6033`
given the same cache setting; `RESUME.json` written with the reason. The controller runs its
GPU health check and continues. Side note: the login node's `/tmp` refused a bash here-doc
("No space left on device"); remote scripts are now streamed over stdin.

### 2026-11-01 23:10 CET — allocation B complete: packed combine halves combine time

Job 3829402, `nid007507,nid007531`, all 28 gates PASS (16 correctness, 12 ordinary
repeats). Median of three counterbalanced repeats of the per-iteration rank maximum,
V4 Flash, FP8 dispatch / BF16 combine, all arms on the identical `marker-zero` transport with
packed dispatch rows and interval 16:

| Arm | 4K fresh dispatch | 4K combine | 16K fresh dispatch | 16K combine |
|---|---:|---:|---:|---:|
| control (= 10/31 candidate) | 1.0753 ms | 3.4391 ms | 3.4975 ms | 13.303 ms |
| packed combine | 1.0667 | **1.8018** | 3.4998 | **6.992** |
| final-tail merge | **1.0332** | 3.4291 | **3.4568** | 13.258 |
| both | 1.0383 | 1.8018 | 3.4528 | 6.995 |

Repeat ranges are tight (combine 1.8013–1.8019 ms at 4K; 6.991–7.002 ms at 16K).
Against the 21.5 GB/s practical bound: combine moves from 2.19× to **1.15×** at 4K and from
2.11× to **1.11×** at 16K (useful payload 18.8 and 19.4 GB/s, up from 9.8 and 10.2). The
final-tail merge is a small, consistent dispatch gain (−3.9 % at 4K, −1.2 % at 16K) and the
two changes compose. Compiler evidence: packed combine keeps 216 registers with a 320-byte
stack frame, zero spills, in every gate.

Where this leaves the two operations (both arms on, V4 Flash):

| Operation | 4K | bound 21.5 | ratio | 16K | bound 21.5 | ratio |
|---|---:|---:|---:|---:|---:|---:|
| fresh FP8 dispatch | 1.038 ms | 0.823 | 1.26 | 3.453 ms | 3.292 | 1.05 |
| BF16 combine | 1.802 ms | 1.573 | 1.15 | 6.995 ms | 6.292 | 1.11 |

Next in the same held allocation: a 2K–16K size sweep of the `both` arm (three orders) to
measure combine's fixed term and incremental rate, and combine batch-limit variants (8 and 64
rows) to see whether PUT granularity still matters at 16K.

### 2026-11-01 23:18 CET — A: retry mechanics; B: follow-up gates queued

The first retry request `6030b` was rejected in 3 ms by the controller ("invalid environment
override"): request environments may only contain `CXI_*`, `EP_*` or `NCCL_*` keys, so
`TRITON_CACHE_DIR` cannot be injected per request. A plain retry `6030c` (identical to 6030)
is queued instead, `6031` rewired to it, the extra key removed from 6032/6033, and the
controller resumed a second time. Making the Triton cache node-local therefore needs a harness
change (map an allowed variable in `direct_node.sh` to `TRITON_CACHE_DIR` under
`CXI_LOCAL_JIT=1`); it goes into the next snapshot together with the packed combine.

NIC windows for B (median TX GB/s per port over 600 calls, three repeats): combine 10.9 GB/s
control → 19.8 GB/s packed, bytes per call unchanged (35.9 → 35.5 MB); dispatch 17.7–18.4 GB/s
in all arms. Queued in B's held allocation on the same snapshot: 7060–7062 size sweep of the
`both` arm (2K–16K, three orders) and 7070–7073 combine batch limits 8 and 64 (two repeats
each). B's controller picked them up and is running 7060.

### 2026-11-01 23:20 CET — allocation C submitted; A's SGLang gates recovering

A: `6030c` (plain retry of the Qwen3 SGLang scatter/gather) PASS, `6031` Qwen3 expert smoke
PASS, `6032` MiniMax scatter/gather PASS; `6033` running. The 6030 failure was transient.

**Allocation C, job 3829630**, submitted 22:18 UTC, PENDING on priority behind A and B.
Snapshot `source-1101-release-c-v1` = `source-1101-release-v1` (serving harness) + the two
DeepEP patches of B's qualified `both` arm (archive hash-identical to
`source-1101-combine-pack-v2`) + one harness change: under `CXI_LOCAL_JIT=1`,
`TRITON_CACHE_DIR` is set to the node-local JIT directory for both EP and SGLang runs. Its
31-gate sequence (8000–8033) mirrors A with `CXI_EP_PACK_COMBINE=1`,
`CXI_EP_MERGE_FINAL_TAIL=1`, `CXI_EP_COMBINE_BATCH=16`: fresh qualification and three repeats,
then the full release matrix including SGLang for all three models. Preflight: transport
probes, CPU models and all 24 real templates PASS, zero spills.

### 2026-11-01 23:20 CET — allocation A complete and released

Job 3829353: 33 gate records, 31 PASS. The two non-PASS records are the original Qwen3
SGLang gate (transient Triton-cache stale handle) and the retry request rejected by the
environment whitelist; the plain retry passed. The 10/31 candidate (packed dispatch rows,
interval 16, 129 contexts, `marker-zero` transport) is therefore release-qualified on this node
pair: correctness for three geometries, FP8 and BF16, 257/4096/16384 tokens; three geometry
timing repeats per model; three size sweeps; SGLang scatter/gather with exact dispatch
reference and reduced-expert smoke (`actual_sglang_expert_kernels=true`) for all three
models. SGLang-side cold-call numbers in the rank records are debug-scope diagnostics and are
not used as performance data. `STOP` written to the controller at 22:19 UTC; nodes released to
let C start. B continues its follow-up gates.

### 2026-11-01 23:25 CET — size sweep of the packed-combine + final-tail arm (allocation B)

Gates 7060–7062 (three orders) PASS. Fit T = α + β·MB per rail, medians of three repeats:

| Operation (both arms on) | α | β | Incremental throughput | R² |
|---|---:|---:|---:|---:|
| fresh FP8 dispatch | 0.192 ms | 0.0459 ms/MB | 21.8 GB/s | 0.99976 |
| BF16 combine, packed | **0.091 ms** | 0.0510 ms/MB | **19.6 GB/s** | 0.99998 |

| Tokens/rank | Dispatch | ratio to 21.5 GB/s bound | Combine | ratio |
|---:|---:|---:|---:|---:|
| 2048 | 0.600 ms | 1.46 | 0.971 ms | 1.23 |
| 4096 | 1.032 ms | 1.25 | 1.804 ms | 1.15 |
| 8192 | 1.796 ms | 1.09 | 3.535 ms | 1.12 |
| 16384 | 3.454 ms | 1.05 | 6.997 ms | 1.11 |

Combine is now within 11–15 % of the practical bound at 4K–16K with a fixed term of only
0.09 ms; its incremental rate (19.6 GB/s) sits about 10 % under dispatch's 21.8 GB/s, which
is the next thing to understand (candidates: PUT granularity, 16 rows = 132 KB per PUT at
interval 16, versus one PUT per channel in the raw probe; the reduction work between PUTs;
the final flush). Gates 7070–7073 compare batch limits 8 and 64 next. Dispatch's remaining
gap is the 0.19 ms per-call term (down from 0.21 ms with the final-tail merge).

### 2026-11-01 23:32 CET — combine batch limit is not the limiter; allocation B released

Gates 7070–7073 PASS (two repeats each; batch 16 from the three earlier repeats):

| Combine batch limit (rows per PUT) | 4K combine | 16K combine | 16K PUTs per channel |
|---|---:|---:|---:|
| 8 | 1.821 ms | **6.843 ms** | 8 |
| 16 (candidate) | 1.802 ms | 6.995 ms | 4 |
| 64 | 1.789 ms | 6.918 ms | 1 |

At 4K every channel holds 16 rows, so 16 and 64 are the same single PUT and differ by noise;
8 costs 1 %. At 16K the smallest batch is 2 % faster than the largest: issuing PUTs earlier
overlaps transfer with the reduction better than fewer, larger requests. PUT granularity is
therefore no longer where combine loses its remaining ~10 % of incremental rate; the next
candidates are the reduction/TMA work between PUTs and the final flush, which need the trace
build adapted to the packed path. Dispatch is unaffected by the combine batch (1.03 / 3.45 ms).
Batch 16 stays the candidate setting. B had nothing further to run; `STOP` written at 22:29 UTC
(1.8 h of its allocation unused, returned to the queue so C can start).

### 2026-11-02 00:45 CET — allocation C: candidate reproduced on a fourth node pair

Job 3829630 started 23:30 UTC on `nid007442,nid007458`. Gates 8000–8006 PASS. Three-repeat
medians of the packed-combine + final-tail candidate: fresh dispatch 1.0319 / 3.4522 ms,
combine 1.8006 / 6.9898 ms at 4K / 16K (B: 1.0383 / 3.4528 and 1.8018 / 6.9950). The release
matrix 8010–8033 runs next, followed by the queued forward-chunk and interval variants
8100–8142.

### 2026-11-02 01:10 CET — release geometry timings of the final candidate (allocation C)

Gates 8010–8015 PASS (release correctness: three geometries, FP8 and BF16, 257/4096/16384
tokens, packed combine and merged final tail). Geometry repeats 8016–8024, medians of three,
versus allocation A's 10/31 candidate on another node pair:

| Geometry | 4K dispatch A → C | 4K combine A → C | 16K dispatch A → C | 16K combine A → C |
|---|---|---|---|---|
| V4 Flash | 1.071 → **1.032** ms (−3.6 %) | 3.458 → **1.801** ms (−47.9 %) | 3.492 → **3.454** ms (−1.1 %) | 13.30 → **6.992** ms (−47.4 %) |
| Qwen3 | 1.089 → **1.042** ms (−4.3 %) | 3.442 → **1.802** ms (−47.6 %) | 3.520 → **3.473** ms (−1.3 %) | 13.23 → **6.997** ms (−47.1 %) |
| MiniMax | 0.872 → **0.831** ms (−4.8 %) | 2.416 → **1.388** ms (−42.5 %) | 2.705 → **2.659** ms (−1.7 %) | 9.107 → **5.322** ms (−41.6 %) |

Repeat ranges are within 0.5 % everywhere. MiniMax (hidden 3072, top-k 8) gains slightly less
on combine because its row is smaller (6208 bytes) and the per-PUT fixed cost weighs more.
Size sweeps 8025–8027 and the six SGLang gates follow, then the forward-chunk and interval
variants.

### 2026-11-02 01:23 CET — C size sweeps reproduce the fits

Gates 8025–8027 PASS. Fit on the fourth node pair: dispatch T = 0.197 ms + MB / 21.85 GB/s
(R² 0.9997); combine T = 0.094 ms + MB / 19.64 GB/s (R² 0.99998). Allocation B had 0.192 ms /
21.80 GB/s and 0.091 ms / 19.61 GB/s. Both intercepts and both slopes are therefore stable
properties of the candidate, not of a node pair. SGLang gates 8028–8033 run next.

### 2026-11-02 01:27 CET — C: SGLang gate failed on my Triton-cache change; corrected snapshot D

`8028-marker-zero-v4flash-sglang-scatter-gather` FAILED on all eight ranks within 70 s:
`ImportError: .../deepep-jit-3829630-n0-…/triton/…/cuda_utils.cpython-312-aarch64-linux-gnu.so:
failed to map segment from shared object`. Triton `dlopen`s compiled extension modules from its
cache, and `/dev/shm` is mounted `noexec` inside the SGLang container, so the node-local Triton
cache I introduced in snapshot C cannot work there. DeepEP's own JIT is unaffected because it
loads cubins through the driver, which is why every EP gate passed. Not a transport or kernel
defect; the packed combine is not implicated.

Actions: gates 8029–8033 retired from C (`retired-requests-noexec-triton-cache/`), controller
resumed to run the EP-only variants 8100–8142. New snapshot `source-1101-sglang-c2-v1`
(GPU code and archive identical to C): Triton cache goes to the container-local `/tmp` only
when `/proc/mounts` shows that mount without `noexec`, otherwise Triton's default location is
kept; the chosen path is recorded per gate. Sequence 8200–8215: fresh irregular and 4K
correctness, then the six SGLang gates. Submitted as allocation D (queues behind C).

### 2026-11-02 01:45 CET — allocation D: SGLang release gates pass with packed combine; released

Job 3830035 (`nid006219,nid007319`), all eight gates PASS: fresh irregular stress and 4K
correctness of the candidate, then SGLang scatter/gather with exact dispatch reference and
reduced-expert smoke for V4 Flash, Qwen3 and MiniMax (`actual_sglang_scatter_gather=true`,
`actual_sglang_expert_kernels=true` on the smoke gates). Triton's cache was placed in the
container-local `/tmp` on both nodes (`triton-cache-path.txt` records
`/tmp/deepep-triton-3830035-n{0,1}`); no Triton cache errors, no retries needed. Together with
C's correctness, geometry and size-sweep gates, the packed-combine + final-tail candidate has
now passed the same release matrix as the 10/31 candidate did in A. `STOP` written to D at
00:44 UTC.

### 2026-11-02 01:50 CET — dispatch cadence variants: no further gain; allocation C released

C gates 8100–8142 PASS (forward chunk 16 and notification interval 32 each pass irregular
stress and 4K correctness, then three counterbalanced repeats against the candidate):

| Arm | 4K dispatch | 16K dispatch | 4K combine | 16K combine |
|---|---:|---:|---:|---:|
| candidate (interval 16, forward chunk 3) | 1.0334 ms | 3.4524 ms | 1.8018 ms | 6.990 ms |
| forward chunk 16 | 1.0304 (−0.3 %) | 3.4665 (+0.4 %) | 1.8020 | 6.954 |
| interval 32, chunk 3 | 1.0345 (+0.1 %) | 3.5319 (+2.3 %) | 1.8003 | 6.989 |

Neither the forwarder's chunk size nor a sparser notification cadence moves dispatch; interval
32 is slightly worse at 16K (fewer, later notifications delay forwarding). The candidate's
settings stay. The remaining dispatch per-call term (0.19 ms) is therefore not in the
notification cadence or the forwarder loop; attributing it needs the device trace adapted to
the packed path, which is the next engineering step rather than another knob sweep. C had
nothing further queued; `STOP` written at 00:44 UTC. All four allocations of this campaign are
now released; nothing of mine is queued or running.

Note on timestamps: the log headers above were corrected at this point from the per-gate
`end_utc` records; earlier drafts of this file carried headers 1–3 h late.

### 2026-11-02 02:10 CET — allocation E prepared: device traces of the final candidate

Snapshot `source-1101-trace-e-v1` (parent `source-1101-combine-pack-v2`, ordinary archive
byte-identical). The private trace archive is the 10/31 packed-dispatch trace generator
(events 113 packed payload submission, 114 tail notification, 115 receiver tail observation,
209–214 transport publication/fence/CSTATE/atomic/cursor) applied to the packed-combine
archive, plus event 116 around each packed combine batch PUT and a balanced close of the
per-token reduce scope (135) on the packed path. The standalone controller's trace check now
uses the configuration-aware validator (native fencing means no GPU flush event on dispatch).
Gates: 8400 candidate at 4K, 8401 control arm at 4K, 8402 candidate at 16K, three captures per
operation and rank with tracing-disabled timings before and after. Launch includes a login-node
compile of the traced combine, epilogue and dispatch templates with `EP_TRACE_PTR` set.
Purpose: attribute dispatch's 0.19 ms per-call term and combine's 10 % incremental shortfall.

### 2026-11-02 02:55 CET — allocation E: where the remaining time goes (device traces)

Job 3830077 (`nid007054,nid007126`), gates 8400 (candidate 4K), 8401 (control arm 4K) and
8402 (candidate 16K) PASS with the configuration-aware validator; three captures per operation
and rank, zero trace overflow. Recording adds 23 % to dispatch and 4–13 % to combine, so the
timelines below are structure, not latency; the tracing-disabled instrumented timings
(1.110 / 1.845 ms at 4K, 3.53 / 7.08 ms at 16K) bracket the ordinary ones.

Timelines, medians over 24 rank/capture pairs, milliseconds from the first event of the call:

| Dispatch, packed rows I16 + merged tail | 4K | 16K |
|---|---:|---:|
| count-exchange ("notify") phase; sender and forwarder warps start | 0.116 | 0.116 |
| first packed payload PUT issued (first 16-row batch staged) | 0.161 | 0.163 |
| last payload PUT issued | 0.283 | 0.683 |
| last remote arrival observed by the forwarder | 1.207 | 3.481 |
| forwarder done (last NVLink forward and finish) | 1.212 | 3.486 |
| wire time of the payload at 21.5 GB/s | 0.823 | 3.292 |

| Combine, packed batches of 16 | 4K | 16K |
|---|---:|---:|
| start barrier done; forwarder and NVLink-sender warps start | 0.108 | 0.115 |
| first local contributions available to the forwarder | 0.225 | 0.115 |
| first remote batch PUT issued (16 reductions staged) | 0.352 | 0.426 |
| last batch PUT issued | 1.617 | 6.757 |
| own CT-writeback wait ends (all PUTs acknowledged) | 1.888 | 6.881 |
| forwarder done (remote tail wait, finish) | 1.976 | 7.166 |
| wire time of the payload at 21.5 GB/s | 1.573 | 6.292 |

Reading. In both operations the GPU now finishes issuing long before the data has crossed the
wire: dispatch senders are done at 0.28 ms (4K) and 0.72 ms (16K); combine's last PUT at 16K
goes out 6.76 ms in, and the wire needs 6.29 ms from the first PUT at 0.43 ms, so the NIC is
busy from first byte to last. The remaining non-wire time is start-up and tail:

- Dispatch: 0.12 ms count exchange before any payload warp starts, 0.045 ms to stage the first
  16-row batch, then ~0.05 ms tail (last PUT drains, last NVLink forward, finish). Together
  the 0.19 ms per-call term of the size-sweep fit.
- Combine: 0.11 ms start barrier, ~0.12 ms until the first local contributions arrive over
  NVLink, 0.13 ms to stage the first 16 reductions, then ~0.1 ms tail (own writeback, peer's
  finish signal). The incremental rate (19.6 GB/s) is below dispatch's because the first remote
  byte leaves 0.35–0.43 ms in; the NIC runs at the link rate after that.

Control arm (unpacked combine, same trace build): the forwarder spends 2.54 ms of its 3.15 ms
lifetime waiting for the context lock while its partner is in a completion wait, issuing one
PUT per row from the very start (first remote PUT at 0.002 ms, last at 3.22 ms). Packing turned
a submission-bound combine into a wire-bound one.

Consequence for the target: for the incremental bytes both operations run at the measured
link rate; what remains is 0.19 ms (dispatch) and ~0.3 ms (combine) of start-up and tail per
call, which at 4K is 19 % and 15 % of the call and at 16K 5 % and 11 %. Removing more needs
pipelining changes inside the DeepEP kernels (payload before the count exchange completes,
smaller first batches, earlier remote combine PUTs), each worth at most about 0.1 ms. The
knob sweeps already showed the cadence knobs cannot buy this. `STOP` written to E at 01:55 UTC.

Addendum to the trace reading: the 0.11 ms at the start of both kernels is DeepEP's
`comm::gpu_barrier` at kernel entry (grid-wide plus cross-rank, tags `kHybridDispatchTag0` /
`kHybridCombineTag0`), which also absorbs the launch skew between the eight ranks. The sender
and forwarder roles of dispatch both begin exactly when it completes (0.116 ms); only the
notify warps run before it. Shrinking it means changing how the kernels are launched and
synchronised (for example programmatic dependent launch), not a transport change.

### 2026-11-02 02:10 CET — allocation F prepared: smaller first batches

The traces show the first remote byte leaves 0.045 ms (dispatch) and 0.13 ms (combine) after the
roles start because the first batch must be fully staged first (16 rows / 16 reductions).
Snapshot `source-1101-first-batch-v1` (parent `source-1101-combine-pack-v2`) adds two
compile-time knobs that default to the current behaviour: `CXI_EP_FIRST_INTERVAL` (dispatch's
first progress notification after that many rows, then the regular interval) and
`CXI_EP_COMBINE_FIRST_BATCH` (combine's first remote PUT after that many reductions, then the
regular batch). Arms: candidate (16/16), dispatch first 4, combine first 4, both 4; each arm
gets the full correctness matrix (irregular, 4K FP8/BF16, dropped, sustained 16K) before three
counterbalanced repeats (28 gates). Expected effect if the hypothesis holds: up to ~0.03 ms on
dispatch and ~0.1 ms on combine at 4K; the earlier batch-8 result (1 % worse at 4K) sets the
scale of the extra-PUT cost it must beat.

### 2026-11-02 03:13 CET — allocation F: a 4-row first notification interval removes most of the dispatch per-call term at 4K

Job 3830101, `nid006295,nid006298`, all 28 gates PASS: for each of the four arms the irregular
stress (32/257 tokens, five routings, three seeds), the 4K exact-correctness matrix (FP8 and BF16,
five routings, two seeds), dropped tokens and sustained 16K, then three counterbalanced repeats.
Median of the three repeats, V4 Flash, FP8 dispatch / BF16 combine, mixed routing, 129 contexts,
`marker-zero` transport, packed rows and packed combine, final-tail merge (`summarize_arms.py`):

| Arm | 4K fresh dispatch | 4K cached dispatch | 4K combine | 16K fresh dispatch | 16K combine |
|---|---:|---:|---:|---:|---:|
| candidate (first interval 16 = regular, first batch 16) | 1.0345 ms | 1.0202 ms | 1.8029 ms | 3.4490 ms | 6.9857 ms |
| dispatch first interval 4 | **0.9461 (−8.5 %)** | 0.9411 (−7.8 %) | 1.7993 (−0.2 %) | 3.4418 (−0.2 %) | 6.9891 (+0.0 %) |
| combine first batch 4 | 1.0361 (+0.2 %) | 1.0208 (+0.1 %) | 1.8113 (+0.5 %) | 3.4521 (+0.1 %) | **6.9451 (−0.6 %)** |
| both 4 | **0.9481 (−8.3 %)** | 0.9412 (−7.7 %) | 1.8079 (+0.3 %) | 3.4420 (−0.2 %) | **6.9491 (−0.5 %)** |

Spread across the three repeats ≤ 0.6 % in every cell. The correctness gates (3 iterations, all
routings, both formats) show the same pattern: the two first-interval arms are 7–20 % faster on
4K dispatch for uniform, hot-rank, remote and mixed routing in FP8 and BF16, the combine-only
arm is unchanged, and local routing (no wire) does not move.

Reading:

- Dispatch. The first interval saves 88 µs at 4K and 7 µs at 16K. At 4K each channel carries at
  most 16 rows to its single remote peer (4096 tokens over 256 channels), so with the regular
  interval 16 a channel's whole payload left as one PUT only after all its rows were staged, and
  the remote forwarder received exactly one notification; nothing overlapped the wire. The knob
  splits this into an early 4-row PUT and the remainder, so staging and forwarding run under the
  transfer. At 16K (64 rows per channel, four PUTs) only the first PUT moves earlier. The saving
  is larger than the 45 µs the trace attributed to staging the first batch, so part of the
  forwarder's work on the final batch was exposed as well; the trace gates queued below attribute
  it on the same node pair.
- Against the bounds: 4K fresh dispatch 0.946 ms versus 0.823 ms at the practical 21.5 GB/s
  (ratio 1.15, was 1.26) and 0.708 ms at the nominal 25 GB/s (1.34). What remains per call is
  about 0.12 ms, which is the 0.11 ms entry barrier plus the tail.
- Combine. A first batch of 4 does nothing at 4K (+0.3–0.5 %, within the spread: the first remote
  PUT waits for the NVLink contributions, not for the batch) and saves a consistent 40 µs at 16K.
  Both knobs at 4 is therefore the new candidate (arm "both 4"); it costs nothing anywhere.

Follow-up pushed into F's idle allocation at 02:05 UTC (requests 8570–8605, same immutable
snapshot, environment-only variation like the F arms, generated by
`tools/cxi_gin/experiments/pipeline_1101/followup_first_interval_sweep.py`): first interval 1, 2
and 8 with the regular interval 16, and regular intervals 8 and 4 with first interval 4, all with
combine first batch 4. Each new arm passes irregular stress and the 4K correctness matrix before
three counterbalanced repeats of all six arms (reference = both 4), as the C cadence variants did.
GPT's 10/30 plan compiled packed-row templates for intervals 3/8/16 but ran only 16 on GPUs, so
the regular-interval arms also answer whether a denser cadence (more, smaller PUTs) pays at 16K.

### 2026-11-02 03:57 CET — cadence sweep in F: first interval 4 is the sweet spot; PUT boundaries off multiples of 4 rows are pathological

Requests 8570–8605 (same allocation and node pair, `followup_first_interval_sweep.py`), all PASS:
ten correctness gates (irregular stress and the 4K FP8/BF16 matrix for each new arm) and 18
counterbalanced repeats. Median of three repeats, V4 Flash FP8 dispatch / BF16 combine, mixed
routing; the reference is F's "both 4" arm (first interval 4, regular interval 16, combine first
batch 4), and every arm keeps combine first batch 4:

| Arm (dispatch cadence) | 4K fresh dispatch | 16K fresh dispatch | 4K combine | 16K combine |
|---|---:|---:|---:|---:|
| first 4, regular 16 (reference) | 0.9485 ms | 3.4441 ms | 1.8137 ms | 6.9463 ms |
| first 1, regular 16 | 1.7932 (+89 %) | 6.2338 (+81 %) | 1.8114 | 6.9471 |
| first 2, regular 16 | 3.2286 (+240 %) | 13.5934 (+295 %) | 1.8119 | 6.9470 |
| first 8, regular 16 | 0.9612 (+1.3 %) | 3.4506 (+0.2 %) | 1.8101 | 6.9424 |
| first 4, regular 8 | 0.9798 (+3.3 %) | **3.3966 (−1.4 %)** | 1.8094 | 6.9426 |
| first 4, regular 4 | 1.0166 (+7.2 %) | 3.7405 (+8.6 %) | 1.8132 | 6.9616 |

Spread across repeats ≤ 1.3 % in every cell. Reading:

- First interval 1 and 2 are not slightly worse but 1.9× and 3.4× slower, at 4K and 16K alike,
  with exact correctness intact. A slowdown proportional to the payload is a steady-state effect,
  not a first-PUT effect. The only steady-state difference between these arms and the fast ones
  is where the 16-row PUTs start: the packed staging buffer has no ring (`packed_source_base +
  tail`), source and destination of each PUT are `base + tail × row bytes`, so the first interval
  fixes the phase of every later PUT boundary. First interval 4, 8, 16 and regular 8, 4 keep every
  boundary on a multiple of 4 rows, i.e. 128-byte-aligned addresses for the 4320-byte FP8 row
  (and for the 8288-byte BF16 dispatch row: 8192 hidden + 96 metadata bytes; 8256 is the combine
  row); first interval 1 and 2 put every boundary at 1 or 2 rows mod 4, i.e. 96 or 64 bytes past a
  128-byte line in both formats. The correctness gates show the same
  ×1.7–1.9 and ×3.4–3.8 pattern in BF16 and for every routing. Working hypothesis (confirmed by the
  raw probe of allocation I, 05:30 CET below): the NIC's path into GPU memory degrades sharply for
  PUT addresses that are not 128-byte aligned; trace gate 8702 (first interval 2) checks that the
  GPU-side submission is unchanged and the wire is what slows down. Rule for the implementation: packed PUT
  boundaries must stay on multiples of 4 rows, or better, pad the row stride to a 128/256-byte
  multiple so that any boundary is aligned. The current candidate is safe only because 4 and 16
  are multiples of 4; the knobs must be validated together.
- First interval 8 is within 1.3 % of 4 at both sizes; 4 stays.
- Regular interval 8 is 1.4 % faster at 16K (the exposed final batch halves) but 3.3 % slower at
  4K (twice the PUT submissions for the same bytes); regular 4 is 7–9 % slower everywhere.
  Interval 16 stays; a size-dependent interval (8 for the 16K template) would be worth at most
  1.4 % there.
- Combine does not move with any dispatch knob (±0.2 %), as expected.

Context from the E traces for the dispatch tail (`trace_timeline.py`, 24 captures per gate): in
the 4K candidate all 256 payload PUTs (one 16-row, 69 KB PUT per channel) are submitted between
0.161 and 0.283 ms and the forwarder exits at 0.350 ms, but the receiver observes the last tail at
1.208 ms, 0.23 ms later than the 21.5 GB/s wire time from the first PUT; at 16K (four PUTs per
channel) the excess is 0.03 ms. The NIC drains two large PUTs per queue (129 queues) worse than
eight; this is the part of the 4K per-call term that the smaller first batch recovers (−88 µs), and
the trace gates 8700/8701 measure it directly on this node pair.

### 2026-11-02 04:10 CET — trace gates in F: where the first-interval gain comes from, and the mod-4 pathology is on the wire

Snapshot `source-1101-trace-g-v1` (parent `source-1101-first-batch-v1`, E's trace generator applied
to the knob-bearing archive; `package_trace_g_1101.py`) installed into the campaign sources and its
gates pushed into F as kind `ep` (the F controller predates the configuration-aware trace
qualification); the traces were validated offline (24 dispatch + 24 combine captures per gate, all
`correctness=PASS`, overflow 0, every required event kind present). Same node pair as every F
measurement. Median over the 24 dispatch captures, times from the kernel's first traced instruction
(`trace_timeline.py`):

| 4K FP8 dispatch (trace build) | candidate (8701) | first interval 4 (8700) | first interval 2 (8702) |
|---|---:|---:|---:|
| forwarder/receiver roles start (after `gpu_barrier`) | 0.121 ms | 0.116 | 0.117 |
| first packed PUT submitted | 0.164 | **0.131** | 0.126 |
| last packed PUT submitted / forwarder exit | 0.297 / 0.362 | 0.385 / 0.424 | 0.390 / 0.435 |
| PUTs per channel (rows) | 1 (16) | 2 (4 + 12) | 2 (2 + 14) |
| receiver observes the last tail | 1.223 | **1.131** | **3.006** |
| kernel end / CUDA event | 1.285 / 1.372 | 1.150 / 1.245 | 3.215 / 3.315 |

Reading:

- The −127 µs of the first-interval-4 arm (trace build; −88 µs in production) is three parts: the
  first byte leaves 33 µs earlier (the 4-row batch is staged in 0.015 ms instead of 0.045 ms); the
  drain from the first PUT to the last tail shortens from 1.059 to 1.000 ms, i.e. the NIC drains
  512 PUTs (four per queue) better than 256 (two per queue) even though the forwarder now needs
  0.09 ms longer to submit them; and the receiver's work after the last tail falls from 62 to
  19 µs because only 12 rows per channel remain. The wire time of the payload at 21.5 GB/s is
  0.823 ms, so the drain is still 0.18 ms longer than the link allows; at 16K the same excess is
  0.03 ms (E), which is why the fixed term is a 4K problem.
- First interval 2 is identical to first interval 4 on the GPU side: same PUT count, same submission
  window (0.126–0.390 ms), same lock/capacity waits, forwarder gone at 0.435 ms. The receiver then
  waits until 3.006 ms for the last tail. The payload is the same 17.7 MB; only the PUT boundaries
  differ (2 + 14 rows instead of 4 + 12). The NIC therefore moves these PUTs at a third of the
  rate. The BF16 dispatch row is 8288 bytes (8192 hidden + 96 metadata), not the 8256-byte combine
  row, so in both formats a boundary at 2 rows mod 4 lies 64 bytes past a 128-byte line and odd
  boundaries 32 or 96 bytes past one; the raw probe of allocation I (05:30 CET) confirms 128-byte
  alignment of the PUT addresses as the cause. Rule: packed PUT boundaries at multiples of 4 rows,
  or a row stride padded to a 128-byte multiple so every boundary is aligned.
- Combine: both arms end at 1.975 ms (kernel) with the first remote PUT at the same time; the
  first batch 4 adds 256 PUTs (770 vs 514 `gin.put`) and changes nothing, as the repeats said. The
  combine submitters spend 115–143 ms (summed over warps) in CT-writeback waits: wire-bound, as
  found in E.

Receiver-side check (same traces, receiver warps = role 104): the union of their wait-for-tail
scopes (event 105) is 0.93 of a 1.03 ms lifetime in the candidate, 0.79 of 0.90 ms with first
interval 4, and 2.42 of 2.52 ms with first interval 2. The receivers are idle while the NIC
delivers; their processing time (lifetime minus waiting) is 0.10 ms in all three arms. The
pathology is therefore in the transfer, not in the kernels on either side. Four more phase arms
(first interval 3, 5, 6, 12 → boundaries at 3, 1, 2, 0 rows mod 4 with different first-PUT sizes)
are queued in F as correctness gates (8610–8617) to pin the rule to the boundary phase.

Release re-qualification of the final candidate queued in F at 03:08 UTC: snapshot
`source-1101-release-h-v1` (parent `source-1101-sglang-c2-v1`, i.e. the serving harness with the
exec-capable Triton cache, plus `prepare_first_batch`; DeepEP archive asserted identical to the
F-qualified one, `package_release_h_1101.py`), C's 31-gate release matrix renumbered 8800–8833
with `CXI_EP_FIRST_INTERVAL=4` and `CXI_EP_COMBINE_FIRST_BATCH=4` in every gate: V4 Flash
irregular/4K/dropped/16K + 3 repeats, FP8/BF16 correctness at 257/4096/16384 for V4 Flash, Qwen3
and MiniMax, nine geometry repeats, three size sweeps, six SGLang gates. About 70 min; F's
allocation ends 05:28 UTC.

### 2026-11-02 05:15 CET — release matrix of the final candidate PASS (allocation F/H); phase table; allocation released

Requests 8800–8833 (snapshot `source-1101-release-h-v1`, pushed into F): 31 gates, all PASS,
including the six SGLang gates (V4 Flash, Qwen3, MiniMax scatter/gather and expert smoke) with the
exec-capable node-local Triton cache. Geometry repeats (median of three) against allocation C's
previous candidate on its own node pair:

| Model | 4K fresh dispatch | 4K combine | 16K fresh dispatch | 16K combine |
|---|---:|---:|---:|---:|
| V4 Flash | 0.9494 ms (−8.0 %) | 1.8136 (+0.7 %) | 3.4391 (−0.4 %) | 6.9459 (−0.7 %) |
| Qwen3 | 0.9512 (−8.7 %) | 1.8098 (+0.4 %) | 3.4584 (−0.4 %) | 6.9457 (−0.7 %) |
| MiniMax | 0.7639 (−8.0 %) | 1.3981 (+0.7 %) | 2.6509 (−0.3 %) | 5.2944 (−0.5 %) |

Size sweeps 8825–8827 (`fit_size_sweep.py`, median of three orders):

| Operation | α | β | incremental | R² | 2K ratio | 4K | 8K | 16K |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| fresh FP8 dispatch | 0.147 ms | 0.0466 ms/MB | 21.5 GB/s | 0.9998 | 1.39 | 1.15 | 1.09 | 1.04 |
| cached FP8 dispatch | 0.144 ms | 0.0465 ms/MB | 21.5 GB/s | 0.9998 | 1.39 | 1.15 | 1.08 | 1.04 |
| BF16 combine | 0.121 ms | 0.0506 ms/MB | 19.8 GB/s | 0.9999 | 1.26 | 1.15 | 1.12 | 1.10 |

Phase arms 8610–8617 (first interval 3, 5, 6, 12; irregular stress and 4K matrix, all PASS)
complete the picture. 4K fresh dispatch, median over the four wire routings of the 4K
correctness gates (3 iterations each), relative to first interval 4:

| First interval | Boundary phase (rows mod 4) | FP8 | BF16 |
|---:|---:|---:|---:|
| 1 | 1 | 1.819 ms (×1.90) | 2.957 ms (×1.70) |
| 2 | 2 | 3.302 (×3.45) | 6.500 (×3.75) |
| 3 | 3 | 1.687 (×1.76) | 2.804 (×1.62) |
| **4** | 0 | **0.958 (×1.00)** | **1.735 (×1.00)** |
| 5 | 1 | 1.621 (×1.69) | 2.700 (×1.56) |
| 6 | 2 | 2.648 (×2.76) | 5.081 (×2.93) |
| 8 | 0 | 0.984 (×1.03) | 1.744 (×1.01) |
| 12 | 0 | 1.006 (×1.05) | 1.798 (×1.04) |
| 16 (= one PUT per channel) | 0 | 1.117 (×1.17) | 2.118 (×1.22) |

The slowdown depends only on the phase class of the PUT boundaries, not on the size of the first
PUT (5 behaves like 1, 6 like 2, 3 like 1), and it is the same in both formats because both dispatch
rows are 32·odd bytes (FP8 4320 = 32·135, BF16 8288 = 32·259): a boundary at 2 rows mod 4 lies 64
bytes past a 128-byte line, odd boundaries 32 or 96 bytes past one, multiples of 4 rows are
128-byte aligned. The receiver-side traces showed the GPUs waiting for delivery during the slow
transfers, and the raw probe of allocation I (below) measures the NIC at 5 GB/s for 64-byte-offset
PUTs and at full rate when 128-byte aligned. Rule for the packed layout: PUT boundaries at
multiples of 4 rows, or a row stride padded to a 128-byte multiple so the rule disappears. `STOP` written to F at
04:15 UTC after all 98 gates (28 first-batch, 28 cadence sweep, 3 traces, 8 phase arms, 31 release)
passed; no allocation of mine is left on the system.

### 2026-11-02 05:25 CET — allocation I submitted: raw PUT offset/length probe for the mod-4 pathology

Snapshot `source-1101-offset-probe-v1` (parent `source-1101-first-batch-v1`; GPU archive unused),
job 3830643 (45 min), `package_offset_probe_1101.py`. `runner/offset_probe.cu` derives from GPT's
burst probe and uses the same private device primitives the GIN backend uses (`cxi_gin::put_locked`
with aggregation, `flush`, `add_locked` signals), one thread and one channel per GPU, each GPU
talking to its rail peer on the other node. Per case both peers issue 256 PUTs of `len` rows, PUT i
covering rows [off + 16 i, off + 16 i + len) of a 48 MB window with identical source and
destination offsets (the packed-dispatch pattern), flush to CT completion and record the
globaltimer span; a signal handshake aligns every case's start and end so the two directions
overlap identically; three repeats per case. Cases for both row sizes (4320 B FP8, 8256 B BF16):
boundary phase off ∈ {0,1,2,3,4,5,6,8} rows with 16-row PUTs; length ∈ {15,14,13,12} rows at
phase 0; and DeepEP's final-PUT shapes (phase k, length 16−k, k = 1..4). The preflight compiled it
for all eight transport flag combinations. If the single-queue raw rate reproduces the ×1.7 (odd
phase) / ×3.5 (phase 2) pattern the cause is in the NIC/host write path and independent of the
kernels and of queue count; if it does not, the pathology needs the 129-queue interleaving.

### 2026-11-02 05:30 CET — allocation I: the raw probe pins the cause to 128-byte PUT alignment; allocation released

Job 3830643, `nid006629,nid006854`, gate 9000: the probe kernel completed all 96 case-repeats on
all eight ranks (errors 0, diagnostic 0); the gate is marked FAIL only by my own host check, which
demanded posted == completed while the final done-signal (one `add_locked`) had not been flushed
(24864 vs 24863). The timing data is complete; gate 9001 was not needed and `STOP` was written at
04:28 UTC. Median over 8 ranks × 3 repeats of 256 PUTs per case, one thread and one queue per GPU,
both directions of each rail pair active:

| Row bytes | PUT rows | boundary offset (rows) | address mod 128 | GB/s | vs aligned |
|---:|---:|---:|---:|---:|---:|
| 8256 | 16 | 0, 2, 4, 6, 8 | 0 | 21.4–21.9 | 1.00 |
| 8256 | 16 | 1, 3, 5 | 64 | 4.9–5.1 | **×4.3 slower** |
| 8256 | 15 / 13 | 1 / 3 | 64 | 4.95 | ×4.4 |
| 8256 | 14 / 12 | 2 / 4 | 0 | 20.1 / 17.2 | 1.08 / 1.26 (fewer bytes per PUT) |
| 4320 | 16 | 0, 4, 8 | 0 | 12.0–12.1 | 1.00 (single-queue issue-bound at 69 KB) |
| 4320 | 16 | 2, 6 | 64 | 5.05–5.13 | **×2.4 slower** (same 5 GB/s floor) |
| 4320 | 16 | 1, 5 / 3 | 96 / 32 | 10.8–11.0 | ×1.1 |
| 4320 | 14 | 2 | 64 | 5.03 | ×2.4 |
| 4320 | 15 / 13 | 1 / 3 | 96 / 32 | 10.4 / 9.4 | ×1.16 / ×1.28 |

Reading:

- The NIC rate depends on the PUT address modulo 128 bytes and on nothing else that was varied:
  64 bytes off a 128-byte line gives a hard floor of 5 GB/s for every row size and length; 32 or
  96 bytes off gives about 11 GB/s (the FP8 aligned cases are issue-bound at 12 GB/s here, one
  thread issuing 69 KB PUTs; with the 132 KB BF16 PUTs the same thread reaches 21.6 GB/s, the
  link rate); 128-byte aligned addresses run at the link rate.
- This explains every DeepEP measurement once the dispatch rows are taken as they are: FP8 4320 =
  32·135 and BF16 8288 = 32·259 bytes (`TokenLayout`: hidden + scale factors + 96 metadata bytes,
  each 16-byte aligned). A boundary at 2 rows mod 4 is 64 bytes off (×2.8–3.8 in DeepEP, where
  the 129 queues otherwise reach the link rate), odd boundaries are 32/96 bytes off (×1.6–1.9),
  multiples of 4 rows are aligned. My earlier statement that alignment did not explain the BF16
  arms used the 8256-byte combine row and was wrong; corrected above.
- Consequence for the transport: pad the packed row stride to a multiple of 128 bytes (4320 →
  4352, 8288 → 8320; +0.7 % / +0.4 % bytes) or keep every PUT boundary on a multiple of 4 rows.
  With padding, any first interval and any regular interval become safe, and the knob sweep can
  be revisited without the trap. The same rule applies to the combine's packed PUTs (8256 = 64·129:
  odd boundaries are 64 bytes off; the candidate's batch 16 / first batch 4 are even). Checked in the
  4K combine traces of 8700/8701: all 12288 and 6144 packed combine PUTs start at even rows (batch
  lengths 4/12 and 16), i.e. 100 % of the combine bytes were 128-byte aligned in mixed routing; a
  routing that breaks a channel's run at an odd row would not be, which is one more reason to pad.
- Raw single-queue numbers also give the per-PUT issue cost of the device primitives: about 5.7 µs
  per 69 KB PUT from one thread, i.e. a single queue cannot exceed ~12 GB/s at that PUT size; the
  kernels' 256 channels on 129 queues are what reach the link rate.

Artifacts: `tools/cxi_gin/experiments/pipeline_1101/offset_probe.cu`, `package_offset_probe_1101.py`,
raw logs `results/deepep_pipeline_20261101/job-3830643/results/results/9000-offset-probe-run1/offset/node*/gpu*.log`
(one JSON line per case and repeat). No allocation of mine is left on the system.

## Closing summary (2026-11-02 05:20 CET)

Target: dispatch/combine of DeepEP v2 over the direct-CXI GIN close to pure payload serialization.
Where the campaign ends: incremental bytes at the link rate for both operations (21.5 GB/s
dispatch, 19.8 GB/s combine, against 21.5 GB/s for the raw coalesced probe and 25 GB/s nominal);
4K V4 Flash at 1.15× the 21.5 GB/s bound for both operations (dispatch was 1.30× at the start of
the night, 4.1× on 10/30), 16K at 1.04× (dispatch) and 1.10× (combine). Every change is
compile-time-knobbed on one immutable GPU archive (`source-1101-first-batch-v1` =
`source-zero-packed-v7` + packed combine + final-tail merge + first-batch knobs), release-qualified
on four node pairs over the night, and reproduced on three model geometries.

What remains per call and what would move it:

- The 0.11 ms cross-rank entry barrier (`comm::gpu_barrier`) in both kernels: 12 % of a 4K
  dispatch. A kernel/launch change (programmatic dependent launch, or overlapping the count
  exchange with the previous kernel's tail), not a transport change.
- The 4K-specific NIC drain excess (0.18 ms with first interval 4; 0.03 ms at 16K): the NIC drains
  few large PUTs per queue worse than many. The 16K regular-interval-8 result (−1.4 %) and the
  first-interval result both point the same way; a size-dependent regular interval (8 for the
  16K template) is worth 1.4 % there, nothing at 4K (+3.3 %).
- Combine's first remote PUT at 0.35–0.43 ms is set by the NVLink contributions, not by the
  batch (first batch 4 changed nothing at 4K); overlapping the local reduction with the first
  remote PUTs is a kernel restructuring.
- The 128-byte alignment cliff (allocation I): PUTs whose addresses lie 64 bytes off a 128-byte
  line move at 5 GB/s, 32 or 96 bytes off at about 11 GB/s, aligned ones at full rate. Not on the
  candidate's path (its boundaries are multiples of 4 rows), but a trap for any cadence or layout
  change; pad the packed row stride to a 128-byte multiple (4320 → 4352, 8288 → 8320 bytes, +0.7 %
  / +0.4 % payload) so the transport is robust to the kernels' choices.

Harness notes for whoever continues: the controller accepts new `requests/*.json` while idle with
`CXI_KEEP_ALLOCATION=1` and runs any snapshot installed under the campaign `sources/`, which is
how F hosted the sweep, the traces and the release matrix (98 gates in one 4 h allocation);
`launch_1101.py --no-submit` installs and preflights a snapshot without a job; `summarize_arms.py`,
`fit_size_sweep.py` and `trace_timeline.py` are the analysis entry points; the F-era controller's
`ep_trace` branch is the old fixed-event-set one, so trace gates were run as kind `ep` and the
traces validated offline. Jobs touched tonight: 3829353 (A), 3829402 (B), 3829630 (C), 3830035 (D),
3830077 (E), 3830101 (F, with the sweep, G and H pushed in), 3830643 (I, raw probe). None of the
user's own jobs were touched.
