# Build and run

How to build the direct-CXI backend with its NCCL and DeepEP, run the transport tests, the EP8
benchmark and the SGLang smoke, and read the results. Everything that touches a GPU or the NIC runs
inside a Clariden Slurm allocation (two GH200 nodes, four GPUs each) in the pinned container; the
NCCL build can run on any CPU host with a CUDA 13.0 toolkit. Commands are those of the qualification
scripts (`backend/tools/direct_node.sh`, `harness/runner/node.sh`) with their site paths made
explicit; the helper scripts under `scripts/` were run on 2026-11-05 against pristine checkouts and
reproduce the snapshot trees byte for byte, but they have not themselves been through a GPU job.

## 1. Pinned inputs

| Input | Version | Where from |
|---|---|---|
| NCCL | `12df1a11afad322be5a204a2db890161cbf8131d` (v2.32.3-1) | `git clone https://github.com/NVIDIA/nccl` |
| DeepEP v2 | `bd1e1669a9324a4a111e3786658f1a4a43151f1e` with `third-party/fmt` at `a4c7e17133ee9cb6a2f45545f6e974dd3c393efa` | `git clone https://github.com/deepseek-ai/DeepEP` |
| Container | `lmsysorg/sglang:v0.5.13-cu130` (CUDA 13.0, Python 3.12, torch, SGLang, DeepGEMM) | [site/clariden/deepep-v2-cxi.toml](../site/clariden/deepep-v2-cxi.toml) |
| libcxi | the node's `cray-libcxi` (SHS 13.1.0, `libcxi.so.1.5.0`), visible in the container as `/host_usr/lib64/libcxi.so` and `/host_usr/include` | EDF mount `/usr:/host_usr:ro` |
| CUDA | `/usr/local/cuda` inside the container; a CUDA 13.0 toolkit extracted onto scratch for login-node compiles | site |
| Backend headers | the six files under `backend/include` and `backend/device` (hashes in [patches/nccl-cxi-new-headers.json](../patches/nccl-cxi-new-headers.json)) | this repository |

The harness's own route is a hashed source bundle (`backend/tools/package_sources.py`,
`verify_rebuild_inputs.py`, `build_reconstructed_nccl.sh`, `build_reconstructed_deepep.sh`;
[backend/docs/reproduce.md](../backend/docs/reproduce.md)). The git route below is equivalent and
was checked against the bundles' tarballs.

## 2. Patch NCCL and DeepEP

```bash
git clone https://github.com/NVIDIA/nccl && git -C nccl checkout 12df1a11afad322be5a204a2db890161cbf8131d
git clone https://github.com/deepseek-ai/DeepEP && git -C DeepEP checkout bd1e1669a9324a4a111e3786658f1a4a43151f1e
git -C DeepEP submodule update --init third-party/fmt
scripts/apply_patches.sh --check nccl DeepEP                    # verify only
scripts/apply_patches.sh --variant lean-b nccl DeepEP           # apply (profile full, release transport)
```

`apply_patches.sh` applies `patches/nccl-12df1a11-cxi-integration.patch` (type 6 registration,
header installation), the DeepEP patch of the chosen profile, and copies the six backend headers into
`nccl/src/include/nccl_device/gin/cxi/`, where NCCL's Makefile installs them next to its own device
headers.

| `--profile` | DeepEP tree | Use |
|---|---|---|
| `full` (default) | every change; all extra knobs off until selected by environment variables | current code; with `scripts/release_env.sh` it is the release candidate |
| `release` | qualified + lean signal path, nothing later | the exact tree of release-matrix job 3835100 |
| `qualified` | the 2026-11-01 release | historical comparison |

`--trace` adds the device/host trace hooks (attribution builds; not for timing). `--variant NAME`
prepends the transport variant's `#define`s from [backend/variants.json](../backend/variants.json)
to the installed `cxi_primitives.cuh`, so DeepEP's JIT and the GIN tests compile that variant:

| Variant | Defines beyond the common set (`CXI_HW_SIGNAL_FENCE`, `CXI_BATCH_DELIVERY`, `CXI_ZERO_DELIVERY_MARKER`, `CXI_CT_THRESHOLD_FLUSH` = 1, `CXI_TX_BATCH_LIMIT` = 8) | Status |
|---|---|---|
| `marker-zero` | none | 2026-11-01 candidate |
| `lean-a` | `CXI_LEAN_FENCE`, `CXI_LEAN_CSTATE` | passed the ladders, 0.1–0.5 % behind lean-b |
| `lean-b` | `CXI_LEAN_FENCE`, `CXI_LEAN_CSTATE`, `CXI_LEAN_FOLD_MARKER` | **release** |

Without `--variant` the header's own defaults apply (`CXI_BATCH_DELIVERY=1`, `CXI_HW_SIGNAL_FENCE=1`,
`CXI_TX_BATCH_LIMIT=8`, everything else 0), which is none of the qualified variants: always pick one.
To build several variants from one NCCL build, use `scripts/make_variant_runtime.py --nccl-build
<prefix> --out <dir> lean-b marker-zero`, which copies the build and bakes one variant per
sub-directory the way the harness does; point `EP_NCCL_ROOT_DIR` at the variant directory. The host
plugin does not depend on the variant.

## 3. Build NCCL

On a host with the CUDA 13.0 toolkit (GCC 7.5 to 14 have been used):

```bash
make -C nccl/src -j4 src.build CUDA_HOME="$CUDA_HOME" BUILDDIR="$PWD/nccl-build" \
  NVCC_GENCODE='-gencode=arch=compute_90,code=sm_90'
ls nccl-build/lib/libnccl.so.2.32.3 nccl-build/include/nccl_device/gin/cxi/   # six headers + SHA256SUMS
```

`nccl-build` is the `EP_NCCL_ROOT_DIR` of everything below. Keep one build per header change: the
pinned DeepEP does not hash external header contents into its JIT key.

## 4. Build the plugin (inside the container)

```bash
srun -N1 --environment=site/clariden/deepep-v2-cxi.toml \
  scripts/build_plugin.sh "$PWD/nccl-build" "$PWD/nccl" "$PWD/plugin/libnccl-gin-cxi.so"
```

This is the `g++ -std=c++17 -fPIC -shared -Wall -Wextra -Werror ...` line of `direct_node.sh`: the
three host sources against the backend headers, the built NCCL's public headers, the NCCL source's
plugin-internal headers, CUDA, and `/host_usr/lib64/libcxi.so`. The harness recompiles it on every
node at the start of each gate (a few seconds) and records its hash.

## 5. Build DeepEP (inside the container, on an allocated node)

```bash
export EP_NCCL_ROOT_DIR=$PWD/nccl-build CUDA_HOME=/usr/local/cuda
export EP_NVSHMEM_ROOT_DIR=/usr/local/lib/python3.12/dist-packages/nvidia/nvshmem
export LD_PRELOAD="$EP_NCCL_ROOT_DIR/lib/libnccl.so.2"
export LD_LIBRARY_PATH="$EP_NCCL_ROOT_DIR/lib:$EP_NVSHMEM_ROOT_DIR/lib:${LD_LIBRARY_PATH:-}"
export LIBRARY_PATH="$EP_NCCL_ROOT_DIR/lib:${LIBRARY_PATH:-}"     # setup.py links -l:libnccl.so without -L
export MAX_JOBS=4 TORCH_CUDA_ARCH_LIST=9.0 EP_SUPPRESS_NCCL_CHECK=0
# one NCCL runtime only: PyTorch preloads nvidia/nccl/lib/libnccl.so.2 from the Python path, so put
# an overlay pointing at our build in front of it (LD_PRELOAD alone is not enough)
mkdir -p overlay/nvidia/nccl/lib && ln -sf "$EP_NCCL_ROOT_DIR/lib/libnccl.so.2.32.3" overlay/nvidia/nccl/lib/libnccl.so.2
export PYTHONPATH="$PWD/overlay:$PWD/DeepEP"
(cd DeepEP && python setup.py build_ext --inplace)
python -c 'import deep_ep, deep_ep._C; print(deep_ep._C.__file__)'   # must be inside DeepEP/
```

The kernels themselves are JIT-compiled at first use through `backend/tests/nvcc_wrapper.py`
(`EP_JIT_NVCC_COMPILER`), which injects the `CXI_EP_*` defines and keeps the ptxas register/spill
reports under `$EP_JIT_CACHE_DIR/compiler-reports/`. Keep the DeepEP directory a git checkout (the
benchmark records its commit) or set `DEEPEP_WORK` to a directory holding a `source-manifest.json`
as the harness bundles do.

## 6. Run

Per node, in the container, with `MASTER_ADDR` = first node of the allocation (`scontrol show
hostnames "$SLURM_JOB_NODELIST" | head -n1`) and a free `MASTER_PORT`:

```bash
export NCCL_GIN_PLUGIN=$PWD/plugin/libnccl-gin-cxi.so EP_NCCL_ROOT_DIR=$PWD/nccl-build
export LD_LIBRARY_PATH="$EP_NCCL_ROOT_DIR/lib:$LD_LIBRARY_PATH" LD_PRELOAD="$EP_NCCL_ROOT_DIR/lib/libnccl.so.2"
export PYTHONPATH="$PWD/overlay:$PWD/backend/tests:$PWD/DeepEP" DEEPEP_SOURCE=$PWD/DeepEP
export EP_JIT_CACHE_DIR=$PWD/jit/$SLURM_JOB_ID/node$SLURM_PROCID      # fresh per knob set
source scripts/release_env.sh      # NCCL_GIN_TYPE=6, Ring, bootstrap over hsn0, the release knobs
export NCCL_DEBUG=INFO             # optional; the plugin logs CXI_MAP / CXI_GPU_ADDRESSING lines
run() { python -m torch.distributed.run --nnodes=2 --nproc_per_node=4 --node_rank="$SLURM_PROCID" \
          --master_addr="$MASTER_ADDR" --master_port="$MASTER_PORT" "$@"; }
```

`release_env.sh` sets `NCCL_GIN_TYPE=6`, `NCCL_GIN_NCONNECTIONS=1`, `NCCL_ALGO=Ring`,
`CXI_GIN_BOOTSTRAP_IFNAME=hsn0`, `EP_SUPPRESS_NCCL_CHECK=0`, `EP_JIT_NVCC_COMPILER`, and the knobs
of §7. Plugin and `EP_NCCL_ROOT_DIR` must come from the same NCCL build; the plugin refuses a second
NCCL runtime in the process.

### 6.1 Transport tests

```bash
nvcc -std=c++17 -shared -Xcompiler=-fPIC -arch=sm_90 -I"$EP_NCCL_ROOT_DIR/include" \
  backend/tests/gin_smoke.cu -L"$EP_NCCL_ROOT_DIR/lib" -lnccl -ldl -o out/gin_smoke.so
export SMOKE_SO=$PWD/out/gin_smoke.so CASE_OUT=$PWD/out/smoke
CXI_TEST_KIND=smoke CXI_SMOKE_CONTEXTS=1,129 CXI_SMOKE_RESET=1 run backend/tests/gin_smoke.py
```

| `CXI_TEST_KIND` | Source | Checks |
|---|---|---|
| `smoke` | `gin_smoke.cu` | put / put-value / signal / counter / flush across all eight ranks, optional reset, self-signal and delayed peer; `CXI_SMOKE_CONTEXTS` (default `1,4`), `CXI_SMOKE_ROUNDS` (14) |
| `producer` | `gin_producer_stress.cu` | same-warp and multi-CTA producers sharing one context; `CXI_PRODUCER_BLOCKS` (`1,2,8`), `CXI_PRODUCER_ROUNDS` (128) |
| `bad_offset` | `gin_bad_offset.cu` | an out-of-window PUT must terminate with diagnostic code 11 (expected failure) |
| `bounds` | `gin_bounds.cu` | five bounds and peer rejections on isolated guard state, no NIC command posted |

Each writes `CASE_OUT/rank*.json` with the per-case results; the rank exits non-zero on any failure.

### 6.2 EP8 benchmark with exact reference

```bash
run backend/tests/ep_benchmark.py --backend deepep --output out/ep \
  --models v4flash --tokens 4096 16384 --dtypes fp8 --routing mixed --seeds 1 \
  --warmup 20 --iters 100 --nic-iters 0 --profile-steps 0
```

Every case first runs one dispatch and combine and compares the received payload, FP8 scales,
routing ids, weights and padded counts, and the combined output, against an independent NCCL
all-to-all reference (`backend/tests/common.py`); the rank aborts on the first mismatch. Timing
follows: fresh dispatch (primary), cached dispatch (diagnostic), combine, and the dispatch+combine
cycle, with CUDA events per rank and the host wall time of the timed loop.

| Option / variable | Values |
|---|---|
| `--models` | `v4flash` (hidden 4096, 256 experts, top-k 6), `qwen3` (4096, 128, 8), `minimax` (3072, 256, 8) |
| `--tokens` | tokens per rank; 32, 257, 4096 and 16384 are qualified; the SGLang adapter's capacity is 4096 |
| `--dtypes` | `fp8` (FP8 dispatch, BF16 combine) or `bf16` (both BF16) |
| `--routing` | `uniform` (random top-k, 4.5 destination ranks per token), `mixed` (2 destinations per token, one per node), `local`, `remote`, `skew1.2` / `skew1.6` / `skew2` / `skew4` (receiver skew), `hot_rank`, `bank_f<forward>_l<layer>_<vanilla|greedy|random>` (exact per-expert counts of a real OpenSWE 4K unit, V4 Flash at 4096 tokens only; bank subset in `backend/tests/`) |
| `--sms`, `CXI_EP_SMS` | SMs for the hybrid kernels (64 qualified; 32 and 128 are slower) |
| `CXI_EP_CONTEXTS` | NIC contexts (queues) per rank, 129 qualified (257 slower) |
| `CXI_EP_DROP_EVERY` | drop every n-th token's routing (0 = off); used by the dropped-token correctness gates |
| `CXI_EP_DEBUG` | 1 makes the pinned DeepEP print on every call; use 0 for timing |
| `--nic-iters` | extra untimed iterations for NIC counter windows (0 unless telemetry is collected) |

Output under `--output`: `summary.csv` (one row per case and operation: `median_rank_max_us`,
`p95_rank_max_us`, `mean_rank_max_us`, `max_host_us_per_iteration`, host CPU core equivalents),
`repeatability.json` (median of the headline over cases), `timings-rank<r>.jsonl` (per-rank
per-iteration samples with the full knob set, the routing's traffic statistics and, for bank
routings, the bank record), `correctness-rank<r>.jsonl` and `manifest-rank<r>.jsonl` (source and
library hashes, loaded paths).

### 6.3 SGLang dispatcher smoke

The adapter `backend/sglang/deepep_v2_cxi.py` replaces SGLang's normal-mode DeepEP dispatcher
implementation with one built on DeepEP v2's `ElasticBuffer` when `SGLANG_CXI_DEEPEP_V2=1`. It is
installed into an isolated copy of the container's SGLang package, never into the image:

```bash
python backend/tools/prepare_sglang_overlay.py --destination out/sglang-overlay/sglang \
  --adapter backend/sglang/deepep_v2_cxi.py          # --source defaults to the image's /sgl-workspace/sglang/python/sglang
export PYTHONPATH="$PWD/out/sglang-overlay:$PYTHONPATH" SGLANG_CXI_DEEPEP_V2=1
export SGLANG_ENABLE_JIT_DEEPGEMM=1 SGLANG_JIT_DEEPGEMM_PRECOMPILE=0 SGLANG_DG_CACHE_DIR=$PWD/out/deepgemm/node$SLURM_PROCID
export SGLANG_CXI_DEEPEP_V2_SMS=64 SGLANG_CXI_DEEPEP_V2_CONTEXTS=129 SGLANG_CXI_DEEPEP_V2_MAX_TOKENS=4096
export CASE_OUT=$PWD/out/sglang DEEPEP_WORK=$PWD    # DEEPEP_WORK: provenance directory, see §5
CXI_SGLANG_MODEL=v4flash CXI_SGLANG_DTYPES=fp8,bf16 CXI_SGLANG_TOKENS=32,4096 CXI_SGLANG_ROUNDS=3 \
CXI_SGLANG_EXACT_REFERENCE=1 run backend/tests/sglang_dispatcher_smoke.py
```

The smoke drives SGLang's real `DeepEPDispatcher.dispatch` / `combine` on eight ranks with fresh
4096-token routings and checks payload, scales, ids and weights exactly (`CXI_SGLANG_EXACT_REFERENCE=1`);
`CXI_SGLANG_GEMM=1` additionally runs the actual DeepGEMM expert path with a reduced FFN width and a
numerical reference, `CXI_SGLANG_PERMUTE=1` the real scatter/gather. `CXI_SGLANG_MODEL` is `toy`
(2048, 64, 4) by default or one of the three geometries. Normal mode only, synchronous, group size 8
with a (2, 4) domain; LL/AUTO, overlap, CUDA-graph decode and EPLB recording are rejected
([backend/docs/sglang_integration.md](../backend/docs/sglang_integration.md)).

### 6.4 The node script

`backend/tools/direct_node.sh` is what the harness runs per node and does all of §4 and §6 in one
go: node inventory, plugin compile, test selection by `CXI_TEST_KIND` (`smoke`, `producer`,
`bad_offset`, `bounds`, `ep`, `sglang`), the overlay, local JIT and log handling, and a `PASS` file.
It expects `SNAPSHOT` (a directory holding `backend/`, so the repository root works), `OUT`,
`SLURM_PROCID`, `MASTER_ADDR`, `MASTER_PORT`, `CXI_NCCL_PREFIX` (= `EP_NCCL_ROOT_DIR`),
`CXI_NCCL_SOURCE` (the patched NCCL tree), `CXI_DEEPEP_SOURCE` (the built DeepEP) and the `CXI_EP_*`
variables of a gate (`evidence/gates-*/<gate>/FINISHED.json` carries complete examples). Two lines
are site constants to adapt before use: the `source .../runtime_cxi.sh` line (the container Python
environment, [site/clariden/](../site/clariden/)) and the `root=` default for the NCCL paths. Launch
with one task per node:

```bash
srun --nodes=2 --ntasks-per-node=1 --gpus-per-node=4 --kill-on-bad-exit=1 \
  --environment=site/clariden/deepep-v2-cxi.toml bash backend/tools/direct_node.sh
```

## 7. Knobs

All `CXI_EP_*` values are compile-time defines of the DeepEP kernels, injected by
`backend/tests/nvcc_wrapper.py` at JIT time. DeepEP's JIT cache key does not see them: **use a fresh
`EP_JIT_CACHE_DIR` whenever one changes.** `release_env.sh` sets the "release" column.

| Variable | Default | Release | Meaning |
|---|---:|---:|---|
| `CXI_EP_PACK_ROWS` | 0 | 1 | dispatch: stage a channel's remote rows contiguously and ship one PUT per interval instead of one per token |
| `CXI_EP_UPDATE_INTERVAL` | 3 | 16 | dispatch: rows per PUT / progress notification |
| `CXI_EP_FIRST_INTERVAL` | = interval | 4 | dispatch: rows in the first PUT of a channel (must be a multiple of 4, see §9) |
| `CXI_EP_FORWARD_CHUNK` | = interval | 3 | dispatch: rows per NVLink forward chunk |
| `CXI_EP_MERGE_FINAL_TAIL` | 0 | 1 | dispatch: the last rows ride with the finish signal |
| `CXI_EP_PACK_COMBINE` | 0 | 1 | combine: channel-major receive layout, one PUT per batch of remote rows |
| `CXI_EP_COMBINE_BATCH` | 16 | 16 | combine: rows per PUT |
| `CXI_EP_COMBINE_FIRST_BATCH` | = batch | 4 | combine: rows in a channel's first PUT (never 1: 4× slower; 2 only with the early tail) |
| `CXI_EP_SKIP_COMBINE_FLUSH` | 0 | 1 | combine: no GPU-side flush before the end signal; ordering stays with the NIC's marker and fence |
| `CXI_EP_LOCAL_SELF_SIGNAL` | 0 | 1 | GIN barrier: no NIC round trip for the rank's own arrival |
| `CXI_EP_COMBINE_FIRST_TAIL` | 0 | 0 | combine: scale-up warps publish their first tail after this many rounds (0 = regular 3); 1 with first batch 2 is exact and −16 µs at 4K, not release-qualified |
| `CXI_EP_COMBINE_SPLIT_BARRIER` | 0 | 0 | combine: split entry barrier; exact, no gain |
| `CXI_EP_COMBINE_DOUBLE_TMA` | 0 | 0 | combine: second staging buffer per scale-up warp; neutral |
| `CXI_EP_SMS`, `CXI_EP_CONTEXTS` | 64, 129 | 64, 129 | kernel SMs (4 channels per SM), NIC contexts per rank |
| `CXI_RING_ACCESS` (host, plugin) | `register` | `register` | `ats`: the kernel addresses the command rings through the host page tables instead of a `cudaHostRegister` mapping; correct, same speed, diagnostic |
| `CXI_VARIANT` | — | `lean-b` | label recorded in results; the variant itself is baked into the installed header (§2) |

## 8. Reading results

- `median_rank_max_us` (the harness headline) is the median over iterations of the per-iteration
  maximum across the eight ranks. `max_host_us_per_iteration` is the slowest rank's host wall time of
  the timed loop divided by the iteration count: the throughput a serving loop sees. With
  `CXI_EP_SKIP_COMBINE_FLUSH=1` the ranks' kernel ends decouple and the headline reads 1–4 % above
  the wall time for the same gates; the results tables quote the wall time for everything after
  2026-11-01.
- Effective rate = payload bytes per rank per direction / wall time (V4 Flash: 4320 B per FP8
  dispatch row, 8256 B per BF16 combine row, one row per token). The bound is the same bytes at the
  NIC's measured bidirectional ceiling of 22.5 GB/s per rail ([docs/results.md](results.md)).
- `harness/pipeline_1102/effective_rate.py RESULTS_DIR 'regex' --ref ARM --wall` prints per-arm
  medians and effective rates for a directory of gates; `harness/pipeline_1101/summarize_arms.py`
  does the headline. Both read the gate layout under `evidence/gates-*/`.
- A correctness failure aborts the rank with a message naming the tensor; a transport timeout traps
  the kernel, the plugin reports the diagnostic code and terminates the process group with exit 86.

## 9. Rules and pitfalls

- **One NCCL runtime.** The plugin and `EP_NCCL_ROOT_DIR` must be the same build; the Python overlay
  (§5) is required because PyTorch preloads its own `libnccl.so.2`. `deep_ep` refuses to load with a
  second runtime (`EP_SUPPRESS_NCCL_CHECK=0`).
- **Fresh JIT cache per knob set** (§7). The `compiler-reports` in the cache record the defines used.
- **PUT boundaries on multiples of four rows.** With the GPU-issued path a PUT whose address is 64
  bytes off a 128-byte line runs at a quarter of link rate; DeepEP rows are 32·odd bytes, so
  `CXI_EP_FIRST_INTERVAL`, `CXI_EP_UPDATE_INTERVAL` and the combine batches must be multiples of 4
  (2 only as a first batch together with the early tail). Never set `CXI_EP_COMBINE_FIRST_BATCH=1`.
- **Service identifiers** come from the allocation (`SLINGSHOT_DEVICES`, `SLINGSHOT_SVC_IDS`,
  `SLINGSHOT_VNIS`); never reuse another job's.
- **Fail-fast only.** No recovery after a timeout or teardown failure; relaunch the process group.
- **Container details.** `/dev/shm` is `noexec` (Triton cache → the container's `/tmp`); the
  bootstrap uses `hsn0`; the debug partition caps a job at 25 minutes and the per-knob JIT rebuild
  of the 24 kernel templates takes a few minutes per node, so size `CXI_TEST_TIMEOUT` accordingly.
- **Receive capacity.** A destination at 32768 received rows (the EP8 real-routing stress corner)
  degraded the transport for the rest of that job; keep token capacity and routing within the
  qualified envelope ([limitations.md](limitations.md)).

## 10. Full qualification

The harness ([harness/README.md](../harness/README.md)) packages the backend, the DeepEP archives
and a `sequence.json` of gates into an immutable snapshot with a hashed manifest, installs one NCCL
runtime per variant (`harness/runner/install.py`), compile-checks on the login node
(`preflight.sh`), submits `run.sbatch` and lets `controller.py` run the gates serially inside the
allocation, exact correctness first. A release matrix is the ladder of
`evidence/snapshots/source-1102-lean-v1/sequence.json`: irregular stress at 32 and 257 tokens on
five routings, 4K FP8 and BF16 correctness, dropped tokens, sustained 16K, then three
counterbalanced timing repeats per arm. Any new transport or kernel change goes through that ladder
before its timing is read.
