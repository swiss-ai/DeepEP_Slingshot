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
  together with the wall time per iteration (see [results.md](results.md)). The release matrix passed
  on 2026-11-03 (job 3835100, 45 gates).
- **Dispatch: first-touch convoy at the start of the wire phase.** Every channel's first PUT spends
  ~100 µs in the transport because the first access per kernel to each context's host-mapped command
  ring costs ~80 µs when 128 contexts start together (shown by moving the cost from the NIC status read
  into the ring store with cached credits, 11/02 log §5.7; a barrier-time prewarm of every ring does
  not change it, §5.9, so the cost is per access under 128-way concurrency, not per translation).
  The NIC then drains at the ceiling. The ring's registration path is now known (2026-11-03): the
  libcxi command queue is kernel memory mmap'd from `/dev/cxiN`, `cudaHostRegisterMapped` refuses it and
  every ring is registered as IO memory. That attribute is not the cause: addressing the ring through the
  host page tables instead (GH200 ATS, `CXI_RING_ACCESS=ats`, cacheable system memory, no registration)
  is exact-correct, leaves the wall time unchanged and shows the same ~90 µs first access in the trace.
  The cost sits in the GPU→host round trip itself when 128 contexts take it at once. What removes it is a
  GPU-resident command queue, which the upstream Slingshot driver and libcxi gained in 2026 (user and
  device-memory command queues, `cxil_alloc_buf_cmdq`) but the installed SHS 13.1.0 does not have. No
  cadence, SM-count (32 or 128) or context-count knob improves 4K.
- **Fixed per-call costs that remain are DeepEP-level**: the dispatch copy epilogue (0.09 ms) and
  combine reduce epilogue (0.08 ms) as separate kernels, the entry barrier (0.08–0.11 ms,
  skew-dominated), and the combine's 0.28 ms before its first remote PUT (barrier, inter-rank skew,
  scale-up handoff), which the double-buffered scale-up staging did not move. The 2026-11-03 combine
  round ([results.md](results.md)) moved the first PUT to 40 µs after the barrier (early scale-up tail,
  two-row first batch) for a 16 µs gain at 4K; a split entry barrier cannot help because the skew is
  between the rail pairs and every node holds one rank of each pair. The 4K combine stays at 19.2–19.4 GB/s
  against the 20 GB/s target; what is left is the slowest pair's wire phase (94–97 % of the ceiling), the
  per-iteration spread of the pairs' wire ends that the next barrier absorbs, and the epilogue kernel.

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
7. A system-scope load or store to the command ring costs ~80–90 µs when 128 GPU contexts access
   their rings at the same instant, 1–3 µs otherwise, and a load of the same word moments earlier does
   not help. The ring is libcxi's command queue (kernel pages mmap'd from `/dev/cxiN`); the GPU reaches
   it either as IO memory (`cudaHostRegisterIoMemory`, the only registration that succeeds) or, on these
   GH200 nodes, directly through the host page tables (ATS) as cacheable system memory, and the first
   access costs the same either way (2026-11-03). Is this a serialisation point for GPU-issued
   system-scope accesses on the C2C/host path? The structural fix is a command queue in GPU memory:
   upstream shs-cxi-driver (2026-02-18, `CXI_OP_CQ_ALLOC_BUF`) and shs-libcxi (`cxil_alloc_buf_cmdq`,
   device memory 2026-05-26, "KI") provide it; which Slingshot Host Software release will bring it to
   Clariden?
