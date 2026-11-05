# DeepEP v2 direct GIN over Slingshot

GPU-initiated transport for DeepEP v2 expert-parallel dispatch and combine on HPE Slingshot
(Cassini) NICs. The GPU kernels write NIC commands and ring doorbells themselves; the CPU does
setup only. Implemented as a private NCCL GIN backend (type 6) plus patches to NCCL and DeepEP,
developed and qualified on Clariden GH200 nodes at EP8 (two nodes, four GPUs each).

**Status (2026-11-05): experimental; correct and release-qualified within the envelope in
[docs/limitations.md](docs/limitations.md).** Not a supported transport. This branch holds
everything needed to build, run and check the current code; the complete campaign record (every
snapshot, gate record and device trace) is on the `debug` branch.

## Current results

V4 Flash geometry (hidden 4096, 256 experts, top-k 6), EP8, FP8 dispatch and BF16 combine, mixed
routing, 64 SMs, 129 contexts. Times are the wall time per iteration of the slowest rank (what a
serving loop sees), medians over the nine repeat gates of the release matrix (job 3835100, 45 gates
PASS, 2026-11-03; records in [evidence/gates-3835100/](evidence/gates-3835100/)). The bound is
payload serialisation at the NIC's measured bidirectional ceiling of 22.5 GB/s per rail.

| tokens/rank | operation | release candidate | effective rate | bound | ratio | 2026-11-01 candidate |
|---:|---|---:|---:|---:|---:|---:|
| 4096 | dispatch | 0.932 ms | 19.0 GB/s | 0.786 ms | 1.19 | 0.944 ms |
| 4096 | combine | 1.758 ms | 19.2 GB/s | 1.503 ms | 1.17 | 1.801 ms |
| 16384 | dispatch | 3.411 ms | 20.8 GB/s | 3.146 ms | 1.08 | 3.423 ms |
| 16384 | combine | 6.877 ms | 19.7 GB/s | 6.013 ms | 1.14 | 6.929 ms |

The release candidate is the `lean-b` transport variant with the kernel knobs
`CXI_EP_SKIP_COMBINE_FLUSH=1` and `CXI_EP_LOCAL_SELF_SIGNAL=1` on top of the packed dispatch and
combine paths ([scripts/release_env.sh](scripts/release_env.sh) sets all of it). Every number is
exact against an independent NCCL all-to-all reference checked before timing.

Other results, each detailed in [docs/results.md](docs/results.md):

- **Other geometries** (2026-11-01 candidate, 98-gate matrix, job 3830101): Qwen3 (4096, 128, 8)
  0.953 / 1.811 ms at 4K; MiniMax (3072, 256, 8) 0.765 / 1.399 ms; V4 Flash BF16 dispatch 1.737 ms.
  Six SGLang gates through the real dispatcher PASS. The release candidate's matrix is V4 Flash only.
- **Small batches**: 32 tokens/rank 0.305 / 0.229 ms, 257 tokens/rank 0.424 / 0.362 ms. The fixed
  per-call cost (entry barrier, notify exchange, signal tails, epilogue kernels) dominates.
- **Real routing** (OpenSWE per-expert counts, 72 cases exact): +5 % dispatch and +9 % combine over
  synthetic mixed routing at equal NIC bytes; combine follows the hottest destination's rows beyond
  about 1.3× the mean (+33 % at 4× receiver skew), dispatch stays NIC-bound.
- **Experimental**: the early scale-up tail with a two-row first batch
  (`CXI_EP_COMBINE_FIRST_TAIL=1`, `CXI_EP_COMBINE_FIRST_BATCH=2`) is exact and 16 µs faster at 4K
  combine on three node pairs; it has no release matrix yet. A one-row first batch is 4× slower
  (128-byte alignment cliff) and must not be used.
- **Where the rest goes**: dispatch pays a 0.11 ms entry barrier, a ~100 µs first-PUT convoy (the
  first access per kernel to each context's host-mapped command ring when 128 contexts start at
  once; shown to be off the critical path) and the copy epilogue; combine pays 0.28 ms before its
  first remote PUT and then runs the slowest rail pair's wire at 94–97 % of the ceiling. Every
  zero-code lever (SM count, context count, cadence, batch sizes, cached credits, prewarm, ATS ring
  access, split barrier) is closed; the structural fix is a command queue in GPU memory, which the
  installed Slingshot host software (SHS 13.1.0) does not offer.

## Repository layout

| Path | Content |
|---|---|
| [backend/](backend/) | The transport: host plugin, device primitives, GIN device API, SGLang adapter, tests and tools. Byte-identical to the latest qualified snapshot (`source-1103-ep8skew-v3`) except for its README and the added `variants.json`. Start with [backend/README.md](backend/README.md) and [backend/docs/operation_contract.md](backend/docs/operation_contract.md). |
| [patches/](patches/) | NCCL `12df1a11` integration patch, the DeepEP `bd1e1669` patches (full, release and qualified profiles, trace hooks) and the dated incremental patches; [patches/README.md](patches/README.md) gives the lineage. |
| [scripts/](scripts/) | `apply_patches.sh` (patch NCCL and DeepEP, install the headers, bake a transport variant), `build_plugin.sh`, `make_variant_runtime.py`, `release_env.sh`. |
| [docs/](docs/) | [usage.md](docs/usage.md) (build and run), [design.md](docs/design.md), [results.md](docs/results.md), [limitations.md](docs/limitations.md), and the dated engineering logs under [docs/history/](docs/history/). |
| [harness/](harness/) | Qualification harness: the Slurm controller and node scripts ([harness/runner/](harness/runner/)), snapshot packagers, gate definitions and analysis scripts. |
| [site/clariden/](site/clariden/) | The container environment file and runtime scripts the harness uses on Clariden. |
| [evidence/](evidence/) | Snapshot manifests with per-file hashes, curated verdicts and medians of every gate quoted in the results, the NIC link-rate measurement and the raw alignment probe ([evidence/README.md](evidence/README.md)). |

## Quick start

Everything runs inside a Clariden Slurm allocation (two GH200 nodes, four GPUs each) in the pinned
container; the full procedure with all commands is [docs/usage.md](docs/usage.md).

```bash
git clone https://github.com/NVIDIA/nccl && git -C nccl checkout 12df1a11
git clone https://github.com/deepseek-ai/DeepEP && git -C DeepEP checkout bd1e1669 && git -C DeepEP submodule update --init third-party/fmt
scripts/apply_patches.sh --variant lean-b nccl DeepEP          # patches + headers; --check to only verify
make -C nccl/src -j4 src.build CUDA_HOME=$CUDA_HOME BUILDDIR=$PWD/nccl-build NVCC_GENCODE='-gencode=arch=compute_90,code=sm_90'
scripts/build_plugin.sh nccl-build nccl plugin/libnccl-gin-cxi.so  # inside the container (needs /host_usr libcxi)
# build DeepEP against nccl-build (docs/usage.md §5), then per node:
export NCCL_GIN_PLUGIN=$PWD/plugin/libnccl-gin-cxi.so EP_NCCL_ROOT_DIR=$PWD/nccl-build
source scripts/release_env.sh
python -m torch.distributed.run --nnodes=2 --nproc_per_node=4 --node_rank=$SLURM_PROCID \
  --master_addr=$MASTER_ADDR --master_port=$MASTER_PORT backend/tests/ep_benchmark.py \
  --backend deepep --output out/ep --models v4flash --tokens 4096 --dtypes fp8 --routing mixed --seeds 1 --warmup 20 --iters 100 --nic-iters 0
```

Correctness is checked on every case before any timing; `out/ep/summary.csv` holds the per-case
medians (`max_host_us_per_iteration` is the wall time per iteration quoted above).

## Third-party notices

`backend/include/cassini_user_defs.h` is HPE's generated Cassini header (GPL-2.0-only OR
BSD-2-Clause), vendored unchanged. DeepEP (MIT) is included as patches and, for the 2026-11-01
snapshots, as the exact tarball under `evidence/snapshots/`, with the pinned `fmt` submodule (MIT).
NCCL (BSD-3-Clause) is included as a patch only. SGLang (Apache-2.0) is not included; the adapter
in `backend/sglang/` is applied to the container's copy at run time.
