# EP8 microbenchmark on the direct-CXI GIN path: DeepSeek V4 Flash with OpenSWE routing (2026-11-03 evening)

Status: in progress (autonomous window 19:00–23:00 CET; plan written before the first job).
Companion documents: `10_26_EP8_Microbenchmark.md` (question and decision rule), `11_03_DeepEP_v2_Slingshot.md`
(the transport's state: lean-b with the two kernel knobs, release matrix passed; combine levers of the afternoon),
`10_24_EXPERIMENT_REQUIREMENT.md` (the EP4 serving protocol an EP8 campaign would follow).

## 1. Question

The EP4 serving campaign compared expert placements on one node. Its EP8 counterpart needs the cross-node
dispatch/combine at a cost that leaves placement effects measurable. The transport now runs the hybrid
DeepEP v2 kernels at 0.93 ms dispatch / 1.75 ms combine per layer for 4096 tokens per rank with the
benchmark's synthetic `mixed` routing (two destination ranks per token). Serving traffic is different:
a V4 Flash token has six experts spread over about 4.4 of the 8 ranks (OpenSWE bank), so nearly every token
crosses the node boundary, rows per destination are imbalanced, and the packed combine runs break where
the router interleaves local and remote rows. Three questions for the demo:

1. **Transport cost under real routing.** Per-layer dispatch and combine time with bank-consistent OpenSWE
   routing (exact per-expert counts of real 4K units) against the synthetic `mixed` reference, and against
   the wire bound computed from the real NIC rows of each case.
2. **Alignment cliff under real routing.** The combine's packed PUT batches start wherever a run of remote
   rows starts; a start at an odd row costs 4× on that PUT (11_01 alignment probe; today's one-row first
   batch result). Real routing produces such starts; synthetic routing does not. The ratio of the measured
   combine time to its wire bound, compared with `mixed`, measures the penalty.
3. **Placement sensitivity of the communication term.** Vanilla (expert e on rank e // 32), a greedy balanced
   partition fitted on 256 training forwards (r = 0, this document's own fit, not the paper's EPLB or swap
   search), and a random permutation. Under the hybrid path a token crosses the NIC once per remote node,
   so the NIC rows per source barely depend on placement (offline study `results/ep8_offline/ep8_summary.md`
   I); rows per destination do. The measurement tells which of the two the period follows at EP8.

## 2. Method

- Harness: the campaign pipeline (`tools/cxi_gin/experiments/pipeline_v1`, snapshots, controller, debug
  partition, 2 nodes × 4 GH200, one 200 Gb/s NIC per GPU), transport lean-b with `CXI_EP_SKIP_COMBINE_FLUSH=1`
  and `CXI_EP_LOCAL_SELF_SIGNAL=1` (the release candidate), DeepEP v2 at bd1e1669 with the packed paths
  (first interval 4, first batch 4), 64 SMs, 129 contexts. Every case is checked bit-exact against the
  reference all-to-all dispatch and the combine tolerance before it is timed.
- Routing: `backend/tests/bank_routing.py` realises a bank unit's per-expert counts for one layer as a
  (4096, 6) table of distinct expert ids per token (copies of every expert laid out contiguously, in a
  random expert order, into a (6, 4096) array and transposed: a run of at most 4096 copies never meets the
  same token twice). Units whose counts sum below 4096 × 6 (39 of 1280 in the test forwards, one slot
  short) get a `-1` slot with weight 0, which DeepEP accepts. Bank: `v4flash_daint_td_buckets_openswe.npy`
  (16384 units × 40 layers × 256 experts); forward f = units 8f..8f+7, rank r takes unit 8f + r.
- Cases: forwards 300 and 301 (held out from the training forwards 0–255), layers 3, 20 and 37 (an early,
  a middle and a late MoE layer), placements vanilla / greedy / random, FP8 dispatch and BF16 combine, 20
  warm-up and 100 timed iterations plus the 600-iteration NIC loop, as in the release repeats; the synthetic
  `mixed` routing as the reference case in the same gate. A BF16-dispatch gate and a gate with the
  afternoon's combine knobs (`CXI_EP_COMBINE_FIRST_TAIL=1`, `CXI_EP_COMBINE_FIRST_BATCH=2`) follow.
- Recorded per case (in `timings-rank*.jsonl` and `correctness-rank*.jsonl`): `bank` = forward, layer,
  placement, unit, rows per destination rank, NIC rows per source rank, per rail pair the larger of its two
  directions. Wire bound per case: pair_rows_max × row bytes / 22.5 GB/s (FP8 dispatch row 4320 B incl.
  scales, BF16 combine row 8256 B).

- Second job, padded row stride (`prepare_pad128_1103.py`, snapshot `source-1103-pad128-v1`): DeepEP's
  per-token size rounded up to a 128-byte multiple (FP8 dispatch row 4320 → 4352 B, BF16 dispatch 8288 →
  8320, combine 8256 → 8320; +0.4 to +0.8 % payload), component offsets unchanged, host and device from the
  same header. Gates: 4K correctness (FP8+BF16, five routings, two seeds), the bank cases in FP8 and BF16,
  and the synthetic 4K+16K repeat for the padding's own wire cost. If the bank cases pay an odd-row penalty
  in job 1, job 2 shows whether the padding removes it; if they do not, job 2 is the alignment fix qualified
  on correctness for the serving campaign anyway.

- Third job (when a submission slot frees; `package_ep8skew_1103.py`): which traffic quantity the time
  follows. The synthetic skew routings keep two destinations per token and the pair maximum at 4096 NIC rows
  while rows per destination grow (max/mean 1.2, 1.6, 2, 4; mean NIC rows per source fall 4038 → 3218), `local`
  has no NIC rows at all, `remote` one per token; bank forwards 302 and 303 add more real cases. Traffic
  statistics are recorded for every case, so per-layer dispatch and combine time can be regressed on NIC rows,
  pair maximum and destination rows in one table: if the period follows the slowest rail pair (as the afternoon's
  combine analysis says), the skew ladder costs nothing in dispatch/combine time; if it follows destination rows
  (receive side, NVLink forwarding), skew4 is far slower. This decides R10(d) of the EP4 requirements.

## 3. Expected traffic of the planned cases (computed locally from the bank before the run)

Every token of the OpenSWE units touches the other node (mean NIC rows per source 4000–4080 of 4096,
pair maximum 4096 in every case), exactly like the synthetic `mixed` routing (one local and one remote
destination per token, 4096 NIC rows). So the NIC bytes per layer are the same for all cases, 17.7 MB per
NIC per direction for FP8 dispatch and 33.8 MB for the BF16 combine, and the wire bounds are the same as
the campaign's (0.786 / 1.503 ms at 22.5 GB/s). What differs is the receive side: a token reaches 4.4
distinct ranks on average instead of 2, so each destination GPU receives about 2.2× the rows of `mixed`
over NVLink (forwarding stage), with an imbalance of 1.1 to 1.6 (max/mean over destinations) that the
greedy placement does not systematically reduce at r = 0:

| forward | layer | placement | NIC rows mean / max | rows per destination max/mean |
|---:|---:|---|---|---:|
| 300 | 3 | vanilla / greedy / random | 4054 / 4066 / 4019, max 4096 | 1.63 / 1.54 / 1.59 |
| 300 | 20 | vanilla / greedy / random | 4080 / 4056 / 4021, max 4096 | 1.21 / 1.20 / 1.15 |
| 300 | 37 | vanilla / greedy / random | 4034 / 4017 / 4060, max 4096 | 1.31 / 1.46 / 1.19 |
| 301 | 3 | vanilla / greedy / random | 4052 / 4064 / 4002, max 4096 | 1.44 / 1.48 / 1.52 |
| 301 | 20 | vanilla / greedy / random | 4020 / 4021 / 4024, max 4096 | 1.19 / 1.08 / 1.21 |
| 301 | 37 | vanilla / greedy / random | 4000 / 4058 / 4051, max 4096 | 1.20 / 1.30 / 1.22 |

Training-load balance of the placements (layer mean over forwards 0–255, max/mean over ranks): vanilla
1.14–1.29, greedy 1.00, random 1.15–1.31. Prediction before the run: if the period is NIC-bound the bank
cases cost what `mixed` costs (0.93 / 1.75 ms); a combine well above 1.75 ms is the odd-row alignment
penalty of real runs; any spread between placements of the same layer is a receive-side (NVLink forwarding,
destination imbalance) effect, since the NIC rows are equal.

## 4. Results

Jobs: 3844569 = `source-1103-ep8bank-v1` (X100–X103, submitted 19:08 CET), 3844593 = `source-1103-pad128-v1`
(P100–P103, submitted 19:14 CET). Debug queue at submission: 23 running, 29 pending; one running job per user.

### 4.1 X100: release transport, FP8 dispatch / BF16 combine, real OpenSWE routing (job 3844569, nid007649/007656, 20:03 CET)

All 19 cases exact (bit-exact dispatch against the reference all-to-all, combine within tolerance). Wall time
per iteration, slowest rank; bounds at 22.5 GB/s from the pair maximum of 4096 rows (0.786 / 1.503 ms):

| case | dest rows max/mean | dispatch_fresh ms | combine ms | combine / bound |
|---|---:|---:|---:|---:|
| mixed (synthetic reference) | 1.00 | 0.933 | 1.757 | 1.17 |
| f300 L3 vanilla / greedy / random | 1.63 / 1.54 / 1.59 | 1.000 / 1.000 / 0.988 | 1.948 / 1.936 / 1.947 | 1.30 |
| f300 L20 vanilla / greedy / random | 1.21 / 1.20 / 1.15 | 0.978 / 0.977 / 0.970 | 1.884 / 1.882 / 1.896 | 1.25 |
| f300 L37 vanilla / greedy / random | 1.31 / 1.46 / 1.19 | 0.977 / 0.984 / 0.977 | 1.968 / 1.911 / 1.893 | 1.26–1.31 |
| f301 L3 vanilla / greedy / random | 1.44 / 1.48 / 1.52 | 1.004 / 0.993 / 0.988 | 1.935 / 1.930 / 1.941 | 1.29 |
| f301 L20 vanilla / greedy / random | 1.19 / 1.08 / 1.21 | 0.968 / 0.971 / 0.969 | 1.906 / 1.906 / 1.904 | 1.27 |
| f301 L37 vanilla / greedy / random | 1.20 / 1.30 / 1.22 | 0.976 / 0.984 / 0.983 | 1.937 / 1.895 / 1.903 | 1.26–1.29 |

Findings:
1. **Real routing costs 4–8 % on dispatch and 7–12 % on combine** over the synthetic reference with the same
   NIC bytes (dispatch 0.968–1.004 vs 0.933 ms; combine 1.882–1.968 vs 1.757; dispatch+combine cycle
   2.859–2.999 vs 2.691 ms). Per MoE layer the communication is 2.9–3.0 ms against roughly 1 ms of expert GEMM
   at EP8: the step is communication-bound, as the offline time model said, but by 3× rather than 20×
   (the proxy transport's 13 ms).
2. **The extra cost follows the receive side, not the NIC.** Across the 18 bank cases the time regresses on
   the destination-row imbalance (dispatch slope +0.055 ms per unit of max/mean, R² 0.72; cycle +0.23 ms,
   R² 0.79) and not on NIC rows (R² ≤ 0.16; they are 4000–4080 everywhere). Layer 3 (imbalance 1.4–1.6)
   costs 1.00 / 1.94 ms, layer 20 (1.1–1.2) 0.97 / 1.89 ms. With 4.4 destination ranks per token the
   forwarders receive 2.2× the rows of `mixed` over NVLink and the busiest destination up to 1.6× the mean.
3. **Placement moves little at r = 0.** Within a (forward, layer) the three placements differ by ≤ 1.5 % in
   dispatch and ≤ 4 % in combine, not in a consistent order; the greedy partition balances the training load
   (max/mean 1.00) but not the per-forward destination rows (1.08–1.54). This is the r = 0 limit: without
   replicas, a hot expert's rows land on one GPU whatever the partition.
4. **No alignment penalty on OpenSWE.** Every token touches the other node, so each channel's rows are nearly
   all remote and the packed runs are gapless; batches start on multiples of four rows and the 4× cliff does
   not appear (a cliff would show as combine/bound far above 1.3). The cliff would appear exactly when a
   placement keeps many tokens node-local and runs break at odd rows, so the padding fix (job 2) remains a
   precondition for the serving campaign.

### 4.2 X101 (BF16 dispatch) and X102 (combine knobs first tail 1 / first batch 2), same job

| gate | operation | mixed | bank median (min–max) | median vs mixed |
|---|---|---:|---|---:|
| X101 BF16 dispatch | dispatch_fresh | 1.692 (1.12× bound 1.509) | 1.792 (1.763–1.824) | +5.9 % |
| X101 | combine | 1.757 | 1.917 (1.882–1.975) | +9.1 % |
| X101 | cycle | 3.450 | 3.706 (3.656–3.818) | +7.4 % |
| X102 knobs, FP8 | dispatch_fresh | 0.935 | 0.982 (0.967–1.003) | +5.0 % |
| X102 | combine | 1.741 | 1.915 (1.886–1.978) | +10.0 % |
| X102 | cycle | 2.672 | 2.898 (2.859–3.002) | +8.5 % |

The real-routing surcharge is the same for BF16 dispatch (+6 %) as for FP8 (+5 %), so it is not a payload
effect. The afternoon's combine knobs keep their 16 µs on `mixed` (1.741 vs 1.757) but give nothing on the
bank cases (1.915 vs 1.909 medians): under real routing the forwarders' first PUT is no longer what the
period waits for; the receive side is.

### 4.3 X103: repeat of X100 in the same job

The 19 cases reproduce within 4 µs (dispatch) and 24 µs (combine) case by case (mean difference +0.6 µs);
bank medians 0.981 / 1.908 ms against 0.981 / 1.909 in X100. Job 3844569: four gates, all PASS, released at
20:17 CET.

### 4.5 Job 2, padded row stride (3844593, same pair as job 1, 20:17 CET)

P100 (4K correctness, FP8+BF16, five routings, two seeds, 300 s budget) was killed by the gate budget after
303 s. The node-local log ends with the NCCL ring set-up, with no DeepEP timeout, trap or Python error; the
extension build had passed. A first gate carries the extension build (~100 s) and, for two dtypes, two
kernel JIT sets (~100 s each), so 300 s is below what this gate needs even when nothing is wrong (the X100
gate with one dtype took 293 s). Re-staged as P104 with a 600 s budget into the job's remaining 16 minutes
(dependent gates removed; they would not have fitted). P104 settled it: six minutes in, the four ranks of
node 0 were spinning at ~3 CPU cores each, the JIT had produced its four kernels within the first minute
(compiler reports at 20:26), and the node log ended at the buffer creation with no case record, no DeepEP
timeout and no trap. The padded build hangs in its first dispatch, with the host spinning on the received
counts. Job 2 was cancelled at 20:34 (the skew job was re-based on the unpadded parent,
`source-1103-ep8skew-v2`). The padding therefore needs a debugging session: some consumer of the row size
does not go through `TokenLayout::get_num_bytes` (candidates: the packed-channel capacity arithmetic, the
notify/count path, the shared-memory staging layout with the mbarrier variant); a device-traced run of one
small case is the next step. Until then the alignment rule (batch boundaries on multiples of four rows)
stands, and the campaign's exposure is placements that localise traffic.

### 4.4 Projection over a whole forward (model, not measured)

Applying the X100 regression (dispatch 0.910 + 0.055 × imbalance, combine 1.789 + 0.097 × imbalance, ms) to
the destination-row imbalance of every one of the 40 MoE layers of the four test forwards:

| forward | mean imbalance vanilla / greedy / random | communication per forward, ms (40 layers) |
|---:|---|---|
| 300 | 1.385 / 1.336 / 1.386 | 116.4 / 116.1 / 116.4 |
| 301 | 1.332 / 1.261 / 1.342 | 116.1 / 115.6 / 116.1 |
| 302 | 1.290 / 1.238 / 1.307 | 115.8 / 115.5 / 115.9 |
| 303 | 1.251 / 1.211 / 1.250 | 115.6 / 115.3 / 115.6 |

About 116 ms of dispatch+combine per 32K-token forward at EP8, of which 39 ms dispatch and 77 ms combine; the
greedy r = 0 partition saves 0.3–0.4 % of it. For scale: the EP4 prefill step of V4 Flash is ~300 ms
(10_23_RUNBOOK §8.10), so EP8 communication alone would be 40 % of that step time before the halved expert
GEMM and attention are added; placement work at EP8 must target the GEMM term and replicas, as the offline
study concluded, and the communication term is a near-constant 116 ms with a ±1 % receive-side modulation.

### 4.6 Job 3, skew ladder: packaging error and resubmission

`source-1103-ep8skew-v2` (job 3845018, 20:33 CET) failed at argument parsing on every rank: its packager had
copied the workspace copy of `bank_routing.py` over the snapshot's, dropping the loader and the routing
validator that the bank preparation appends, so the benchmark died before the first case (my error, found in
the copied node log). The job was cancelled at 20:40, the packager now patches the snapshot's file in place,
and `source-1103-ep8skew-v3` (same gates: skew ladder FP8, bank forwards 302/303, skew repeat, skew BF16)
was submitted at 20:42 as job 3845070 (debug queue: 20 running, 23 pending). The earlier variant on the padded parent (job 3844958) was cancelled unrun.

## 5. Position for the EP8 serving campaign (interim, after job 1; updated after jobs 2 and 3)

1. **The transport is usable for EP8 serving experiments with real routing.** Exact results on 76 real-routing
   cases (FP8 and BF16, three placements, two forwards, three layers, two repeats), per-layer communication
   2.9–3.0 ms for V4 Flash at 4096 tokens per rank (dispatch 0.97–1.00, combine 1.88–1.97 ms), 1.25–1.31× the
   wire bound. Against the 10_26 decision rule (U ≥ 0.5 and comm ≤ 2× GEMM): U = 0.78 passes; comm ≈ 3× the
   ~1 ms expert GEMM fails the second half, i.e. the EP8 step is communication-bound by about 3× (the proxy
   transport was 20×). Placement effects on the step will have to show through the receive side and the GEMM,
   not through the NIC bytes, which real routing fixes at one row per token per direction.
2. **What the per-layer time follows at EP8** (R10(d) of the EP4 requirements): destination-row imbalance,
   not NIC rows (R² 0.7–0.8 vs ≤ 0.2 across the bank cases). The offline EP8 time model should carry the
   communication term as a function of the busiest destination's rows (slope ≈ 0.055 ms dispatch and
   ≈ 0.10 ms combine per unit of max/mean at 4K, from 18 cases; job 3 adds the synthetic ladder). The paper's
   "busiest-NIC rows" metric is the right one for the NIC bytes but those are routing-invariant here.
3. **Alignment.** No penalty on OpenSWE because nearly every row is remote and runs are gapless; the padded
   128-byte row stride (job 2) is the guard for placements that localise traffic.
4. **Still missing for the campaign:** the two-node SGLang boot over the adapter (never done), the recorder
   for replay banks (disabled in the adapter), EP8 editions of the harness (two-node sbatch, collect scripts),
   and layouts with replicas (r = 1, the paper's EPLB/swap) exported for EP8, since r = 0 placements do not
   move the receive side.
