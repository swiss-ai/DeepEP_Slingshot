# Apples-to-apples EP8: DeepEP v2 direct-CXI GIN vs UCCL-EP CPU proxy (2026-11-05)

Question (user, 2026-11-05 ~15:00 CET): CSCS users mainly run UCCL-EP's CPU-proxy path on Alps; do we have, or
can we get, an apples-to-apples comparison with our patched DeepEP v2 direct GIN over Slingshot?

## 1. What existed before this job

| Comparison | Matched? | Numbers (V4 Flash, 4096 tokens/rank, FP8 dispatch) |
|---|---|---|
| DeepEP v2 over NCCL CPU-proxy GIN (type 2) vs direct GIN (type 6) | yes: same `ep_benchmark.py`, inputs, full-call CUDA-event metric | proxy 6.60 / 6.60 ms (job 3753568, 10-26); direct now 1.01 / 1.89 ms uniform, 0.93 / 1.76 ms mixed |
| UCCL-EP native CPU proxy vs ours | one point: same uniform routing/seed and call boundaries, fresh FP8 dispatch only, tracing-disabled diagnostic builds (10-29, jobs 3790547/3790548) | UCCL 1.53 ms, direct then 3.43 ms, proxy GIN 6.60 ms; direct today 1.01 ms on the same case |
| UCCL upstream `test_internode.py` (job 3783795, swiss-ai/uccl@54ef064) | no: best transmit-kernel time over chunk settings, cached handle, notify separate | 1.17 ms dispatch, 1.80 ms BF16 combine |

Our harness's `--backend uccl` path passed at EP4 (job 3728338, uccl 27a0abb) but its only EP8 attempt (3753568)
crashed in UCCL's `cached_notify` (64 SMs exceed the dynamic shared-memory limit; upstream uses 24), and the
10-27/28 rebenchmark then hit per-case buffer teardown faults (UcclProxy and the DLPack deleter both freeing the
scratch allocation) before the user switched to upstream's own benchmark. No matched combine, cycle, Qwen3 or
MiniMax number existed.

## 2. This job: snapshot `source-1105-ucclcmp-v1`, Slurm job 3865330 (debug, 2 nodes, 40 min)

Packager `tools/cxi_gin/experiments/pipeline_1105/package_ucclcmp_1105.py`, launcher `launch_ucclcmp_1105.py`,
table `compare_ucclcmp_1105.py`. Parent `source-1103-ep8skew-v3` (transport code identical = `main` of the review
repo; runtime installed, preflight skipped). Both backends run through the same `backend/tests/ep_benchmark.py`
in the same allocation and node pair, 4096 tokens/rank, FP8 dispatch / BF16 combine, routings `uniform` (random
top-k, 4.5 destinations per token) and `mixed` (2 destinations per token), seeds 1 2 3, 20 warm-ups, 100 timed
iterations, exact correctness against the independent NCCL all-to-all reference before timing, NIC octet windows
of 600 iterations (CXI telemetry) for the first seed.

- Direct GIN: release candidate (`lean-b`, `CXI_EP_SKIP_COMBINE_FLUSH=1`, `CXI_EP_LOCAL_SELF_SIGNAL=1`, packed
  dispatch/combine knobs, 64 SMs, 129 contexts).
- UCCL-EP: Swiss AI reference build `swiss-ai/uccl@54ef064` of job 3783795 (`ep.abi3.so` dcce642b…), native CPU
  proxy over libfabric/CXI (`UCCL_EP_TRANSPORT=cxi`, dedicated NIC per GPU), 24 SMs, dispatch chunks NVL 32 / RDMA
  32, combine chunks NVL 4 / RDMA 32 (inside the flat region of upstream's own tuning sweep), buffer sizes as
  upstream's `compute_buffer_sizes`, 24 QPs per rank (upstream default). One buffer per process, as upstream's
  benchmark; no per-case destroy; `os._exit` after results are written.
- Snapshot changes vs parent (only these four files): `backend/tests/ep_benchmark.py` (UCCL path: persistent
  buffer, separate dispatch/combine configs, provenance), `runner/node.sh` (`CXI_TEST_KIND=uccl` → new
  `runner/uccl_node.sh`), `runner/validate_gate.py` (qualification `uccl_ep`, unit-tested on synthetic PASS/FAIL).

Gates: C100 deepep v4flash, C101 uccl v4flash, C102 deepep qwen3+minimax, C103 uccl qwen3, C104 uccl minimax,
C105 deepep v4flash repeat, C106 uccl v4flash repeat (expected end 28 min of 40). Metric to read:
`max_host_us_per_iteration` (wall time per iteration of the slowest rank) next to the headline
`median_rank_max_us`; `compare_ucclcmp_1105.py job-3865330/results/results --md`.

Caveats to carry into the write-up: library algorithms differ (UCCL = DeepEP-v1-style normal mode through
`get_dispatch_layout` + dispatch with CPU proxy threads; ours = DeepEP v2 hybrid kernels with GPU-issued
commands); UCCL at its upstream chunk tuning for 24 SMs, not re-tuned on this pair; host CPU core-equivalents
are reported per process (UCCL's proxy threads count, ours is ~1 core of host sync); NIC rates are window
averages including control traffic.

## 3. Execution log

- 15:23 CET: snapshot installed (`runtime/source-1105-ucclcmp-v1/{marker-zero,lean-a,lean-b}`), job 3865330
  submitted, PENDING behind the user's running boot smoke 3863691 (QOSMaxJobsPerUserLimit).
- 15:42:57–16:20:05 CET: job 3865330 ran on nid007536/007542; all seven gates PASS, every case exact on all
  eight ranks for both backends; gate durations 43–52 s (UCCL) and 73–150 s (direct, JIT included); results
  mirrored to `results/deepep_pipeline_20261101/job-3865330/`.

## 4. Results (4096 tokens per rank, FP8 dispatch / BF16 combine, EP8, one node pair, same benchmark)

Wall time per iteration of the slowest rank (ms), medians over the cases of the gates (six for V4 Flash: two gates ×
three seeds; three for Qwen3 and MiniMax). Headline = median over iterations of the per-iteration maximum across
the eight ranks. Bound = DeepEP payload bytes per rank per direction at the measured 22.5 GB/s bidirectional NIC
ceiling (one row per token: FP8 dispatch 4320 B for hidden 4096, 3264 B for 3072; BF16 combine 8256 / 6208 B).
`compare_ucclcmp_1105.py results/deepep_pipeline_20261101/job-3865330/results/results --md`.

| model | routing | operation | direct GIN | UCCL CPU proxy | UCCL / direct | bound | direct eff. | UCCL eff. | headline direct / UCCL |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| V4 Flash | mixed | dispatch | 0.933 | 1.552 | 1.66 | 0.786 | 19.0 GB/s | 11.4 GB/s | 0.936 / 1.503 |
| V4 Flash | mixed | combine | 1.762 | 2.241 | 1.27 | 1.503 | 19.2 | 15.1 | 1.821 / 1.972 |
| V4 Flash | mixed | cycle | 2.695 | 3.529 | 1.31 | | | | 2.750 / 3.447 |
| V4 Flash | uniform | dispatch | 0.964 | 1.565 | 1.62 | 0.786 | 18.4 | 11.3 | 0.969 / 1.505 |
| V4 Flash | uniform | combine | 1.876 | 2.220 | 1.18 | 1.503 | 18.0 | 15.2 | 1.941 / 1.971 |
| V4 Flash | uniform | cycle | 2.840 | 3.512 | 1.24 | | | | 2.897 / 3.446 |
| Qwen3 | mixed | dispatch | 0.936 | 1.572 | 1.68 | 0.786 | 18.9 | 11.3 | 0.940 / 1.510 |
| Qwen3 | mixed | combine | 1.756 | 2.240 | 1.28 | 1.503 | 19.3 | 15.1 | 1.816 / 1.973 |
| Qwen3 | mixed | cycle | 2.695 | 3.563 | 1.32 | | | | 2.750 / 3.457 |
| Qwen3 | uniform | dispatch | 0.994 | 1.575 | 1.58 | 0.786 | 17.8 | 11.2 | 1.001 / 1.535 |
| Qwen3 | uniform | combine | 1.920 | 2.176 | 1.13 | 1.503 | 17.6 | 15.5 | 1.983 / 1.997 |
| Qwen3 | uniform | cycle | 2.913 | 3.588 | 1.23 | | | | 2.974 / 3.500 |
| MiniMax | mixed | dispatch | 0.748 | 1.423 | 1.90 | 0.594 | 17.9 | 9.4 | 0.749 / 1.314 |
| MiniMax | mixed | combine | 1.347 | 1.892 | 1.40 | 1.130 | 18.9 | 13.4 | 1.379 / 1.630 |
| MiniMax | mixed | cycle | 2.089 | 3.039 | 1.46 | | | | 2.124 / 2.899 |
| MiniMax | uniform | dispatch | 0.788 | 1.332 | 1.69 | 0.594 | 17.0 | 10.0 | 0.791 / 1.321 |
| MiniMax | uniform | combine | 1.463 | 1.835 | 1.25 | 1.130 | 17.4 | 13.9 | 1.499 / 1.650 |
| MiniMax | uniform | cycle | 2.246 | 3.048 | 1.36 | | | | 2.284 / 2.948 |

Reading:

- **Dispatch: the direct GIN is 1.6–1.9× faster**, combine 1.1–1.4×, the dispatch+combine cycle 1.2–1.5×. UCCL's
  fresh dispatch costs 1.5–1.6 ms regardless of geometry or routing (its proxy, not the rows, sets the time; the
  10-29 matched trace point of 1.53 ms is reproduced); ours follows the bytes (0.75–0.99 ms).
- **NIC utilisation** (CXI octet counters over the 600-iteration windows, per NIC, including control traffic): direct
  GIN 18.2–20.3 GB/s on every operation; UCCL 9.3–12.0 GB/s during dispatch and 13.7–16.1 GB/s during combine.
- **UCCL's headline understates its wall time on combine** (1.97 vs 2.21–2.28 ms): its per-iteration times have a
  long tail (p95 3.8–4.6 ms, single iterations up to 7.6 ms) that the median hides; dispatch has no such tail
  (median 1.48, wall 1.49 ms). Ours: dispatch headline = wall; combine headline 3 % above wall because the
  skip-flush knob decouples the rail peers' kernel ends (known metric effect, docs/results.md).
- **Repeatability on this pair**: direct 0.930 / 0.948 ms dispatch and 1.761 / 1.764 ms combine across the two V4
  Flash gates; UCCL 1.511 / 1.579 and 2.211 / 2.283 (±4–5 %).
- **Host CPU**: 5.0 core-equivalents per rank process for UCCL (its proxy threads) vs 3.0 for ours (CUDA runtime
  and host count sync; no proxy).
- **Correctness**: identical inputs by construction (same received-row and remote-row counts per routing, e.g. 18104
  received / 4035 remote rows for V4 Flash uniform on rank 0) and identical floating-combine error (max 0.0166 abs)
  on both backends; every case exact.

Caveats: UCCL ran at upstream's 24 SMs and chunk settings (dispatch NVL 32 / RDMA 32, combine 4 / 32) taken from
its own tuning sweep of 2026-10-28 on another pair, not re-tuned here (that sweep's optimum region is flat to ~1 %);
UCCL's 24 SMs leave more SMs to compute than our 64, which matters for overlap in serving but is not measured by a
communication-only benchmark; UCCL implements the DeepEP v1 normal-mode API (layout + dispatch, CPU proxy
"high-throughput mode"), ours the DeepEP v2 hybrid kernels; UCCL's upstream transmit-only numbers (1.17 ms dispatch,
1.80 ms combine) differ from these full-call numbers by the notify kernel, layout and host count sync, which a
serving layer pays.

## 5. Files

- Snapshot and job: `results/deepep_pipeline_20261101/source-1105-ucclcmp-v1` (manifest, sequence, the four changed
  files), `results/deepep_pipeline_20261101/job-3865330/results/results/<gate>/{direct,uccl}/ep/` (summary.csv,
  repeatability.json, timings-rank*.jsonl with per-iteration CUDA events, correctness-rank*.jsonl, manifest-rank*.jsonl,
  nic-node*.jsonl), `uccl/node*/{benchmark.log,node-inventory.txt}`.
- Scripts: `tools/cxi_gin/experiments/pipeline_1105/{package,launch,compare}_ucclcmp_1105.py`.
- Review repository: `main` docs/results.md section "UCCL-EP CPU proxy, same benchmark", evidence/gates-3865330,
  harness/pipeline_1105; `debug` carries the snapshot record, the curated job and this note.
