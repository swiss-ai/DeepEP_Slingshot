# Results

All numbers: EP8 on two Clariden GH200 nodes, 64 SMs, 129 contexts, exact correctness verified
against an independent NCCL all-to-all before timing, medians of repeats. Raw per-gate medians are
in [`evidence/gates-3830101/<gate>/direct/ep/repeatability.json`](../evidence/gates-3830101/);
verdicts and environments in each gate's `FINISHED.json`.

## Progress over the campaign

V4 Flash (hidden 4096, 256 experts, top-k 6), FP8 dispatch, BF16 combine, mixed routing.

| Operation | 10/30 start | 10/31 | final (11/02) | bound at 21.5 GB/s | final / bound |
|---|---:|---:|---:|---:|---:|
| 4K tokens/rank dispatch | 3.399 ms | 1.075 ms | 0.949 ms | 0.823 ms | 1.15 |
| 4K tokens/rank combine | 4.387 ms | 3.439 ms | 1.814 ms | 1.573 ms | 1.15 |
| 16K tokens/rank dispatch | 10.46 ms | 3.498 ms | 3.439 ms | 3.292 ms | 1.04 |
| 16K tokens/rank combine | not run | 13.30 ms | 6.946 ms | 6.291 ms | 1.10 |

Size-sweep fits (2K to 16K tokens): dispatch 0.147 ms + bytes / 21.5 GB/s, combine
0.121 ms + bytes / 19.8 GB/s. Incremental bytes move at link rate; what remains is a fixed per-call
cost (cross-rank entry barrier about 0.11 ms, notify exchange, signal tails).

## Model geometries, final candidate

Mixed routing, 4K and 16K tokens per rank. FP8 rows are from the release matrix (four or more
repeats); BF16 rows are from correctness gates with fewer iterations.

| Model (hidden, experts, top-k) | dispatch dtype | 4K dispatch | 4K combine | 16K dispatch | 16K combine |
|---|---|---:|---:|---:|---:|
| V4 Flash (4096, 256, 6) | FP8 | 0.949 ms | 1.812 ms | 3.439 ms | 6.946 ms |
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

The rate depends on the PUT address modulo 128 bytes and on nothing else that was varied. In the
DeepEP kernels this showed up as a 1.9x (first interval 1) and 3.4x (first interval 2) slowdown with
correctness intact, which is why the qualified knobs keep every PUT boundary on a multiple of four
rows.

## Knobs that did not help

257 contexts; combine batch 8 or 64; forward chunk 16; dispatch interval 32; interval 4 (+8 %);
interval 8 (-1.4 % at 16K, +3.3 % at 4K); combine first batch at 4K (within noise).
