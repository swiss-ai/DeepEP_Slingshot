# Patches

All DeepEP patches are against `bd1e1669a9324a4a111e3786658f1a4a43151f1e`; the NCCL patch is against
`12df1a11afad322be5a204a2db890161cbf8131d` (v2.32.3-1). `scripts/apply_patches.sh` applies a profile
and installs the backend headers; every file below was checked on 2026-11-05 to apply to a pristine
checkout and, where a snapshot tarball exists, to reproduce that snapshot's DeepEP tree byte for byte.

## NCCL

| File | Content |
|---|---|
| `nccl-12df1a11-cxi-integration.patch` | 7 files, 35 lines: registers `NCCL_NET_DEVICE_GIN_CXI = 6`, includes `cxi/gin_cxi.cuh` behind `NCCL_GIN_CXI_ENABLE`, installs `include/nccl_device/gin/cxi/*.h` and `*.cuh`. |
| `nccl-cxi-new-headers.json` | SHA-256 of the six backend headers that go into `src/include/nccl_device/gin/cxi/` (`cassini_user_defs.h`, `cxi_gin_abi.h`, `cxi_primitives.cuh`, `cxi_queue_credit.h`, `cxi_fence_command.h`, `gin_cxi.cuh`), as in `backend/` on this branch. |

## DeepEP, cumulative profiles

| File | Profile | Reproduces | Status |
|---|---|---|---|
| `deepep-bd1e1669-cxi-full.patch` | **full** (default): qualified + lean signal path + double-buffered combine staging + combine pre-wire levers; 7 files, +366/−42; every knob default off, selected through `CXI_EP_*` environment variables at JIT time | `DeepEP.tar.gz` of `source-1103-combine-v1` … `source-1103-ep8skew-v3` | the tree of every job since 2026-11-03 afternoon (combine rounds, EP8 real-routing demo); with the release knobs it reproduces the release-matrix numbers (jobs 3843956, 3844086) |
| `deepep-trace-hooks-full.patch` | trace hooks on top of **full** (11 files; device and host events for attribution, not for timing) | `DeepEP-trace.tar.gz` of `source-1103-ep8skew-v3` | diagnostic builds only |
| `deepep-bd1e1669-cxi-qualified.patch` + `1102/lean-signal-deepep-1102.patch` | **release**: the exact tree of the release matrix | `DeepEP.tar.gz` of `source-1102-lean-v1` (job 3835100, 45 gates PASS) | release candidate |
| `deepep-bd1e1669-cxi-qualified.patch` | **qualified**: the 2026-11-01 release (barrier on NCCL's bounded `waitSignal`, runtime guard, packed dispatch rows, packed combine, final-tail merge) | `DeepEP.tar.gz` of `source-1101-first-batch-v1` (job 3830101, 98 gates PASS) | 2026-11-01 candidate |
| `deepep-trace-hooks.patch` | trace hooks on top of **qualified** | `DeepEP-trace.tar.gz` of `source-1101-first-batch-v1` | diagnostic builds only; does not apply on top of the lean patch (use the `-full` one) |
| `deepep-bd1e166-portable-signal-wait.patch` | the barrier part of the qualified patch alone (GIN barrier through `ncclGin::waitSignal` instead of peeking GDAKI's signal table) | — | subset, kept for upstream discussion |

## Incremental patches (history of the knob-guarded additions)

Each is the diff of one experiment round against its parent snapshot; `backend/` on this branch
already contains all backend-side hunks that are part of the current code, and `-full.patch`
contains all DeepEP-side hunks. They are kept so a reviewer can see each change in isolation.

| File | Parent | Content | Result |
|---|---|---|---|
| `1102/lean-signal-backend-1102.patch` | first-batch-v1 | transport variants `lean-a` / `lean-b` (`CXI_LEAN_FENCE`, `CXI_LEAN_CSTATE`, `CXI_LEAN_FOLD_MARKER`; `CxiGpuContext::lean_state`), knob plumbing in `nvcc_wrapper.py` / `ep_benchmark.py`, `variants.json`, preflight | in `backend/`; lean-b is the release transport |
| `1102/lean-signal-deepep-1102.patch` | first-batch-v1 | `CXI_EP_SKIP_COMBINE_FLUSH`, `CXI_EP_LOCAL_SELF_SIGNAL` | in `-full`; both = 1 in the release candidate |
| `1102/double-tma-deepep-1102.patch` | lean-v1 | `CXI_EP_COMBINE_DOUBLE_TMA` (second smem staging buffer per scale-up warp) | in `backend/` and `-full`; neutral, off |
| `1102/credit-cache-backend-1102.patch` | dbuf-v1 | `CXI_CREDIT_CACHE` cached TX read pointer (ABI 4, variants `cache-a` / `lean-c`) | **not** in `backend/`: correct through the ladders, 99.9 % fewer status reads, no time change |
| `1102/prewarm-contexts-1102.patch` | dbuf-v1 | `CXI_EP_PREWARM_CONTEXTS` (touch every context's ring in the GIN barrier) | **not** in `backend/` or `-full`: correct, no effect; its wrapper hunks predate the combine-lever hunks and no longer apply directly |
| `1102/trace-validator-knobs-1102.patch` | — | harness trace validator follows the skip-flush / self-signal knobs | in `harness/runner-trace/validate_trace.py` |
| `1103/ring-diagnostic-ats-1103.patch` | dbuf-v1 (host code) | `CXI_MAP` / `CXI_GPU_ADDRESSING` diagnostics, `CXI_RING_ACCESS=ats` | in `backend/` (the snapshot's `cxi_resources.cc` carries a few more diagnostic lines than this diff) |
| `1103/dispatch-start-stagger-1103.patch` | ringdiag-v1 | `CXI_EP_STAGGER_NS` dispatch channel start stagger (diagnosis only) | **not** in `-full`: wall time unchanged |
| `1103/combine-levers-1103.patch` | ringdiag-v1 (after double-TMA) | `CXI_EP_COMBINE_FIRST_TAIL`, `CXI_EP_COMBINE_SPLIT_BARRIER` | in `-full`; tail 1 + first batch 2 = −16 µs at 4K, split barrier no gain |

Not included anywhere: the padded 128-byte row stride of the EP8 demo (`source-1103-pad128-v1`), which
faults at 4096 tokens per rank (see docs/limitations.md), and the raw NIC probes, which live in
`harness/pipeline_1101/offset_probe.cu` and `harness/runner/burst_probe.cu`.
