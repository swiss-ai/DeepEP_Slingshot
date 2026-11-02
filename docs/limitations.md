# Qualified envelope, limitations and open questions

## Qualified envelope

- Exactly two scale-out nodes with four NVLink GPUs each (EP8). The packed dispatch and combine
  paths static-assert two scale-out ranks; the delivery-marker epoch logic flushes the whole
  context on every peer or window change, so more nodes would be correct but slow.
- DeepEP v2 at `bd1e1669`, NCCL v2.32.3-1 at `12df1a11`, the pinned Clariden container, the
  installed libcxi and node image. Qualified on one node pair, one driver and firmware state.
- SGLang normal mode through the adapter in [backend/sglang/deepep_v2_cxi.py](../backend/sglang/deepep_v2_cxi.py):
  synchronous, one live dispatch at a time, group size 8 with a (2, 4) domain, token capacity fixed
  at buffer creation (default 4096 per rank), BF16 combine input, EPLB recorder disabled, FP8 or
  BF16 dispatch (no NVFP4).

## Limitations

- **No low-latency or AUTO mode, no overlap, no CUDA-graph decode.** Every dispatch spins the host
  for the received counts. At 32 to 257 tokens per rank the fixed cost is 0.3 to 0.4 ms per
  operation; decode-style serving needs a different kernel.
- **Fail-fast only.** A transport timeout traps the kernel and the plugin terminates the process
  group (exit 86). There is no recovery and no partial retry.
- **Compile-time knobs outside the JIT cache key.** The `CXI_EP_*` defines are injected by the
  nvcc wrapper from environment variables; DeepEP's kernel cache does not see them. Clear or
  redirect `EP_JIT_CACHE_DIR` when a knob changes.
- **Alignment sensitivity of our GPU-issued PUTs.** PUT addresses 64 bytes off a 128-byte line
  run at a quarter of link rate with our primitives, but not with HPE's `cxi_write_bw` from GPU
  memory at the same lengths, so the cause is in our transport path (registration, delivery
  descriptor bits or command path), not the NIC. The qualified knobs avoid it by construction and
  the synthetic routings produce gapless runs; a real router can break a combine channel's run at
  an odd row. Finding the cause in the transport is the preferred fix; padding the row stride to
  a 128-byte multiple is the fallback.
- **Ordering rests on NIC semantics.** Signals are ordered after payload by the flush-bit marker
  plus `C_CMD_CQ_FENCE`, with no GPU-observed completion, and source-buffer reuse across
  iterations relies on the same chain through the peer's barrier. Thousands of exact-checked
  iterations support it; no test yet overwrites the source immediately after a signal returns.
- **Per-channel flush before the combine's end signal** held the context lock for up to 0.7 ms.
  Removing it (`CXI_EP_SKIP_COMBINE_FLUSH`, 2026-11-02) is exact-correct on every gate and gives
  2 % of combine time, but it also decouples the rail peers' kernel ends: read the harness headline
  together with the wall time per iteration (see [results.md](results.md)). Release matrix pending.
- **Fixed per-call costs that remain are DeepEP-level**: the dispatch copy epilogue (0.09 ms) and
  combine reduce epilogue (0.08 ms) as separate kernels, the entry barrier (0.11 ms, skew-dominated),
  and the combine's first remote PUT at 0.40 ms, which the double-buffered scale-up staging did not
  move (the forward warps' reduction rate gates the wire start). No cadence, SM-count or context-count
  knob improves 4K any further.

## Open questions for NIC and driver experts

1. Does `C_CMD_CQ_FENCE` guarantee that all prior commands on the queue have completed
   (acknowledged), not merely been issued, so source buffers may be reused once the peer observes
   the fenced signal?
2. Our GPU-issued PUTs whose address is 64 bytes off a 128-byte line run at 5 GB/s, while
   `cxi_write_bw` with CPU-issued commands from GPU memory shows no such effect at the same
   lengths. What differs for GPU-written commands on dmabuf-registered GPU memory with
   `CT_SEND`-counted, flush-less payload PUTs?
3. Is `C_CMD_CT_TRIG_EVENT` with threshold equal to the posted count, one outstanding trigger per
   context, the intended usage of counting-event write-back from a GPU?
4. Is GPU mapping of command queues and doorbells (`cudaHostRegister` with IO-memory flags) from
   an unprivileged job a supported configuration or an accident of the current node image?
5. About 4 to 10 µs per 64-byte command from one GPU thread: is there a safe way to cache the
   command-queue read pointer on the GPU? An earlier attempt stalled under sustained load and was
   quarantined (10/30 log, gate 521).
6. Can the kernel-initiated libfabric extension (`rdma/fi_cxi_gpu_ext.h`, used by HPE's CLIC) be
   made available on Clariden? It would give a vendor-backed reference on the same NIC.
