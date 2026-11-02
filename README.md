# DeepEP v2 direct GIN over Slingshot

Experimental GPU-initiated transport that lets the pinned DeepEP v2 hybrid dispatch and combine
kernels drive HPE Slingshot (Cassini) NICs directly from the GPU on Clariden GH200 nodes, with no
CPU proxy progress. It is implemented as a private NCCL GIN backend (type 6) plus small patches to
NCCL and DeepEP, and is qualified on one node pair (EP8: two nodes, four GPUs each).

This repository is a curated copy of the working tree used for the campaign, kept in the same
relative layout so that every path cited in the dated logs under `*_DeepEP_v2_Slingshot.md`
resolves here. It is published for review by CSCS colleagues; the open questions are about NIC
and driver behaviour, listed at the end.

**Status: experimental, not a supported transport.** Correct within the qualified envelope below.
Anything outside it (more than two nodes, decode-style low-latency serving, overlap, fault
recovery) is not qualified and in several cases not implemented.

## Headline results

V4 Flash geometry on EP8, FP8 dispatch and BF16 combine, mixed routing, medians of three
counterbalanced repeats. The bound is pure payload serialisation at the measured 21.5 GB/s per rail
(4320 B per dispatched token, 8256 B per combined token).

| Operation | 10/30 start | 10/31 | final (11/02) | bound | final / bound |
|---|---:|---:|---:|---:|---:|
| 4K tokens/rank dispatch | 3.399 ms | 1.075 ms | 0.949 ms | 0.823 ms | 1.15 |
| 4K tokens/rank combine | 4.387 ms | 3.439 ms | 1.814 ms | 1.573 ms | 1.15 |
| 16K tokens/rank dispatch | 10.46 ms | 3.498 ms | 3.439 ms | 3.292 ms | 1.04 |
| 16K tokens/rank combine | (not run) | 13.30 ms | 6.946 ms | 6.291 ms | 1.10 |

Size-sweep fits: dispatch 0.147 ms + bytes / 21.5 GB/s, combine 0.121 ms + bytes / 19.8 GB/s.
The remaining cost is per call (entry barrier, notify exchange, signal tails), not per byte.
The full history, including the intermediate 11/02 02:00 candidate, is in
[11_01_DeepEP_v2_Slingshot.md](11_01_DeepEP_v2_Slingshot.md) ("Results so far").

## What was changed

### Transport: private NCCL GIN backend, type 6 ([tools/cxi_gin/backend](tools/cxi_gin/backend))

- **Host plugin** ([host/gin_plugin.cc](tools/cxi_gin/backend/host/gin_plugin.cc),
  [host/cxi_resources.cc](tools/cxi_gin/backend/host/cxi_resources.cc),
  [host/cxi_bootstrap.cc](tools/cxi_gin/backend/host/cxi_bootstrap.cc)): NCCL GIN v14 plugin
  "CXI-Direct-Experimental". Uses the Slurm-assigned CXI service and VNI, allocates libcxi LNI,
  communication profiles, one event queue, one domain plus PTE per registered window (offset-zero
  mapping, dmabuf registration), and per context a TX command queue, a trigger command queue and a
  counting event. Command queues, doorbells, CT write-back and diagnostics are mapped into the GPU.
  129 contexts per rank. A setup-only TCP bootstrap over `hsn0` exchanges peer descriptors;
  `needsProxyProgress=0`, no progress callback. Channels are pooled and recycled; teardown is
  checked and a failure terminates the rank (exit 86) instead of freeing memory the NIC may still
  touch.
- **Device primitives** ([device/cxi_primitives.cuh](tools/cxi_gin/backend/device/cxi_primitives.cuh)):
  GPU-issued full DMA PUTs (bounds-checked, 1 MiB chunks), inline PutValue, CSTATE plus 64-bit SUM
  atomics for signals, completion by counting events with `C_CMD_CT_TRIG_EVENT` threshold
  write-back, credit arithmetic matching libcxi, per-context lock, batched doorbells (8 commands),
  batched delivery (CT_SEND per payload plus one zero-byte delivery marker with the flush bit per
  epoch), and a native `C_CMD_CQ_FENCE` before every signal so the GPU never waits on write-back
  in the signal path. Every wait is bounded and records a diagnostic code.
- **GIN device API** ([device/gin_cxi.cuh](tools/cxi_gin/backend/device/gin_cxi.cuh)):
  `ncclGinApi_*` specialisations for Put, PutValue, Flush, FlushAsync/Wait, indexed and VA
  signals, counters and resets. Get traps (Engram is outside the EP subset).
- **NCCL 2.32.3 integration**
  ([patches/nccl-12df1a11-cxi-integration.patch](tools/cxi_gin/patches/nccl-12df1a11-cxi-integration.patch),
  seven files, 35 lines): registers backend type 6, dispatches the device API to the new headers,
  exports them. The four new headers are the backend's own files; their hashes are in
  [patches/nccl-cxi-new-headers.json](tools/cxi_gin/patches/nccl-cxi-new-headers.json).

### DeepEP changes (pinned `bd1e1669`, seven files, +208/-26)

Full diff: [patches/deepep-bd1e1669-cxi-qualified.patch](tools/cxi_gin/patches/deepep-bd1e1669-cxi-qualified.patch).
The exact qualified tree is `DeepEP.tar.gz` in the final snapshot (hash in its manifest).

- **Backend-independent barrier wait and runtime guard**: the GIN barrier uses NCCL's bounded
  `waitSignal` instead of peeking GDAKI's signal table; `deep_ep/__init__.py` refuses to load with
  a second NCCL runtime present.
- **Hybrid dispatch, packed remote rows** (`CXI_EP_PACK_ROWS`): rows destined to the remote node are
  staged contiguously per channel in the send buffer and shipped as one PUT per notification
  interval instead of one PUT per token. Knobs: regular interval 16 (`CXI_EP_UPDATE_INTERVAL`,
  upstream 3), first interval 4 (`CXI_EP_FIRST_INTERVAL`), forward chunk 3 (`CXI_EP_FORWARD_CHUNK`),
  final tail merged into the last payload PUT (`CXI_EP_MERGE_FINAL_TAIL`).
- **Hybrid combine, packed batches** (`CXI_EP_PACK_COMBINE`): a channel-major receive layout
  (`packed_combine_slot`) so consecutive remote-origin rows of a channel land contiguously; the
  forward warp batches them into one PUT (batch 16, first batch 4, `CXI_EP_COMBINE_BATCH`,
  `CXI_EP_COMBINE_FIRST_BATCH`); the reduce epilogue reads the channel-major slot.
- **Trace build** ([patches/deepep-trace-hooks.patch](tools/cxi_gin/patches/deepep-trace-hooks.patch)):
  device and host events (100-141 kernel roles, 200-214 transport) used for attribution; never used
  for performance numbers.

The knobs are compile-time defines injected at JIT time by the harness's nvcc wrapper. They are not
part of DeepEP's JIT cache key, so a persistent cache must be cleared when they change.

### Harness and qualification ([tools/cxi_gin/experiments](tools/cxi_gin/experiments))

- Immutable source snapshots with hashed manifests (`package*.py`), a Slurm controller that runs
  gates serially inside one allocation (`pipeline_v1/runner`), exact-correctness checks of payload,
  FP8 scales, routing IDs and weights against an independent NCCL all-to-all before any timing,
  three counterbalanced repeats, node-local JIT, logs and results.
- Release matrix: three model geometries (V4 Flash, Qwen3, MiniMax), FP8 and BF16, 32 to 16K
  tokens per rank, five routings including dropped tokens, sustained 16K, geometry repeats, size
  sweeps, and six SGLang gates through the real dispatcher
  ([backend/sglang/deepep_v2_cxi.py](tools/cxi_gin/backend/sglang/deepep_v2_cxi.py)).
- Raw NIC probes on the same device primitives: queue wrap and source reuse (`burst_probe.cu`),
  concurrent producers, bounds rejection, and the PUT offset/length probe
  ([pipeline_1101/offset_probe.cu](tools/cxi_gin/experiments/pipeline_1101/offset_probe.cu)).
- Analysis tools: `summarize_arms.py`, `fit_size_sweep.py`, `trace_timeline.py` in `pipeline_1101`.

## Repository layout

| Path | Content |
|---|---|
| `10_26 ... 11_01_DeepEP_v2_Slingshot.md` | Dated engineering logs, oldest first. Read 11_01 first (final state, closing summary), then 10_30 (transport design and qualification ladder). |
| `tools/cxi_gin/backend/` | The qualified backend. Byte-identical to `results/deepep_pipeline_20261101/source-1101-first-batch-v1/backend`. Its [README](tools/cxi_gin/backend/README.md), [docs/operation_contract.md](tools/cxi_gin/backend/docs/operation_contract.md) and [docs/reproduce.md](tools/cxi_gin/backend/docs/reproduce.md) describe build, runtime requirements and the test kinds. |
| `tools/cxi_gin/patches/` | DeepEP and NCCL patches against the pinned upstream commits; the trace-hook patch. |
| `tools/cxi_gin/experiments/` | Harness and analysis scripts (`pipeline_v1`, `pipeline_1101`, earlier `async_*`, `cq_credit_v1`, `size_sweep`, `trace_v1`). |
| `tools/cxi_gin/README.md` and bring-up files | The October bring-up notes (raw libcxi probes that preceded the backend). |
| `results/deepep_pipeline_20261101/` | The 11/01 campaign: full snapshots of the qualified chain (`first-batch-v1` GPU archive, `release-h-v1` release harness, `offset-probe-v1`, `trace-g-v1`), manifests and sequences of the other snapshots, launch and preflight logs, and per-gate evidence. |
| `results/deepep_pipeline_20261030/` and the `async`, `size_sweep`, `direct_10_26` campaigns | Log-free curated evidence of the campaigns cited by the 10/30 document. |

Per gate the evidence is `STARTED.json`, `FINISHED.json` (request, environment, qualification
verdict), `direct/ep/repeatability.json` and `summary.csv` (medians), `correctness-rank*.jsonl`
(exact-check records), SGLang `direct/smoke/` outputs, the raw probe logs under
`9000-offset-probe-run1/offset/`, and the device traces of the two trace gates
(`8700-trace-both4-4k`, `8701-trace-cand-4k`) that the 11/01 document analyses.

**Omitted** from the workspace copy: per-rank stderr logs, `timings-rank*.jsonl` (68 MB), JIT caches
and compiler reports, the `8702` trace gate, the NCCL and DeepEP source trees (patches suffice),
installed-header reference copies, the SGLang image file copies (hashes kept in
`tools/cxi_gin/sglang-reference/SHA256SUMS`), the upstream CLIC_SwissAI tree, and the pre-GIN
bring-up artifacts the 10/26 document cites (`ep8_threepath_trace`, `deepep_direct_10_26` traces,
`tools/ep8_*`). All are available on request. Local absolute paths (`/home/yu/...`) in launch logs
and manifests are left as recorded.

## Qualified envelope and known limitations

- Exactly two scale-out nodes with four NVLink GPUs each (static asserts in the packed paths; the
  delivery-marker epoch logic flushes the whole context on every peer or window change).
- SGLang normal mode only, synchronous, one live dispatch at a time, token capacity fixed at
  buffer creation (default 4096 per rank), BF16 combine input, EPLB recorder disabled. Low-latency
  and AUTO modes, two-batch overlap and CUDA-graph decode are not available.
- Fixed per-call cost of about 0.3 to 0.4 ms per operation at 32 to 257 tokens per rank; decode-
  style serving would need a different kernel.
- Any transport timeout traps the kernel and the plugin terminates the process group. No recovery.
- Performance cliff: PUT addresses 64 bytes off a 128-byte line transfer at about 5 GB/s, 32 or
  96 bytes off at about 11 GB/s. The candidate avoids it by construction (first interval 4,
  interval 16, batch boundaries on even rows); a real router can break a channel's run at an odd
  row. Padding the row stride to a multiple of 128 bytes removes the constraint.
- Qualified on one node pair, one driver and firmware state; the raw probes must be repeated on a
  materially different configuration before any wider claim.

## Questions for CSCS review

1. **CQ fence semantics.** Signals are ordered after payload by a zero-byte PUT with the flush bit
   followed by `C_CMD_CQ_FENCE`, with no GPU-observed completion. Does the fence guarantee that all
   prior commands on the queue have completed (acknowledged), not merely been issued, so that
   source buffers may be reused once the peer observes the signal?
2. **128-byte alignment.** The raw probe
   ([11_01 log, 05:30 entry](11_01_DeepEP_v2_Slingshot.md)) shows transfer rate depending on the
   PUT address modulo 128 bytes. Is this a known Cassini or GH200 PCIe/C2C read behaviour, and is it
   firmware or driver dependent?
3. **Counting-event write-back.** `C_CMD_CT_TRIG_EVENT` with threshold equal to the posted count is
   used as the completion flush. Is one outstanding trigger per context the intended usage, and is
   the 48-bit count semantics as assumed in `flush_locked`?
4. **GPU mapping of command queues and doorbells** (`cudaHostRegister` with IO-memory flags) from
   an unprivileged job: supported configuration or an accident of the current node image?
5. **Per-command issue cost.** About 4 to 10 µs per 64-byte command from one GPU thread (CQ status
   read over C2C plus system fences). An earlier read-pointer cache stalled under sustained load
   and was quarantined (10/30 log, gate 521). Any guidance on safe credit caching from the GPU?

## Third-party notices

- `tools/cxi_gin/backend/include/cassini_user_defs.h` is HPE's generated Cassini header,
  SPDX `GPL-2.0-only OR BSD-2-Clause`, vendored unchanged because the snapshot manifests hash it.
- DeepEP (MIT, DeepSeek) is included as patches and as the exact tarballs inside the snapshots,
  which also carry the pinned `fmt` submodule (MIT).
- NCCL (BSD-3-Clause, NVIDIA) is included as a patch only.
- SGLang (Apache-2.0) is referenced by file hashes only.
