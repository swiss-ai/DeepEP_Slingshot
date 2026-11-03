# EP8 microbenchmark on the direct-CXI GIN path: DeepSeek V4 Flash with OpenSWE routing (2026-11-03 evening)

Status: complete for the evening (autonomous window 19:00–23:00 CET; plan written before the first job, results from five debug jobs, all allocations released by 21:11).
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
stands, and the campaign's exposure is placements that localise traffic. A localisation job
(`source-1103-pad128-diag-v1`, job 3845106, submitted 20:46) runs four single-case correctness gates with
their own 300 s budgets: BF16 4K (no FP8 scale region), FP8 32 tokens, FP8 257 tokens, BF16 32 tokens.

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

### 4.7 S100: the synthetic skew ladder (job 3845070, nid007648/007658, 20:48 CET; all cases exact)

Two destination ranks per token; the receiver skew moves rows per destination while the pair maximum of NIC
rows stays 4096. `local` has no NIC traffic (NVLink only), `uniform` is random top-6 (4.5 destination
ranks per token, 2.24× the rows per destination of `mixed`, imbalance 1.01).

| case | NIC rows mean (pair max) | rows per destination max (max/mean) | dispatch_fresh ms | combine ms | combine / bound |
|---|---|---|---:|---:|---:|
| local | 0 (0) | 8192 (1.00) | 0.300 | 0.279 | — |
| mixed | 4096 (4096) | 8192 (1.00) | 0.934 | 1.755 | 1.17 |
| remote | 4096 (4096) | 8192 (1.00) | 0.928 | 1.744 | 1.16 |
| skew1.2 | 4038 (4096) | 9830 (1.20) | 0.930 | 1.757 | 1.17 |
| skew1.6 | 3923 (4096) | 13107 (1.60) | 0.922 | 1.871 | 1.24 |
| skew2 | 3809 (4096) | 16384 (2.00) | 0.944 | 2.102 | 1.40 |
| skew4 | 3218 (4096) | 32768 (4.00) | 0.967 | 2.340 | 1.56 |
| uniform | 4034 (4050) | 18356 (1.01) | 0.967 | 1.879 | 1.26 |

Findings:
1. **Dispatch follows the NIC, not the receiver.** From skew 1 to 4 the hottest GPU receives 4× the rows and
   dispatch moves from 0.93 to 0.97 ms (+4 %); `uniform` with 2.24× the rows everywhere costs the same +4 %.
   The dispatch period is the slowest rail pair's wire (pair maximum 4096 rows in every case) plus a small
   receive-side term.
2. **Combine follows the hottest rank's rows.** Combine is flat to skew 1.2, then +7 % at 1.6, +20 % at 2.0,
   +33 % at 4.0 (1.76 → 2.34 ms) with unchanged NIC bytes. The rows a rank received in dispatch are the
   expert outputs it must send back over NVLink in the combine's scale-up stage (0.26 ms for 8192 rows on
   `mixed`, 11_03 §5); at 4× the rows that stage outlasts the wire's head start and the forwarders' PUTs
   starve the NIC. `uniform` (+7 %) shows the volume part of the effect without imbalance.
3. **The real-routing surcharge decomposes.** `uniform` costs +4 % dispatch / +7 % combine with imbalance 1.0;
   the bank cases cost +5 % / +9 % at imbalance 1.1–1.6; so most of the surcharge is the 2.2× destination
   volume of top-6 routing, and the imbalance adds the rest, growing steeply beyond 1.6.
4. **NVLink-only cost.** `local` gives the intra-node floor: 0.30 ms dispatch and 0.28 ms combine for
   8192 rows per GPU, i.e. the hybrid path's scale-up stages; the EP4 numbers of 10_22 (0.19 / 0.35 ms at
   4096 tokens per rank) are of the same order.

### 4.8 S101–S103: more bank forwards, the skew repeat, and a stress corner (same job)

**S101, bank forwards 302 and 303** (18 cases, exact): dispatch median 0.982 ms (0.966–0.994), combine 1.922
(1.895–1.999), the same surcharge as forwards 300/301; the regression on destination imbalance has the same
slopes (+0.044 / +0.117 ms per unit) at lower R² (0.44 / 0.31) because the imbalance range of these forwards
is narrower (1.08–1.51). Across the four forwards, 36 bank cases at FP8: dispatch 0.966–1.004 ms, combine
1.882–1.999 ms, cycle 2.86–3.05 ms per layer.

**S102, skew ladder repeated**: `mixed`, `skew1.2`, `skew1.6`, `skew2` and `local` reproduce S100 within
5–30 µs (combine 1.752 / 1.757 / 1.860 / 2.069 ms; local 0.291 / 0.283). The three NIC-using cases that ran
after `skew4` did not: `skew4` combine 2.893 ms (2.340 in S100), `remote` 1.610 / 3.324 ms (0.928 / 1.744),
`uniform` dispatch 1.541 ms (0.967), all with exact results and with CUDA-event medians equal to the wall
times (slower kernels, not stalls). **S103, the BF16 skew ladder**, passed `mixed` to `skew2` with BF16
dispatch 1.67–1.73 ms and the same combine ladder (1.755 / 1.761 / 1.867 / 1.994 / 2.383 ms), then failed
on `skew4` with the dispatch's host-side count wait reporting zero received rows on every rank (fail-fast
exception, no trap). `skew4` puts 32768 rows on one destination, exactly the receive capacity
(8 sources × 4096), so this is operation at the buffer edge, a stress corner rather than a serving pattern;
the degradation of the cases after it in S102 suggests the transport does not fully recover from it within
the job. The serving-relevant range (imbalance ≤ 1.6) reproduced exactly in both repeats. Job 3845070
released at 20:59.

### 4.9 Job 3845106: localising the padded-stride failure (nid007648/007666, 21:03 CET)

Q100 (BF16 dispatch, 4096 tokens, one `mixed` case): the dispatch kernel faults, `CUDA error: unspecified
launch failure` surfacing at the host's read of the received counts, on every rank, 129 s into the gate
(build and JIT included). So the padded build is not merely slow: with BF16 rows (8320 B, no FP8 scale
region) the dispatch writes or reads outside its buffers; the FP8 4K hang of job 2 was most likely the same
fault turned into a wait. The job was resumed for the small-token gates: **FP8 32 tokens, FP8 257 tokens and
BF16 32 tokens all PASS** (exact dispatch and combine, one `mixed` case each). The padded stride therefore
works until the receive layout is filled: with 4096 tokens per rank every destination holds its full
8 × 4096 rows and the wider rows reach past what some consumer sized with the unpadded row (the NCCL window
or receive-layer size on the host, or a per-channel capacity in bytes). The fix is a host-side size audit of
every place that derives bytes from hidden, scales and top-k instead of `TokenLayout::get_num_bytes`,
followed by the 4K correctness gate; the device side needs no change. Job 3845106 released at 21:11.

## 5. Position for the EP8 serving campaign (21:15 CET, all jobs finished and released)

1. **The direct-CXI path can carry EP8 serving experiments with real routing.** 72 real-routing cases
   (four forwards, three layers, three placements, FP8 and BF16, two repeats) and 21 synthetic cases, all
   exact. Per MoE layer for V4 Flash at 4096 tokens per rank: dispatch 0.97–1.00 ms, combine 1.88–2.00 ms,
   2.9–3.0 ms together, 1.25–1.33× the wire bound. On the 10_26 decision rule: U = 0.78 passes; comm ≈ 3×
   the ~1 ms expert GEMM fails the "comm ≤ 2× GEMM" half, so the EP8 step is communication-bound by about
   3× (the proxy transport was 20×). Projected over 40 layers: ~116 ms of communication per 32K-token
   forward.
2. **What the communication time follows** (R10(d)): dispatch follows the slowest rail pair's NIC rows and
   is insensitive to receiver skew up to 4× (0.93 → 0.97 ms); combine follows the hottest rank's rows
   through its NVLink scale-up stage once they exceed ~1.3× the mean (+7 % at 1.6, +20 % at 2.0, +33 % at
   4.0). Real OpenSWE routing sits at imbalance 1.1–1.6, where the surcharge over the synthetic reference is
   mostly the 2.2× destination volume of top-6 routing (`uniform`: +4 % / +7 % at imbalance 1.0) plus a
   small imbalance term. For the EP8 time model: NIC term = pair maximum of (token, remote node) rows (routing-
   invariant for V4 Flash on OpenSWE, 4096 per forward unit); receive term ∝ max destination rows, with a
   knee near 1.3× the mean for the combine.
3. **Placement at r = 0 cannot move the communication term**: the greedy balanced partition and a random
   permutation change dispatch by ≤ 1.5 % and combine by ≤ 4 % within a layer, in no consistent order, and
   the whole-forward projection separates the placements by 0.4 %. Placement effects at EP8 must come through
   replicas (r ≥ 1, the paper's EPLB and swap layouts) acting on the hottest destination, and through the
   GEMM term; the r = 1 layouts need an EP8 export (the offline archives hold metrics only).
4. **Alignment cliff**: absent on OpenSWE because nearly every row is remote (gapless runs). The padded
   128-byte row stride that would remove the exposure is exact at 32 and 257 tokens in both dtypes and faults
   at 4096 tokens (receive layout at capacity) in both: a host-side size consumer still uses the unpadded
   row. One audit plus the 4K correctness gate away from usable; until then keep the four-row rule and
   expect the cliff only from placements that localise traffic.
5. **Stress corner**: a destination at receive capacity (32768 rows = 8 × 4096) degrades the transport for
   the rest of the job and failed once with BF16 rows (host count wait, zero rows). Not a serving pattern at
   EP8 (needs 4× mean on one GPU), but a hard limit to document for the campaign's gates.
6. **Still missing for the campaign** (unchanged): the two-node SGLang boot over the adapter, the
   expert-distribution recorder for the replay banks (disabled in the adapter), EP8 harness editions
   (two-node sbatch, collect scripts), r = 1 layouts for EP8.

## 6. Files

- Generator and bank subset: `tools/cxi_gin/experiments/pipeline_1103/bank_routing.py`,
  `bank_v4flash_openswe_ep8.npz`; benchmark patch `prepare_ep8bank_1103.py`; packagers
  `package_ep8bank_1103.py` (job 3844569), `package_pad128_1103.py` + `prepare_pad128_1103.py` (job
  3844593), `package_ep8skew_1103.py` (jobs 3845018 failed on packaging, 3845070), `package_pad128diag_1103.py`
  (job 3845106); table tool `bank_table.py`.
- Results: `results/deepep_pipeline_20261101/job-384{4569,4593,5070,5106}/results/results/<gate>/direct/ep/`
  (`timings-rank*.jsonl` with the `bank` / `traffic` dicts, `correctness-rank*.jsonl`); curated copies on the
  `debug` branch of the review repository, this document in both branches.
