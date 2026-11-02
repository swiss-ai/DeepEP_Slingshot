# DeepEP v2 direct GIN over Slingshot

GPU-initiated transport for DeepEP v2 expert-parallel dispatch and combine on HPE Slingshot
(Cassini) NICs. GPU kernels write NIC commands and ring doorbells themselves; the CPU does setup
only. Implemented as a private NCCL GIN backend (type 6) plus small patches to NCCL and DeepEP,
developed and qualified on Clariden GH200 nodes (EP8: two nodes, four GPUs each).

**Status: experimental.** Correct and release-qualified within the envelope in
[docs/limitations.md](docs/limitations.md). Not a supported transport.

## Results

V4 Flash geometry (hidden 4096, 256 experts, top-k 6), EP8, FP8 dispatch and BF16 combine, mixed
routing, medians of three repeats. Bound is payload serialisation at the NIC's measured
bidirectional ceiling of 22.5 GB/s per rail (HPE `cxi_write_bw`, GPU memory both ends).

| Operation | time | bound | ratio |
|---|---:|---:|---:|
| 4K tokens/rank dispatch | 0.949 ms | 0.786 ms | 1.21 |
| 4K tokens/rank combine | 1.814 ms | 1.503 ms | 1.21 |
| 16K tokens/rank dispatch | 3.439 ms | 3.146 ms | 1.09 |
| 16K tokens/rank combine | 6.946 ms | 6.013 ms | 1.16 |

Incremental bytes move at 21.5 GB/s (dispatch) and 19.8 GB/s (combine), 4 to 12% under the NIC
ceiling; the rest is a fixed per-call cost of 0.12 to 0.15 ms. The signal-path round of 2026-11-02
(no combine flush, no barrier self-signal, lean transport; [patches/1102/](patches/1102/)) takes the
4K wall time per iteration to 0.934 ms dispatch and 1.759 ms combine (18.9 / 19.2 GB/s effective) on
two node pairs, release matrix pending. Full tables, other model geometries, small batches, the NIC
ceiling measurement, the alignment probe and the metric caveat of that round:
[docs/results.md](docs/results.md).

## Repository layout

| Path | Content |
|---|---|
| [backend/](backend/) | The transport: host plugin, device primitives, GIN device API, SGLang adapter, tests and tools. Start with its [README](backend/README.md) and [docs/operation_contract.md](backend/docs/operation_contract.md). |
| [patches/](patches/) | DeepEP (`bd1e1669`) and NCCL (`12df1a11`, v2.32.3-1) patches, plus the trace-hook patch. |
| [harness/](harness/) | Qualification harness: snapshot packaging, Slurm controller, gate definitions, analysis scripts. |
| [docs/](docs/) | [design.md](docs/design.md), [results.md](docs/results.md), [limitations.md](docs/limitations.md), and the dated engineering logs under [docs/history/](docs/history/). |
| [evidence/](evidence/) | The qualified source snapshot with hashed manifest, verdicts and medians of the 98 release gates, and the raw alignment probe output. |

The complete campaign record (all snapshots, every gate's exact-check records, device traces,
earlier campaigns) is on the **`debug`** branch, which is also the working branch for further
development. `main` carries only what a user or reviewer needs.

## Build and run

Requirements: a Clariden Slurm allocation (it supplies the CXI service and VNI), the pinned
container with CUDA 13 and the installed libcxi, NCCL 2.32.3-1 source at `12df1a11` with
[patches/nccl-12df1a11-cxi-integration.patch](patches/nccl-12df1a11-cxi-integration.patch)
applied and the four backend headers installed, DeepEP at `bd1e1669` with
[patches/deepep-bd1e1669-cxi-qualified.patch](patches/deepep-bd1e1669-cxi-qualified.patch).

1. Build the plugin and reconstructed NCCL and DeepEP: `backend/tools/build_cxi.sh`,
   `build_reconstructed_nccl.sh`, `build_reconstructed_deepep.sh` (see
   [backend/docs/reproduce.md](backend/docs/reproduce.md)).
2. Select the backend at runtime: `NCCL_GIN_TYPE=6`, `NCCL_GIN_PLUGIN=<absolute plugin path>`,
   `NCCL_GIN_NCONNECTIONS=1`, `NCCL_ALGO=Ring`, exactly one NCCL runtime loaded.
3. Compile-time kernel knobs are injected at DeepEP JIT time through `backend/tests/nvcc_wrapper.py`
   (`EP_JIT_NVCC_COMPILER`). Qualified values: `CXI_EP_PACK_ROWS=1 CXI_EP_UPDATE_INTERVAL=16
   CXI_EP_FIRST_INTERVAL=4 CXI_EP_FORWARD_CHUNK=3 CXI_EP_MERGE_FINAL_TAIL=1 CXI_EP_PACK_COMBINE=1
   CXI_EP_COMBINE_BATCH=16 CXI_EP_COMBINE_FIRST_BATCH=4`, with 64 SMs and 129 contexts. Use a fresh
   `EP_JIT_CACHE_DIR` whenever a knob changes; the knobs are not part of DeepEP's cache key.
4. Run a gate: `backend/tools/direct_node.sh` with `CXI_TEST_KIND=ep` (standalone dispatch/combine
   with exact correctness checks) or `CXI_TEST_KIND=sglang` (real SGLang dispatcher, normal mode).
   The `harness/` pipeline wraps this in immutable snapshots and a serial controller.

## Third-party notices

`backend/include/cassini_user_defs.h` is HPE's generated Cassini header (GPL-2.0-only OR
BSD-2-Clause), vendored unchanged. DeepEP (MIT) is included as a patch and as the exact tarball in
the snapshot, with the pinned `fmt` submodule (MIT). NCCL (BSD-3-Clause) is included as a patch only.
