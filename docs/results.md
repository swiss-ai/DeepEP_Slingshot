# Results

All numbers: EP8 on two Clariden GH200 nodes, 64 SMs, 129 contexts, exact correctness verified
against an independent NCCL all-to-all before timing, medians of repeats. Raw per-gate medians are
in [`evidence/gates-3830101/<gate>/direct/ep/repeatability.json`](../evidence/gates-3830101/);
verdicts and environments in each gate's `FINISHED.json`.

## Progress over the campaign

V4 Flash (hidden 4096, 256 experts, top-k 6), FP8 dispatch, BF16 combine, mixed routing.

| Operation | 10/30 start | 10/31 | final (11/02) | bound at 22.5 GB/s | final / bound |
|---|---:|---:|---:|---:|---:|
| 4K tokens/rank dispatch | 3.399 ms | 1.075 ms | 0.949 ms | 0.786 ms | 1.21 |
| 4K tokens/rank combine | 4.387 ms | 3.439 ms | 1.814 ms | 1.503 ms | 1.21 |
| 16K tokens/rank dispatch | 10.46 ms | 3.498 ms | 3.439 ms | 3.146 ms | 1.09 |
| 16K tokens/rank combine | not run | 13.30 ms | 6.946 ms | 6.013 ms | 1.16 |

The bound is payload serialisation at 22.5 GB/s per rail per direction, the NIC's measured
bidirectional ceiling (next section). Size-sweep fits (2K to 16K tokens): dispatch
0.147 ms + bytes / 21.5 GB/s, combine 0.121 ms + bytes / 19.8 GB/s. So the incremental rate is
4 to 12% under the ceiling, and on top of that there is a fixed per-call cost (cross-rank entry
barrier about 0.11 ms, notify exchange, signal tails, epilogue).

## Signal-path round (2026-11-02 afternoon, debug allocations, two node pairs)

Knob-guarded changes on the final candidate ([patches/1102/](../patches/1102/)): no GPU-side flush
before the combine end signal (`CXI_EP_SKIP_COMBINE_FLUSH`), no NIC self-signal in the GIN barrier
(`CXI_EP_LOCAL_SELF_SIGNAL`), and the `lean-b` transport variant (CQ fence only when a transfer was
posted since the last fence, CSTATE cached per context, delivery epoch closed on the pending PUT
instead of a zero-byte marker). Every correctness ladder passed (irregular stress, 4K FP8/BF16 on
five routings, dropped tokens, sustained 16K) on jobs 3835147, 3835199 and 3835540.

| wall per iteration, slowest rank (V4 Flash FP8 mixed) | candidate | lean-b + kernel knobs | effective |
|---|---:|---:|---:|
| 4K dispatch | 0.946 ms | 0.934 ms (−1.2 %) | 18.9 GB/s |
| 4K combine | 1.803 ms | 1.759 ms (−2.4 %) | 19.2 GB/s |
| 4K dispatch + combine cycle | 2.750 ms | 2.692 ms (−2.1 %) | |
| 16K dispatch | 3.451 ms | 3.412 ms (−1.1 %) | 20.7 GB/s |
| 16K combine | 6.945 ms | 6.884 ms (−0.9 %) | 19.7 GB/s |

The kernel knobs alone give almost all of it (kern: −1.1 % / −2.0 % at 4K); the lean transport adds
0.1–0.5 %. **Metric note:** removing the combine flush decouples the two rail peers' kernel ends, so
the harness headline (median over iterations of the per-iteration maximum across the eight ranks)
reads +1 % at 4K and +3.5 % at 16K for the same gates although throughput improves; it is inflated by
the end skew (per-rank histograms become bi- or trimodal with steps of ≈80 µs at 4K / ≈330 µs at 16K).
`harness/pipeline_1102/effective_rate.py --wall` reports the wall time per iteration of the slowest
rank, which is the throughput a serving loop sees. The release matrix of these arms passed on
2026-11-03 (job 3835100, nid007560/007561, 45 gates: stress, 4K, dropped and sustained-16K ladders for
kern, lean-a, lean-b and dbuf, repeats, three trace gates). Lean-b with the two kernel knobs is the
release candidate: 4K dispatch 0.932 ms / combine 1.758 ms, 16K 3.411 / 6.877 ms (wall per iteration,
slowest rank; 19.0 / 19.2 GB/s and 20.8 / 19.7 GB/s effective).

Measured and closed as losses at 4K in the same allocations: 128 SMs / 257 contexts (+14 % dispatch,
+8 % combine), one context per channel with 64 SMs (+7.7 % / +2.6 %), dispatch interval 8 (+3.1 %),
combine batch 8 (+1.5 %); double-buffered TMA staging in the scale-up warps is neutral.

## Where the remaining time goes (2026-11-02 evening, traced builds, debug slices)

A third node pair (job 3837809) reproduces the lean arms: 4K dispatch 0.947 → 0.934 ms, combine
1.803 → 1.755 ms, cycle −2.1 %, 16K −0.4 to −0.7 % (wall per iteration). The traced builds of the same
arms, with the trace validator now following the knobs ([patches/1102/trace-validator-knobs-1102.patch](../patches/1102/trace-validator-knobs-1102.patch)),
decompose a 4K call as follows (medians over 24 captures, kernel-relative ms; details and tools in the
[11/02 log §5](history/11_02_DeepEP_v2_Slingshot.md)).

| Dispatch, lean-b + kernel knobs | | Combine | |
|---|---:|---|---:|
| entry barrier end | 0.09 | entry barrier end | 0.08 |
| first PUT: attempt → emitted | 0.11 → 0.21 | first local token at a forward warp | 0.20 |
| last PUT emitted | 0.33 | first / last PUT emitted | 0.28 / 0.46 |
| receivers' last remote tail observed | 1.06 | last channel's remote rows complete | 1.88 |
| kernel end / CUDA event (epilogue incl.) | 1.15 / 1.24 | kernel end / CUDA event | 1.88 / 1.96 |

- The dispatch **receivers are idle 86 %** of their role; once fed, the NIC delivers the 17.7 MB in
  0.79–0.84 ms, at the 22.5 GB/s ceiling. The dispatch loss is that the first emission happens at
  0.20–0.25 ms instead of ~0.12: **every channel's first PUT spends ~100 µs in the transport** (lock
  wait ~47 µs behind a sibling whose first ring access takes ~85 µs; later PUTs cost 15–25 µs).
- With cached queue credits (`CXI_CREDIT_CACHE`, [patches/1102/credit-cache-backend-1102.patch](../patches/1102/credit-cache-backend-1102.patch);
  correct through the full ladder including sustained 16K, 99.9 % fewer NIC status reads) the same ~80 µs
  moves from the status read into the first ring store plus system fence, and the timeline does not move.
  The cost is the **first access per kernel to each context's host-mapped command ring** when 128 contexts
  start together, not the NIC read and not the fence as such.
- Combine's wire phase runs at 21.1 GB/s from the first PUT; its loss is the 0.28 ms before it (barrier,
  inter-rank skew, scale-up handoff), which is DeepEP-level.
- Closed the same evening: 32 SMs / 128 channels (correct, +2.3 % dispatch, +0.8 % combine at 4K) and the
  credit cache as a speed lever (kept as variants `cache-a`, `lean-c`).
- A barrier-time prewarm that touches every context's ring while the barrier waits
  (`CXI_EP_PREWARM_CONTEXTS`, [patches/1102/prewarm-contexts-1102.patch](../patches/1102/prewarm-contexts-1102.patch))
  is correct and changes nothing: the traced build still shows the first PUT at ~100 µs although the
  same word was loaded during the barrier. The cost is paid **per access while 128 contexts access the
  host-mapped rings at the same instant** (system-scope loads and stores on the `cudaHostRegister`ed
  ring, 1–3 µs when spread out), not per translation. Open leads, a few lines each: confirm which
  registration path the ring takes (plain mapped or the IO-memory fallback), and write the 64-byte
  command with fewer system-scope transactions (11/02 log §5.9).

## Command-ring memory and the convoy (2026-11-03, holder 3835100 and debug slices)

The ring the GPU writes commands into is libcxi's command queue: kernel pages mapped into the process
from `/dev/cxiN` (`remap_pfn_range`). A diagnostic build (`CXI_MAP` lines, [patches/1103/](../patches/1103/))
shows that `cudaHostRegisterMapped` refuses it ("invalid argument") and every TX and triggered ring is
registered as IO memory (266 of 798 mappings per rank; doorbells by design, host buffers plainly). The
GH200 nodes report `PageableMemoryAccessUsesHostPageTables=1`, so `CXI_RING_ACCESS=ats` lets the kernel
address the ring's host virtual address directly, as cacheable system memory with no registration.

| 4K, same pair | lean-b (registered, IO memory) | ATS ring | first PUT of a channel (traced) |
|---|---:|---:|---|
| dispatch | 0.933 ms | 0.932 ms | 97 µs → 107 µs median; lock holder's status load 81 → 90 µs p90 |
| combine | 1.758 ms | 1.766 ms | later PUTs 15 µs in both |

Correct on every gate, no change in time, same convoy. The mapping attribute is therefore not the cause;
the first system-scope access to host memory per context costs ~90 µs when 128 contexts take it at once,
through either path. The structural fix is a command queue in GPU memory, the GDAKI/IBGDA arrangement:
the upstream Slingshot driver and libcxi added user-supplied and device-memory command queues in 2026
(`CXI_OP_CQ_ALLOC_BUF`, `cxil_alloc_buf_cmdq`), after the SHS 13.1.0 installed on Clariden.

## Combine pre-wire levers (2026-11-03 afternoon, four debug slices on three node pairs)

The 4K combine at 1.756 ms (19.2 GB/s) needs 65 µs for 20 GB/s. Its first remote PUT is emitted 0.28 ms
after the kernel starts (traced lean-b: entry barrier end 0.07–0.09 ms, first local token 0.20, first PUT
0.28), and the kernel is wire-bound from that emission on. Two DeepEP-level kernel knobs were built for
this stretch ([patches/1103/combine-levers-1103.patch](../patches/1103/combine-levers-1103.patch)):
`CXI_EP_COMBINE_FIRST_TAIL` (the scale-up warps publish their first tail after one round of the
linked-list loop instead of three) and `CXI_EP_COMBINE_SPLIT_BARRIER` (the scale-up warps wait for the
NVLink half of the entry barrier only, the forward warps for the rail half only, through a flag), combined
with the existing `CXI_EP_COMBINE_FIRST_BATCH`. All variants are exact-correct (FP8 and BF16, five
routings, two seeds, on two pairs). Wall time per iteration, slowest rank, 4K mixed FP8:

| arm (FIRST_TAIL / SPLIT_BARRIER / FIRST_BATCH) | combine ms | vs lean-b | note |
|---|---:|---:|---|
| lean-b 0/0/4 (release candidate) | 1.754–1.775 by pair | — | |
| tail1 1/0/4 | +0.3 % | nothing | first batch still needs four rows; the next tail is three rounds later |
| split 0/1/4 | +0.1 % | nothing | per-iteration kernel time spreads 1.59–1.97 ms, period unchanged |
| both 1/1/4 | −0.2 % | nothing | |
| **tail1fb2 1/0/2** | **−16 µs (−1.0 %)** on two quiet pairs (seven gates against seven); −33 / +5 µs on a noisier pair | real, small | 16K −3 and −22 µs on the two pairs |
| fb2 0/0/2 | −4 µs | nothing | the gain is the early tail made usable by the two-row batch |
| tail1fb1 1/0/1, fb1 0/0/1 | 6.70 / 6.68 ms, 4× | pathological | the 128-byte alignment cliff: a row is 8256 B = 64 mod 128, a one-row first batch starts every second batch at an odd row; same without the early tail |

Why the split barrier cannot help here: the skew the entry barrier absorbs is between the four rail pairs
(each pair has its own two NICs and its own wire end, 35–75 µs apart per iteration on the GPU global
timer), and every node holds one rank of every pair, so the node-local NVLink barrier waits for the
slowest pair exactly as the global barrier did. The traced tail1fb2 build emits its first PUT 40 µs after
the barrier instead of 194; the period moves 16 µs because the rest of it is the barrier latency and
slowest-pair wait, the slowest pair's wire phase (94–97 % of the bidirectional ceiling) and the epilogue.
Trace captures are 1.4 s apart (readout pause), so only the first captured iteration is a warm start; the
untraced repeats carry the steady-state numbers. Details: history log 11_03 §5.

## NIC ceiling measured with `cxi_write_bw`

HPE's host-side RDMA write benchmark (`cray-libcxi-utils` 1.0.2), 256 writes per doorbell, one
queue, three Clariden node pairs on 2026-11-02 (jobs 3832897, 3833183, 3833451). Scripts in
[`harness/link_rate_1102/`](../harness/link_rate_1102/), outputs and tables in
[`evidence/link-rate/`](../evidence/link-rate/).

| Per NIC, per direction | host memory | GPU memory (HBM both ends) |
|---|---:|---:|
| unidirectional, writes of 256 KB and above | 24.2 GB/s | 24.2 GB/s |
| unidirectional, DeepEP PUT sizes (69 to 132 KB) | 23.6 to 23.9 | 23.7 to 24.0 |
| bidirectional (peer writing back at the same time) | 22.3 to 22.6 | 22.4 to 22.6 |
| bidirectional, all four rails of the node busy, 132 KB | 22.1 | 22.2 |

- Port rate is 25 GB/s; packets carry 2 KB of payload (packet rate divided by write rate), so
  framing costs 3.3%. Bidirectional operation costs a further 7%. GPU memory costs nothing.
- DeepEP's rails always run both directions at once, so **22.5 GB/s per direction is the
  ceiling** for its traffic. The earlier 21.5 GB/s figure was the plateau of our own transport.
- One queue is issue-limited by the doorbell batch: 9.9 GB/s with one write per doorbell, 18 to
  21 with 8 (our transport's batch), 22.0 with 16, 24.0 with 256, for 69 to 132 KB writes.
- Odd data point: 1 MiB GPU-memory writes, bidirectional on four rails at once, drop to
  15.5 GB/s per direction (single sample; not relevant to DeepEP's 132 KB PUTs).

## Model geometries, final candidate

Mixed routing, 4K and 16K tokens per rank. FP8 rows are from the release matrix (four or more
repeats); BF16 rows are from correctness gates with fewer iterations.

| Model (hidden, experts, top-k) | dispatch dtype | 4K dispatch | 4K combine | 16K dispatch | 16K combine |
|---|---|---:|---:|---:|---:|
| V4 Flash (4096, 256, 6) | FP8 | 0.949 ms | 1.812 ms | 3.439 ms | 6.946 ms |
| V4 Flash, lean-b + kernel knobs (release matrix 3835100, wall per iteration) | FP8 | 0.932 ms | 1.758 ms | 3.411 ms | 6.877 ms |
| V4 Flash | BF16 | 1.737 ms | 1.822 ms | 6.475 ms | 6.943 ms |
| Qwen3 (4096, 128, 8) | FP8 | 0.953 ms | 1.811 ms | 3.458 ms | 6.948 ms |
| MiniMax (3072, 256, 8) | FP8 | 0.765 ms | 1.399 ms | 2.655 ms | 5.294 ms |

## Small batches

V4 Flash, FP8 dispatch, mixed routing. The fixed per-call cost dominates; even purely local routing
costs about 0.28 ms (dispatch) and 0.19 ms (combine) at these sizes.

| tokens/rank | dispatch | combine | payload bound |
|---:|---:|---:|---:|
| 32 | 0.305 ms | 0.229 ms | about 0.01 ms |
| 257 | 0.424 ms | 0.362 ms | 0.05 ms |

## Release qualification

98 gates in one allocation (job 3830101), all PASS: candidate correctness at 32, 257, 4K and 16K
tokens on five routings including dropped tokens; sustained 16K; three model geometries in FP8 and
BF16; geometry repeats; size sweeps; the first-interval and cadence sweep; two trace gates; and six
SGLang gates (scatter/gather and expert smoke on each model) through the real dispatcher.

## NIC alignment probe

Raw single-queue probe with the backend's own device primitives
([harness/pipeline_1101/offset_probe.cu](../harness/pipeline_1101/offset_probe.cu)), 256 PUTs per
case, one thread and one queue per GPU, both directions of each rail pair active, medians over 8
ranks and 3 repeats. Output: [`evidence/alignment-probe/`](../evidence/alignment-probe/).

| Row bytes | PUT rows | boundary offset (rows) | address mod 128 | GB/s | vs aligned |
|---:|---:|---:|---:|---:|---:|
| 8256 | 16 | 0, 2, 4, 6, 8 | 0 | 21.4 to 21.9 | 1.00 |
| 8256 | 16 | 1, 3, 5 | 64 | 4.9 to 5.1 | 4.3x slower |
| 8256 | 15 / 13 | 1 / 3 | 64 | 4.95 | 4.4x slower |
| 4320 | 16 | 0, 4, 8 | 0 | 12.0 to 12.1 | 1.00 (single queue issue-bound at 69 KB) |
| 4320 | 16 | 2, 6 | 64 | 5.05 to 5.13 | 2.4x slower (same 5 GB/s floor) |
| 4320 | 16 | 1, 5 / 3 | 96 / 32 | 10.8 to 11.0 | 1.1x slower |

With our GPU-issued primitives the rate depends on the PUT address modulo 128 bytes and on nothing
else that was varied. In the DeepEP kernels this showed up as a 1.9x (first interval 1) and 3.4x
(first interval 2) slowdown with correctness intact, which is why the qualified knobs keep every
PUT boundary on a multiple of four rows.

**The cliff is not a NIC property.** `cxi_write_bw` with CPU-issued commands, GPU memory on both
ends and the same PUT lengths (14, 15 and 16 rows of 4320 and 8256 bytes), with writes placed so
that their start addresses alternate between 0 and 64 bytes past a 128-byte line, runs at 23.7 to
24.0 GB/s in every case, the same as 128-byte placement (job 3833451). The slowdown is therefore
specific to our transport's GPU-issued path. Suspects, in order: the dmabuf registration of GPU
memory, the batched-delivery descriptor bits (`CT_SEND` without the flush bit), the GPU-written
command queue. The decisive follow-up is one raw-probe gate with (1) host-pinned buffers and
(2) per-PUT `CT_ACK` delivery; whichever is flat names the cause. Until then the four-row rule
stands.

## Knobs that did not help

257 contexts; combine batch 8 or 64; forward chunk 16; dispatch interval 32; interval 4 (+8 %);
interval 8 (-1.4 % at 16K, +3.3 % at 4K); combine first batch at 4K (within noise); split entry barrier
for the combine (exact, no change: the skew is between rail pairs); early scale-up tail alone (no change);
one-row first batch (4× slower: alignment cliff).
