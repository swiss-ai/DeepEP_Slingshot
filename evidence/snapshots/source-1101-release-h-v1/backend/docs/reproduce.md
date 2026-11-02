# Reproduce the private direct-CXI EP8 path

This recipe targets the existing Clariden account/container setup. It is not an
installer for arbitrary Slingshot systems. The dated root investigation log is
the authority for which stages passed. Archive verification and compilation do
not establish GPU correctness; a new prefix needs its own GIN and EP8 passes.

## Source inputs

Export from the private worktrees, with the previously verified fmt archive:

```bash
python3 tools/cxi_gin/backend/tools/package_sources.py \
  --destination results/deepep_direct_10_26/source-bundles/NEW_BUNDLE \
  --fmt-archive results/deepep_direct_10_26/source-bundles/20261027-source-stride-fix/fmt-base.tar
```

`NEW_BUNDLE` must be unused. The exporter creates pinned DeepEP and NCCL Git
archives, includes fmt, exports both patches, reconstructs their changed files
in fresh checkouts, and records backend file hashes. It never exports the dirty
worktree as the baseline archive. The fmt archive has a fixed expected SHA256.
Before deployment, from the bundle directory run:

```bash
python3 backend/tools/verify_rebuild_inputs.py .
```

The verifier checks each archive's SHA256 and Git archive commit identifier.
Keep `source-manifest.json` and `rebuild-inputs.json` with the archives. These
provide reproducibility checks within this trusted source bundle, not a digital
signature or authentication of an arbitrary downloaded archive.

| Source | Pinned commit |
|---|---|
| DeepEP | `bd1e1669a9324a4a111e3786658f1a4a43151f1e` |
| NCCL | `12df1a11afad322be5a204a2db890161cbf8131d` |
| fmt | `a4c7e17133ee9cb6a2f45545f6e974dd3c393efa` |

Transfer the new bundle to a **new** directory under
`/iopsstor/scratch/cscs/zyu/deepep-direct-20261026/tenhour/sources/`.
Verify the archive and backend hashes after transfer. Do not overwrite the
tested release, earlier source snapshots, or a source directory in a live job.

## NCCL build

On an appropriate CPU build host, use the existing extracted CUDA 13.0 SDK:

```bash
bash "$cxi_bundle/backend/tools/build_reconstructed_nccl.sh" \
  "$cxi_bundle" "$cxi_new_nccl_prefix" \
  /iopsstor/scratch/cscs/zyu/deepep-direct-20261026/cuda-sdk/usr/local/cuda-13.0
```

Set `cxi_bundle` to the transferred bundle and `cxi_new_nccl_prefix` to an
unused path before running. The script uses four compiler jobs, builds SM90,
and writes `source/`, `build/`, `logs/`, and `PASS` or `FAIL`. A successful build
is not a hardware qualification. The first reconstructed build used GCC 7.5.0
and CUDA 13.0.88; preserve the toolchain inventory for each subsequent build.

## Allocated GPU qualification

Use a bounded, explicitly submitted two-node lease; do not submit a second
competing allocation while the existing sequence is running. The site launcher
is `backend/tools/lease.sbatch`, using account `infra01`, four GPUs per node,
one launcher task per node and eight total ranks. The controller executes
explicit immutable request JSON files from its `requests/` directory. It
admits a gate only if its full timeout plus cleanup reserve fits the actual
Slurm allocation. Later stages refused for time have **not run**.

The currently deployed controller files are under `tenhour/tools/`; a new
session must use the bundled `lease_driver.py`, `validate_gate.py` and
`allocation_time.py`, copied before the new allocation starts. The controller
and launchers contain the explicit CSCS paths listed here. No container or
GPU workload should be launched directly on a login node.

Use these two ordered requests for the clean-build gate:

1. `direct_node.sh`, qualification `gin`, `CXI_TEST_KIND=smoke`,
   `CXI_SMOKE_CONTEXTS=1,129`, `CXI_SMOKE_RESET=1`,
   `CXI_NCCL_PREFIX=$cxi_new_nccl_prefix/build`,
   `CXI_NCCL_SOURCE=$cxi_new_nccl_prefix/source`. Allow 180 seconds for the
   request and 150 seconds for its test. This verifies the reconstructed NCCL
   runtime and installed device headers with the actual CXI plugin.
2. Only after the first request qualifies, run `clean_deepep_ep_node.sh`,
   qualification `ep`, with the same NCCL paths, `CXI_TEST_KIND=ep`,
   `CXI_EP_MODELS="v4flash qwen3 minimax"`, `CXI_EP_TOKENS=4096`,
   `CXI_EP_DTYPES=fp8`, `CXI_EP_ROUTING=uniform`, `CXI_EP_SEEDS=1`,
   `CXI_EP_SMS=64`, `CXI_EP_CONTEXTS=129`, `CXI_EP_WARMUP=2`,
   `CXI_EP_ITERS=5`, `CXI_EP_NIC_ITERS=0`, `CXI_EP_PROFILE_STEPS=0`,
   `CXI_EP_DEBUG=0`, `CXI_TEST_TIMEOUT=240`. Allow 900 seconds for the request;
   the per-node native build has a 600-second watchdog. Set `stop_after=true`.

JSON environment values must be literal strings with resolved absolute paths;
the controller does not expand `$variables`. Each request needs `snapshot`,
`node_script`, `timeout_seconds`, `qualification`, `environment`, `requires`
and `stop_after`. A concrete example is retained in
`results/deepep_direct_10_26/tenhour/followup-20261027-1120/sequence.json`,
requests 13 and 14. Their dependencies belong to that longer sequence: when
using only these two gates, replace the first dependency list with `[]` and
the second with the actual first request name. Do not edit a live request.

The clean DeepEP node script reconstructs the pinned source and fmt, builds
its native extension inside the allocated container, checks the loaded
extension path, and then tests that build on all four local GPUs. It uses
the isolated NCCL Python overlay as well as `LD_PRELOAD`; both are needed to
prevent PyTorch from loading a second NCCL. Runtime checks stay enabled.

## Runtime and interpretation

Existing EDF: `/iopsstor/scratch/cscs/zyu/deepep-v2-20261022/tools/deepep-v2-cxi.toml`.
Runtime setup: the adjacent `runtime_cxi.sh`, Python 3.12/CUDA 13.0 environment.
Image: `lmsysorg+sglang+v0.5.13-cu130.aarch64.sqsh` in the user's EDF image store.
These are external site dependencies, not contained in the source bundle.

| Evidence | Qualified scope |
|---|---|
| Job 3765839, `nid006249,nid006255` | GH200 120 GB, driver 595.91.07, kernel `6.4.0-150600.23.125-64kb`, host libcxi 1.7.0; actual inventories retained |
| Private GIN type 6 | Direct GPU CXI command posting/completion, no host network-progress callback; host setup/launch/synchronization remain |
| Standalone EP8 | Three recorded communication geometries, 4096/GPU, matched FP8 dispatch/BF16 combine tests |
| SGLang | Opt-in normal-mode adapter; functional dispatcher/scatter/gather and reduced-width real expert tests; warmed timing qualification still pending |
| Clean source reconstruction/NCCL build | Passed separately; full clean native DeepEP build plus GPU rerun still pending |

Inspect each `FINISHED.json`, its qualification, all eight rank records, both
node `PASS` files and loaded-library/node inventories. Slurm `COMPLETED` alone
is insufficient. Preserve `rebuild-node*/build-import.json`, build logs and
binary hashes. A source or header change requires a new prefix and fresh JIT
cache: pinned DeepEP does not hash external NCCL header contents directly.

This two-gate rebuild procedure is a correctness gate. Performance requires
the separate matched three-seed, ten-warmup, fifty-sample sequence and NIC
counter windows. Synthetic communication results are not full-model TTFT.
GET/Engram, general serving lifecycle, LL/AUTO/overlap/EPLB and transparent
fault recovery remain outside the qualified implementation.
