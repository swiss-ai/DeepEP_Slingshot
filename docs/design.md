# Design

**Code on this branch.** `backend/` is the backend of the latest hardware snapshot
(`source-1103-ep8skew-v3`, 2026-11-03): the 2026-11-01 qualified transport plus the lean signal path
(as compile-time variant defines, selected through `backend/variants.json`), ring-mapping diagnostics
and the `CXI_RING_ACCESS=ats` host knob, and the EP8 benchmark's real-routing support. The DeepEP side
is `patches/deepep-bd1e1669-cxi-full.patch`: the qualified changes plus every later knob
(`CXI_EP_SKIP_COMBINE_FLUSH`, `CXI_EP_LOCAL_SELF_SIGNAL`, `CXI_EP_COMBINE_DOUBLE_TMA`,
`CXI_EP_COMBINE_FIRST_TAIL`, `CXI_EP_COMBINE_SPLIT_BARRIER`), all default off and injected at JIT
time by `backend/tests/nvcc_wrapper.py`. The release candidate is this code with the `lean-b` variant
and the knob values in `scripts/release_env.sh`. Experiments that did not help (cached credits,
prewarm, start stagger, padded row stride) stay out of the code and are kept as patches or logs.

## Transport: private NCCL GIN backend, type 6

The backend lives in [`backend/`](../backend/). NCCL's GIN (GPU-initiated networking) device API
is implemented on raw libcxi resources instead of libfabric.

**Host side** ([host/gin_plugin.cc](../backend/host/gin_plugin.cc),
[host/cxi_resources.cc](../backend/host/cxi_resources.cc),
[host/cxi_bootstrap.cc](../backend/host/cxi_bootstrap.cc)). A NCCL GIN v14 plugin
("CXI-Direct-Experimental") that uses the Slurm-assigned CXI service and VNI, allocates a libcxi
LNI, communication profiles and one event queue, and per registered window a domain plus a
portals-table entry mapped at offset zero (so remote offsets are window-relative). GPU memory is
registered through dmabuf. Each of the 129 contexts per rank owns a TX command queue, a trigger
command queue and a counting event; queues, doorbells, counter write-back and a diagnostic page are
mapped into the GPU. A setup-only TCP bootstrap over `hsn0` exchanges peer descriptors.
`needsProxyProgress=0`: no progress callback exists. Channels are pooled and recycled across
device-context lifetimes; teardown is checked and a failure terminates the rank (exit 86) rather
than freeing memory the NIC may still address.

**Device side** ([device/cxi_primitives.cuh](../backend/device/cxi_primitives.cuh),
[device/gin_cxi.cuh](../backend/device/gin_cxi.cuh)). One lock per context serialises producers.
`emit` writes a 64-byte command into the ring after checking credits against the NIC-updated
read pointer, and publishes with one doorbell per up to eight commands. Payload uses full DMA PUTs
in chunks of at most 1 MiB with bounds checks. Completion is a counting event: payload PUTs count
`CT_SEND`, and one zero-byte delivery marker per epoch (same window, same peer) with the flush bit
and `CT_ACK` closes the epoch. A flush requests counter write-back with `C_CMD_CT_TRIG_EVENT`
whose threshold is the posted count. Signals are 64-bit SUM atomics (CSTATE plus IDC atomic),
preceded by the delivery marker and a native `C_CMD_CQ_FENCE`, so the GPU never waits on
write-back in the signal path. Every wait is bounded and records a diagnostic code that the host can
read after a trap. The `ncclGinApi_*` specialisations cover Put, PutValue, Flush, FlushAsync and
Wait, indexed and VA signals, counters and resets; Get traps.

**NCCL integration** ([patches/nccl-12df1a11-cxi-integration.patch](../patches/nccl-12df1a11-cxi-integration.patch)):
seven files, 35 lines, registering `NCCL_NET_DEVICE_GIN_CXI = 6`, dispatching the device API to the
new headers and exporting them.

## DeepEP changes

Seven files against `bd1e1669`, +208/-26
([patches/deepep-bd1e1669-cxi-qualified.patch](../patches/deepep-bd1e1669-cxi-qualified.patch)).

- **Barrier and runtime guard.** The GIN barrier uses NCCL's bounded `waitSignal` instead of
  peeking GDAKI's signal table; the Python package refuses to load with a second NCCL runtime.
- **Packed remote rows in hybrid dispatch** (`CXI_EP_PACK_ROWS`). Each channel's rows destined to
  the remote node are staged contiguously in the send buffer and shipped as one PUT per
  notification interval instead of one PUT per token. Knobs: `CXI_EP_UPDATE_INTERVAL` (16, upstream
  3), `CXI_EP_FIRST_INTERVAL` (4, so the first PUT leaves early), `CXI_EP_FORWARD_CHUNK` (3),
  `CXI_EP_MERGE_FINAL_TAIL` (1, the last rows ride with the finish signal).
- **Packed combine** (`CXI_EP_PACK_COMBINE`). A channel-major receive layout so consecutive
  remote-origin rows of a channel land contiguously; the forward warp batches them into one PUT
  (`CXI_EP_COMBINE_BATCH` 16, `CXI_EP_COMBINE_FIRST_BATCH` 4); the reduce epilogue reads the
  channel-major slot.
- **Trace build** ([patches/deepep-trace-hooks.patch](../patches/deepep-trace-hooks.patch)):
  device and host events used only for attribution.
- **Signal-path knobs (2026-11-02, [patches/1102/](../patches/1102/))**: `CXI_EP_SKIP_COMBINE_FLUSH`
  (no GPU-side flush before the combine end signal; ordering stays with the NIC's marker + fence),
  `CXI_EP_LOCAL_SELF_SIGNAL` (the GIN barrier skips its own rank), `CXI_EP_COMBINE_DOUBLE_TMA`
  (second staging buffer per scale-up warp), and the transport variants `lean-a` / `lean-b`
  (`CXI_LEAN_FENCE`, `CXI_LEAN_CSTATE`, `CXI_LEAN_FOLD_MARKER`; state in `CxiGpuContext::lean_state`,
  ABI size unchanged). All default off; measured in [results.md](results.md).
- **Evening additions (2026-11-02)**: cached TX-queue credits (`CXI_CREDIT_CACHE`, variants `cache-a`
  / `lean-c`, ABI 4 with `tx_rp32_cache`; `emit` re-reads the NIC status only when the conservative
  free count runs short), and `CXI_EP_PREWARM_CONTEXTS` (every grid thread touches one context's ring
  during the GIN entry barrier). Both default off; both are correct through the ladders and neither is
  faster ([results.md](results.md)).
- **2026-11-03 additions**: ring mapping diagnostics in the host plugin (`CXI_MAP`, `CXI_GPU_ADDRESSING`,
  map/fallback counts in the pool report) and `CXI_RING_ACCESS=ats`, which skips `cudaHostRegister` for
  the command rings and lets the kernel use their host virtual addresses through the GPU's host-page-table
  translation (honoured only when the device reports it). The default stays the registered path; the ATS
  path is correct and equally fast, which is how the IO-memory mapping was ruled out as the convoy's cause.
  `CXI_EP_STAGGER_NS` (DeepEP side, default 0) staggers the dispatch channels' start for the convoy
  diagnosis and is not a production knob ([patches/1103/](../patches/1103/)). Afternoon, combine side
  (`combine-levers-1103.patch`): `CXI_EP_COMBINE_FIRST_TAIL` (rounds before the scale-up warps' first tail
  publication, 0 = the regular three) and `CXI_EP_COMBINE_SPLIT_BARRIER` (scale-up warps wait on the NVLink
  phase word only, forward warps on a module-level flag set after the rail barrier, no closing grid sync;
  exact, no gain in a topology where every node holds one rank of every rail pair, default 0). The early
  tail with `CXI_EP_COMBINE_FIRST_BATCH=2` is exact and 16 µs faster at 4K; a one-row first batch hits the
  alignment cliff (a combine row is 8256 bytes) and must not be used.

The `CXI_EP_*` knobs are compile-time defines injected at JIT time by
[backend/tests/nvcc_wrapper.py](../backend/tests/nvcc_wrapper.py) and are not part of DeepEP's
JIT cache key. The transport variants (`CXI_LEAN_*`, `CXI_BATCH_DELIVERY`, `CXI_HW_SIGNAL_FENCE`,
`CXI_ZERO_DELIVERY_MARKER`, `CXI_CT_THRESHOLD_FLUSH`, `CXI_TX_BATCH_LIMIT`) are defines prepended to
the `cxi_primitives.cuh` installed with NCCL, one runtime prefix per variant
([backend/variants.json](../backend/variants.json), `scripts/apply_patches.sh --variant`,
`scripts/make_variant_runtime.py`); the host plugin is variant-independent.

## Why the packed paths matter on this NIC

Two measured properties of the Cassini path drove the design:

1. A single GPU thread needs 4 to 10 µs per 64-byte command (CQ status read over the chip link
   plus system fences). Per-token PUTs therefore cannot reach link rate; 16-row PUTs from 256
   channels on 129 queues can.
2. With our GPU-issued primitives the transfer rate depends on the PUT address modulo 128 bytes:
   64 bytes off a line runs at about 5 GB/s, 32 or 96 bytes off at about 11 GB/s, aligned at link
   rate. DeepEP's rows are 32·odd bytes (FP8 4320, BF16 8288, combine 8256), so PUT boundaries
   must fall on multiples of four rows. The qualified knobs satisfy this. HPE's `cxi_write_bw`
   does not show the effect with CPU-issued commands from GPU memory, so the cause is in our
   transport path and is under investigation (see [results.md](results.md)).

See [results.md](results.md) for the measurements and [limitations.md](limitations.md) for what
follows from these choices.
