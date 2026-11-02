# DeepEP v2 direct GIN over Slingshot — 2026-11-02

Continuation of `11_01_DeepEP_v2_Slingshot.md`. Four items: an improvement plan for the dispatch
and combine data paths derived from the code and the 4K traces of the final candidate (§2), the
`cxi_write_bw` link-rate measurement (§3), the first implementation round of the plan (§4), and the
evening's debug-partition slices with the trace decomposition of the lean path, which locate the
dispatch loss in a first-PUT submission convoy and queue the cached-credit transport (§5).

Reference state: `source-1101-first-batch-v1` (marker-zero transport, packed rows, interval 16,
first interval 4, forward chunk 3, merged final tail, packed combine batch 16 / first batch 4,
64 SMs, 129 contexts). V4 Flash FP8/BF16, 4K tokens/rank: dispatch 0.949 ms (bound 0.823 at
21.5 GB/s), combine 1.814 ms (bound 1.573); 16K: 3.439 (3.292), 6.946 (6.291). Size-sweep fits:
dispatch 0.147 ms + MB/21.5 GB/s, combine 0.121 ms + MB/19.8 GB/s.

## 1. Where the time goes (4K, traced build of the candidate, medians over 24 captures)

Dispatch, kernel-relative milliseconds:

| Phase | Time | Mechanism (code) |
|---|---:|---|
| Entry barrier | 0 → 0.116 | `comm::gpu_barrier`: SM1 issues two GIN signals on context 0 (to the peer **and to itself through the NIC**), serialized by the context lock; each signal is 4 NIC commands (marker, CQ fence, CSTATE, AMO) at 5–10 µs per command (trace events 209–213 sum to ~35 µs); then `waitSignal` and a grid sync. Inter-rank skew is absorbed here too. |
| First PUT | 0.131 | first interval 4 rows |
| Last PUT submitted | 0.385 (senders idle 0.424) | 512 PUTs/rank on 129 queues; the NIC is the bottleneck from here |
| Last tail observed by receivers | 1.131 | wire-limited phase; slope 21.5 GB/s in the untraced sweep |
| Exit barrier | → 1.150 | NVLink scale-up barrier + grid sync |
| Copy epilogue (PDL) | → 1.245 | events 120/121: 43 + 27 µs plus handoff |

Combine:

| Phase | Time | Mechanism |
|---|---:|---|
| Entry barrier | 0 → 0.106 | as above |
| Scale-up (NVLink) stage | 0.106 → 0.366 | scale-up warps move ~32 tokens each (8 KB rows) with **one TMA staging buffer per warp**: load → store → wait, ~8 µs per token, latency-bound; tails published every 3 tokens (`kNumScaleupUpdateInterval`) |
| First remote PUT | 0.40 | forward warps' first reduce at 0.32; no remote bytes move for the first 22% of the call |
| Wire phase | 0.40 → 1.93 | 33.8 MB at ~22 GB/s |
| End signal, peer wait, reduce epilogue | → 2.055 | per-channel `gin.flush` (CT write-back wait, lock held ~0.7 ms, event 207) then signal; epilogue 0.08 ms |

Two transport facts from the same traces: lock waits (event 200) in combine have p90 0.47 ms and
p99 1.3 ms, and PUT submissions (event 116) p99 0.8–1.1 ms, i.e. sibling channels stall behind a
channel's flush. Dispatch, which never flushes, has p90 lock waits of 0.1 ms. This matches the
combine slope of 19.8 GB/s versus dispatch's 21.5 GB/s.

## 2. Improvement plan, ordered by expected gain per unit of risk

### 2.1 Combine: drop the per-channel flush before the end signal (CXI path only)

Code: `hybrid_combine.cuh`, forward-warp epilogue: `gin.flush<ncclCoopWarp>()` followed by
`red_add_rel` of `expected_signal`. Under the marker-zero transport the signal is already ordered
after delivery of every prior PUT of the context (zero-byte marker with flush bit, then
`C_CMD_CQ_FENCE`, then the AMO), and the receiver's epilogue is gated on that signal. Source
reuse across iterations is protected by the next kernel's entry barrier (the peer enters the next
kernel only after it observed our signal). The flush is therefore redundant on this backend.
Guard it with `#if !CXI_EP_SKIP_COMBINE_FLUSH`.
Expected: 16K combine −0.4 to −0.5 ms (slope back towards 21.5 GB/s), 4K −0.05 to −0.1 ms.
Risk: ordering argument rests on CQ-fence semantics (CSCS question 1). Validation: exact
correctness matrix plus a new source-overwrite stress gate (overwrite the send buffer immediately
after the signal returns; the receiver must hold the original data).

### 2.2 Transport: make a signal one or two NIC commands instead of four

Code: `cxi_primitives.cuh` `add_locked`, `signal_fence_locked`, `state_locked`, `delivery_flush_locked`.
- Elide the CQ fence when no payload command was emitted on this context since the last fence
  (track a per-context counter; the entry barrier and most combine end signals hit this case).
- Emit CSTATE once per (window, peer) per context and cache the key; re-emit only on change.
  CSTATE is plain command-queue state, not NIC-written state, so this is not the credit-cache
  situation.
- When a signal immediately follows the last payload PUT of an epoch, set the flush and `CT_ACK`
  bits on that PUT instead of appending a zero-byte marker.
Expected: signal cost ~45 → ~12 µs; entry barrier 0.116 → ~0.05 ms in both kernels (two
serialized signals today); dispatch tail −20–30 µs; combine end −30 µs per channel.
Total ≈ −0.08 ms per dispatch and per combine at any size. Risk: medium (state caching).

### 2.3 Barrier: do not signal yourself through the NIC

Code: `comm.cuh` `gin_barrier_wo_local_sync`: `gin.signal(team, i, SignalInc)` for every rail rank
including the local one. Replace the self-signal with a local release store/atomic on the signal
word (`ResetSignal` already shows the pointer path). Saves one full signal per barrier (~45 µs
today, ~12 after 2.2) and removes the lock serialization between the two signals.
Expected: −0.03 to −0.045 ms per kernel. Risk: low (NCCL signal shadow must still be bumped).

### 2.4 Combine: start the wire earlier

Two independent routes:
- **More SMs.** The scale-up stage is latency-bound per warp, so it scales with warp count.
  Run the candidate with `CXI_EP_SMS=128` and `CXI_EP_CONTEXTS=257` (keeps two channels per
  context; 128 SMs on 128 contexts would put four channels on one lock). The SGLang adapter
  already accepts the SM count; `CXI_EP_PACK_COMBINE_CHANNELS` follows automatically. Expected:
  scale-up stage 0.26 → ~0.13 ms, first remote PUT ~0.25 ms, 4K combine −0.1 to −0.15 ms.
  Zero code change; one gate.
- **Double-buffered TMA staging in the scale-up warps** (`hybrid_combine.cuh`, scale-up role:
  one `tma_buffer` per warp today). Two buffers per warp fit in shared memory (8.3 KB each,
  8 warps per SM). Overlaps the NVLink store of token n with the load of token n+1.
  Expected similar to the above and additive with it. Kernel change, moderate.

### 2.5 Row stride padded to 128 bytes

Code: `layout.cuh` `TokenLayout::get_num_bytes` (16-byte TMA alignment today). Padding the token
stride to a 128-byte multiple (FP8 4320 → 4352, BF16 8288 → 8320, combine 8256 → 8320; +0.4–0.7%
bytes) makes every PUT boundary aligned, so (a) a real router's gaps in the combine runs no
longer produce 64-byte-offset PUTs at a quarter rate, and (b) the cadence knobs can be revisited
(regular interval 8 was −1.4% at 16K but unsafe in general). Needs a full re-qualification
because the layout is shared by all buffers and the epilogues.

### 2.6 Transport micro-costs in `emit`

- The `__threadfence_system()` after writing a command is redundant when the command is
  aggregated and not published; `publish_locked` fences before the doorbell. Saves ~1–2 µs per
  command.
- Credit caching (skip the CQ status read while the cached read pointer leaves enough room) was
  built as `source-credit-cache-v2` and quarantined after an undiagnosed stall under sustained
  16K load (10/30 log, gate 521). Re-attempt only with a reproducer; the per-command cost
  (4–10 µs) is what caps a single queue at ~12 GB/s and what makes dense cadences lose at 4K.

### 2.7 Items that need DeepEP-level redesign (not transport)

- **Copy epilogue (0.09 ms)**: forwarders could write hidden rows straight into the final
  receive tensor if the per-rank prefix sums (known after the notify stage at ~0.2 ms) were
  consumed in-kernel; the epilogue would shrink to scales/metadata. Changes DeepEP's output
  contract; also affects `do_expand`.
- **Entry barrier as such**: needed for buffer reuse. Double-buffered receive buffers would let
  dispatch N+1 start before combine N's readers finish. Larger memory, DeepEP change.
- **Small batches / decode**: at 32–257 tokens the fixed cost is 0.3–0.4 ms per call and the host
  spins for counts. A decode-class path needs a single-shot kernel without CPU sync (DeepEP LL
  analogue). Separate track.

### 2.8 Expected position after 2.1–2.4 (estimates, not measurements)

| 4K V4 Flash | now | after | bound 21.5 | bound 25 |
|---|---:|---:|---:|---:|
| dispatch | 0.949 | ~0.85 | 0.823 | 0.708 |
| combine | 1.814 | ~1.55–1.60 | 1.573 | 1.352 |

16K combine should recover most of its slope deficit (6.95 → ~6.45 ms). Beyond that the only
lever is the link rate itself, which is what the `cxi_write_bw` measurement below is for.

### 2.9 Validation discipline for every item

One knob per immutable snapshot; exact-correctness gates (payload, scales, routing, weights,
integer and float combine, cycle) before timing; three counterbalanced repeats; three model
geometries; the SGLang gates for anything touching layouts; node-local JIT. New gates to add:
source-overwrite-after-signal stress (for 2.1 and 2.2), and the alignment probe methodology for
anything that changes PUT boundaries.

## 3. Link-rate measurement with `cxi_write_bw`

Purpose: an independent ceiling for the per-NIC rate, so the DeepEP ratios are judged against
what the NIC delivers rather than the 25 GB/s port rate or our own transport's 21.5 GB/s.
Tool: `/usr/bin/cxi_write_bw` 2.4.0 (`cray-libcxi-utils-1.0.2-SHS13.1.0`), HPE's host-side RDMA
write benchmark on the same libcxi the backend uses. Scripts and collector:
`tools/cxi_gin/experiments/link_rate_1102/` (`run.sbatch`, `run_gpu.sbatch`, `wrap.sh`,
`inventory.sh`, `collect_write_bw.py`); raw outputs under `results/cxi_write_bw_20261102/job-<id>/`.
Setup: 256 writes per doorbell (`-l 256`, the tool's default), 4–6 s per case, client on one
node writing to a server on the other over one rail (cxi0 ↔ cxi0), default service ID (the Slurm
switch plugin does not export `SLINGSHOT_*` into these steps; the default service was usable).
The tool reports the client's own write bandwidth in 10^6 B/s; in bidirectional mode it prints
the sum of both directions (verified: 107,776 writes × 1 MiB / 5 s = 22.6 GB/s against a printed
45.1 GB/s), so per-direction values below are half the printed number.

### 3.1 Job 3832897 (09:48–10:10 UTC, nid007470 ↔ nid007659): host memory

| Write size | unidirectional GB/s | packets per write | bidirectional GB/s per direction |
|---:|---:|---:|---:|
| 4 KB | 16.7 | 2 | |
| 8 KB | 19.5 | 4 | |
| 16 KB | 21.7 | 8 | |
| 32 KB | 23.0 | 16 | |
| 64 KB | 23.6 | 32 | 22.3 |
| 69,120 B (FP8 16 rows) | 23.6 | | |
| 132,096 B (BF16 16 rows) | 23.9 | | 22.4 |
| 256 KB | 24.0 | | |
| 1 MiB | 24.2 | 512 | 22.6 |

- **Unidirectional ceiling 24.2 GB/s** (96.7 % of the 25 GB/s port rate) for writes of 256 KB
  and above; 23.6–23.9 GB/s at the DeepEP PUT sizes.
- **Bidirectional costs about 7 %**: 22.3–22.6 GB/s per direction while the peer writes back at
  the same time. DeepEP's rails are always bidirectional (both nodes dispatch and combine at
  once), so 22.5 GB/s is the relevant host-memory ceiling for our traffic.
- **Packet size is 2 KB.** Packet rate ÷ write rate gives 4.0 packets per 8192-byte write,
  5.0 per 8256-byte write (4 × 2048 + 64), 512 per 1 MiB write. The 3.3 % between 24.2 and
  25 GB/s is per-packet framing (about 70 bytes per 2 KB packet).
- **Small writes are command-rate bound**: 8 KB writes run at 2.4 M writes/s on one queue
  (19.5 GB/s) regardless of alignment.
- **No 128-byte alignment cliff from host memory**: 8256-byte writes at 64-byte placement
  (every second write 64 bytes off a 128-byte line) run at 19.55 GB/s against 19.48 GB/s at
  128-byte placement, and 8192/8320-byte writes are identical. The cliff we measured with
  GPU-sourced PUTs is therefore not a NIC transmit property; the GPU-memory run below tests
  the read side.
- GPU-memory cases failed in this job: the bare node has no `libcudart.so` for the tool to
  open. Three of four concurrent four-rail clients connected before their servers listened
  (no retry in the first wrapper). Both fixed in `run_gpu.sbatch` / `wrap.sh` (job 3833183).

### 3.2 Job 3833183 (10:15–10:35 UTC, nid006052 ↔ nid006088): GPU memory, one rail

`libcudart.so.13.0.88` copied out of the harness container image to scratch and put on
`LD_LIBRARY_PATH`; the tool then allocated its buffers on GPU 0 of each node (`-t 0` client,
`-r 0` server; both for bidirectional), NIC cxi0 on NUMA node 0, same as GPU 0.

| Write size | GPU→GPU unidirectional GB/s | host control (same nodes) | GPU↔GPU bidirectional GB/s per direction |
|---:|---:|---:|---:|
| 16 KB | 22.4 | | |
| 64 KB | 23.7 | | 22.4 |
| 69,120 B | 23.7 | | |
| 132,096 B | 24.0 | 23.9 uni / 22.5 bi | 22.4 |
| 256 KB | 24.1 | | |
| 1 MiB | 24.2 | | 22.6 |

- **GPU memory is not the limiter.** NIC reads from HBM and writes into HBM deliver exactly the
  host-memory rates: 24.2 GB/s unidirectional, 22.4–22.6 GB/s per direction bidirectional.
- **No alignment cliff from GPU memory with CPU-issued commands either**: 8256-byte writes at
  64-byte placement 20.61 GB/s, at 128-byte placement 20.63; 8192 and 8320 bytes the same
  (20.6–20.7). The cliff measured with our GPU-issued primitives (5 GB/s at 64 bytes off a line,
  allocation I on 11/02) is therefore **not a property of the NIC data path as exercised by
  HPE's tool**. The remaining candidates are specific to our command construction or issue path
  (descriptor fields, CT_SEND batched delivery, the exact PUT lengths of 14–16 rows), which is
  good news: it may be avoidable in the transport instead of by padding the layout. Section 3.3
  replicates the probe's exact PUT lengths with CPU-issued commands to narrow this down.
- **Commands per doorbell matter on one queue**: 132,096-byte writes run at 9.9 GB/s with one
  write per doorbell, 22.0 with 16, 24.0 with 256. This is the same issue-rate ceiling our
  single-queue probe hit (~12 GB/s for 69 KB PUTs); the kernels' 129 queues hide it.
- Four-rail concurrent runs: only three clean points (cxi3 at 132 KB: 22.1 GB/s per direction;
  cxi0 and cxi2 at 1 MiB concurrently: 22.1 each). The other clients could not connect to their
  servers even with 20 retries; the job then ran out of its 20-minute limit before the host
  four-rail cases. Diagnosed below; rerun in job 3 together with the alignment replica.

**Consequence for the DeepEP bounds.** The NIC's ceiling for our traffic pattern (GPU memory
both ends, both directions busy) is **22.5 GB/s per direction**, not 25 and not 21.5. Re-based:

| 4K V4 Flash | measured | bound at 22.5 GB/s | ratio | bound at 25 GB/s | ratio |
|---|---:|---:|---:|---:|---:|
| dispatch | 0.949 ms | 0.786 ms | 1.21 | 0.708 ms | 1.34 |
| combine | 1.814 ms | 1.503 ms | 1.21 | 1.352 ms | 1.34 |
| 16K dispatch | 3.439 ms | 3.146 ms | 1.09 | 2.832 ms | 1.21 |
| 16K combine | 6.946 ms | 6.013 ms | 1.16 | 5.411 ms | 1.28 |

The size-sweep slopes (21.5 GB/s dispatch, 19.8 combine) are 4–12 % below this ceiling, so
part of the gap that section 2 attributed to fixed cost is wire efficiency: the kernels'
PUT stream does not keep the NIC as busy as the tool's 256-deep single queue does.

### 3.3 Job 3833451 (10:40–10:44 UTC, nid007653 ↔ nid007657): alignment replica, batch 8, four rails

All 39 runs completed. The four-rail failures of jobs 1 and 2 were a harness artefact: each
concurrent `srun` step requested all four GPUs, so Slurm ran the server steps one at a time; the
later servers started after their clients had given up and their buffered "Listening" line was
lost when my timeout killed them. Fixed with `srun --overlap` and line-buffered output.

**(a) The GPU-issued alignment cliff does not exist for CPU-issued commands.** Same PUT lengths
as the 11/02 offset probe (rows × row bytes), GPU memory on both ends, 256 writes per doorbell,
writes placed back to back so that their start addresses alternate between 0 and 64 bytes (or 32)
past a 128-byte line, against 128-byte placement as control:

| PUT bytes | = rows × row | start addresses at 64-B placement | GB/s at 64-B placement | GB/s at 128-B placement | our GPU-issued probe, same shape |
|---:|---|---|---:|---:|---:|
| 60,480 | 14 × 4320 | alternating 0 / 64 | 23.68 | 23.69 | 5.03 (64 off) |
| 64,800 | 15 × 4320 | 0 / 32 (32-B placement) | 23.77 | 23.71 | 10.4 (32/96 off) |
| 69,120 | 16 × 4320 | always 0 | 23.75 | 23.77 | 12.0 (issue-bound) |
| 107,328 | 13 × 8256 | alternating 0 / 64 | 23.88 | 23.88 | 4.95 (64 off) |
| 115,584 | 14 × 8256 | always 0 | 23.95 | 23.98 | 20.1 |
| 123,840 | 15 × 8256 | alternating 0 / 64 | 23.96 | 23.96 | 4.95 (64 off) |
| 132,096 | 16 × 8256 | always 0 | 23.96 | 24.01 | 21.4–21.9 |

Host memory at 64-byte placement: 60,480 B 23.72, 123,840 B 23.79. So the NIC moves 64-byte-offset
PUTs from and into GPU memory at full rate when the commands come from the host. The 4.3× cliff
is specific to the GPU-issued path of our transport. Candidate differences, in order of
suspicion: the memory registration (our dmabuf mapping via `cuMemGetHandleForAddressRange` and
`cxil_map` with `CXI_MAP_DEVICE`, against the tool's own GPU buffer mapping in libcxiutils),
descriptor bits (batched delivery uses `event_ct_send` without the flush bit, the tool uses
`CT_ACK`), and the command-queue write path itself. Decisive follow-up, one raw-probe gate
(`offset_probe.cu`, kind `offset`): (1) the same cases with host-pinned source and destination
registered as host memory, GPU-issued; (2) the same cases with `CXI_BATCH_DELIVERY=0` (per-PUT
`CT_ACK` + flush). If (1) is flat the cliff is in the GPU-memory mapping; if (2) is flat it is in
the delivery descriptor bits; if neither, it is the GPU-written command path. This replaces
section 2.5's row padding as the first move: a transport fix would remove the constraint without
touching the layout.

**(b) Doorbell batching with our transport's batch of 8** (`CXI_TX_BATCH_LIMIT=8`), one queue,
GPU memory: 69,120-byte writes 18.3 GB/s, 132,096-byte writes 20.8 GB/s (batch 1: 9.9; 16: 22.0;
256: 24.0 at 132 KB). One queue with our batch size cannot saturate the link; the kernels need
their 129 queues. Where few queues carry traffic (small batches, the tail), a larger batch would
help, but DeepEP's channels issue one or two PUTs per notification, so the lever is small.

**(c) Four rails concurrently** (GPU i ↔ cxi i, NUMA-matched, both nodes):

| Case | per rail, per direction | single-rail reference |
|---|---:|---:|
| GPU bidirectional, 132,096 B | 22.2 GB/s on all four | 22.4 |
| GPU unidirectional, 132,096 B | 24.0 on all four | 24.0 |
| host bidirectional, 132,096 B | 22.1 on all four | 22.5 |
| host unidirectional, 1 MiB | 23.0 on all four | 24.2 |
| GPU bidirectional, 1 MiB | 15.5–15.6 on all four | 22.6 |

At the DeepEP PUT size there is no node-level sharing: each of the four NICs delivers its
single-rail rate with all four busy in both directions. The 1 MiB GPU bidirectional case drops to
15.5 GB/s per direction with four rails active (single data point, 5 s; 256 writes × 1 MiB =
256 MB of GPU memory per direction per rail, so address-translation pressure is the first
suspect). It does not affect DeepEP, whose PUTs are at most 132 KB, but it is worth a repeat
before anyone relies on multi-megabyte GPU PUTs.

### 3.4 Conclusions

1. **Ceiling for DeepEP's traffic pattern: 22.2–22.6 GB/s per NIC per direction** (GPU memory
   both ends, both directions busy, all four rails active). Unidirectional the NIC reaches
   24.2 GB/s (96.7 % of 25); the bidirectional penalty is 7 %, 2 KB packets cost 3.3 %. GPU
   memory costs nothing against host memory. The 21.5 GB/s used as the bound so far was our own
   transport's plateau, 4–5 % under the NIC's.
2. **Re-based ratios (bound at 22.5 GB/s):** 4K dispatch 1.21, 4K combine 1.21, 16K dispatch
   1.09, 16K combine 1.16. The kernels' incremental slopes (21.5 and 19.8 GB/s) are 4–12 % under
   the ceiling, so wire efficiency, not only fixed cost, is still on the table.
3. **The 128-byte alignment cliff is ours, not the NIC's.** Highest-value next experiment: the
   two raw-probe variants in 3.3(a). Until then the candidate's "boundaries on multiples of four
   rows" rule still protects it.
4. Methodology notes for anyone repeating this: `cxi_write_bw` needs a CUDA runtime on the bare
   node for GPU buffers (copy `libcudart.so.13` from the container image; the host driver's
   `libcuda.so.1` is enough for the rest); concurrent `srun` steps on one node need `--overlap`;
   the tool prints bidirectional bandwidth as the sum of both directions.

## 4. Implementation round 1: lean signal path and kernel-side signal changes (allocation J)

**Target set by the user (15:00 CET):** 20 GB/s effective for both operations at 4K tokens/rank,
i.e. with the 22.5 GB/s bound 4K dispatch ≤ 0.884 ms (now 0.949) and 4K combine ≤ 1.691 ms
(now 1.814). Plan items 2.1–2.4 are the levers; this round implements 2.1, 2.2 and 2.3 and runs
2.4's zero-code arm (128 SMs / 257 contexts).

### 4.1 What was built (snapshot `source-1102-lean-v1`, parent `source-1101-first-batch-v1`)

Scripts: `tools/cxi_gin/experiments/pipeline_1102/{prepare_lean_1102.py,package_lean_1102.py,
package_hold_1102.py,package_lean_dbg_1102.py}`. Every change is knob-guarded; the parent's
behaviour is the default.

Transport (`backend/device/cxi_primitives.cuh`, selected per runtime variant in `variants.json`):

- `CXI_LEAN_FENCE` — `signal_fence_locked` emits the `C_CMD_CQ_FENCE` only when a transfer that
  must precede the signal (payload PUT, delivery marker, inline value PUT) was posted since the
  last fence or since a completed flush (`flush_locked` clears the flag once `completed ==
  posted`). The entry barrier's signal and a signal that follows another signal therefore lose
  the fence; a signal after a PUT keeps it. Safe under either reading of the fence semantics,
  because the elided fence would only repeat an earlier one.
- `CXI_LEAN_CSTATE` — `state_locked` re-emits the CSTATE command only when its `(index_ext,
  write_lac)` pair differs from the cached one. CSTATE is command-queue state consumed by later
  IDC commands (AMO, inline PUT); DMA commands carry their own fields. Per context the pair is
  constant for a given destination window, so after the first signal every later one skips it.
- `CXI_LEAN_FOLD_MARKER` — `delivery_flush_locked` closes the epoch by rewriting the pending payload
  PUT's descriptor in the ring (`event_ct_send=0, event_ct_ack=1, flush=1`) when that PUT is still
  the newest, un-doorbelled entry, instead of appending a zero-byte marker command. Delivery
  semantics and the CT accounting (`posted`, one event per command) are unchanged; one command
  and one NIC round trip per signal are saved. Tracking: `publish_locked` and every `emit` clear
  the "newest entry is the pending PUT" bit, `put_locked` sets it when the PUT stayed unpublished.
- State lives in a new 32-bit `CxiGpuContext::lean_state` inside the former trailing padding
  (`sizeof` stays 192, ABI version unchanged); the host sets it to "fence due" at channel open and
  recycle (`cxi_resources.cc`).

Variants: `marker-zero` (parent), `lean-a` (fence elision + CSTATE cache), `lean-b` (lean-a +
marker fold). Signal cost: parent 4 commands (marker, fence, CSTATE, AMO); lean-a 3 after the
first signal on a context (2 when nothing was posted since the last fence); lean-b 2 (patched
PUT counts as payload) after a PUT, 1 for a bare signal.

Kernels (DeepEP archive, selected per gate through the nvcc wrapper environment):

- `CXI_EP_SKIP_COMBINE_FLUSH` (plan 2.1) — `hybrid_combine.cuh` forward-warp epilogue: the
  `gin.flush<ncclCoopWarp>()` before `red_add_rel(expected_signal)` is compiled out. Ordering of
  the signal after the channel's PUTs is the NIC's (marker/flush bit then CQ fence), the same chain
  dispatch already relies on; the removed call held the context lock for the whole drain.
- `CXI_EP_LOCAL_SELF_SIGNAL` (plan 2.3) — `comm.cuh` `gin_barrier_wo_local_sync`: the rank neither
  signals itself through the NIC nor waits on its own slot. With two rail ranks the barrier
  becomes one signal and one wait.

Gate records carry the knobs (`skip_combine_flush`, `local_self_signal`, `variant` in each case
record; the compiler reports carry the `-D` flags).

### 4.2 Arms and gates

| arm | runtime variant | kernel knobs | SMs / contexts |
|---|---|---|---|
| cand | marker-zero | none (reference) | 64 / 129 |
| kern | marker-zero | skip combine flush, local self-signal | 64 / 129 |
| leana | lean-a | both | 64 / 129 |
| leanb | lean-b | both | 64 / 129 |
| leanb128 | lean-b | both | 128 / 257 |

Full matrix (`source-1102-lean-v1`, 31 gates): per non-reference arm the correctness ladder
(irregular stress 32/257 tokens × 5 routings × 3 seeds, 4K FP8+BF16 × 5 routings, dropped
tokens, sustained 16K), then three counterbalanced 4K/16K repeat gates per arm (9200–9224).
Debug companion (`source-1102-lean-dbg-v1`, identical code, 9 gates with shortened timeouts for
the 25-minute two-node debug allocation): leanb ladder, cand and leanb repeats, leanb128 stress
and repeat, kern stress.

Jobs: 3835100 (normal partition, 4 h, holder snapshot `source-1102-hold-v1` = candidate
reference gates 9000–9003; Slurm's start estimate 20:55 CET; the 31 lean gates are pushed into it
once it runs), 3835147 (debug partition, 25 min, companion). Preflight of the lean snapshot on
the login node PASS (all three variants compile the device tests, the lean burst probe compiles).

Kernel-template preflight of the lean snapshot on the login node (all 24 EP8 instantiations with
`CXI_EP_SKIP_COMBINE_FLUSH=1 CXI_EP_LOCAL_SELF_SIGNAL=1`, lean-b runtime): PASS, combine 216
registers / 0 spills as before, dispatch 144 (fresh) and 128 (cached) registers, 0 spills.

### 4.3 Round 2 prepared: double-buffered TMA staging in the combine scale-up warps (plan 2.4b)

Snapshot `source-1102-dbuf-v1` (parent `source-1102-lean-v1`; `prepare_dbuf_1102.py`,
`package_dbuf_1102.py`, debug companion `source-1102-dbuf-dbg-v1`). Knob
`CXI_EP_COMBINE_DOUBLE_TMA`: each scale-up warp gets a second shared-memory token buffer (placed
after all first-stage buffers; the launcher already passes the device's maximum dynamic shared
memory, and a static assert bounds `(warps + scale-up warps) × (hidden bytes + 1 KB) ≤ 220 KB`),
tokens alternate between the two buffers with their own mbarrier/phase, and the wait before
refilling a buffer becomes `cp.async.bulk.wait_group 1`, so the NVLink store of token n overlaps
the load or reduction of token n+1. `update_tails` still drains all stores before publishing a
tail. Arms: leanb, dbuf (= leanb + knob), leanb128, dbuf128; dbuf ladders plus three
counterbalanced repeats (21 gates); the debug companion runs the dbuf ladder, one repeat per arm
and the dbuf128 stress gate.

### 4.4 Results

**Debug job 3835147 (nid007645/nid007666, 15:57–16:20 CET), `source-1102-lean-dbg-v1`.** All leanb
correctness gates PASS (irregular stress 32/257 × 5 routings × 3 seeds; 4K FP8+BF16 × 5 routings;
dropped tokens; sustained 16K FP8+BF16). The candidate reference in the same allocation reproduces
the release numbers exactly (4K 0.948 / 1.813 ms, 16K 3.435 / 6.944 ms).

| V4 Flash FP8, mixed | cand (9504) | leanb (9505) | leanb rank-median | leanb best iteration |
|---|---:|---:|---:|---:|
| 4K dispatch | 0.948 ms | 0.941 ms (−0.8 %) | 0.929 (cand 0.940) | 0.900 (cand 0.919) |
| 4K combine | 1.813 ms | 1.822 ms (+0.5 %) | 1.756 (cand 1.801) | 1.667 (cand 1.769) |
| 16K dispatch | 3.435 ms | 3.423 ms (−0.4 %) | 3.410 (cand 3.419) | 3.258 (cand 3.268) |
| 16K combine | 6.944 ms | 7.176 ms (+3.4 %) | 6.887 (cand 6.927) | 6.531 (cand 6.753) |

Reading (per-rank, per-iteration CUDA-event times, `pipeline_1102/rank_hist.py`): the lean arm makes
the *typical* iteration faster in both kernels (combine rank median −2.5 % at 4K, best iterations −6 %
at 4K and −3 % at 16K), but combine acquires a rank-to-rank spread that the headline metric (median
over iterations of the per-iteration maximum across the eight ranks) turns into a loss. At 16K the
per-rank values are trimodal: 6.55, 6.89 and 7.22 ms (steps of ~330 µs); the candidate is unimodal at
6.93 ms. The slow ranks change from iteration to iteration and are not rail-paired, so the lateness
is on the *sender* side (a peer's end signal for some channel leaves late). Dispatch shows no such
spread. The small-batch gate (32/257 tokens) shows combine −18 to −25 % at 32 tokens, dispatch −1 to
−4 %: the barrier and signal command savings are worth only ~10 µs per call, far less than the
command-count estimate in §2.2–2.3; the entry barrier is dominated by inter-rank skew, not by
command issue.

**128 SMs / 257 contexts (leanb128, gate 9507) is a loss at 4K:** dispatch 1.082 ms (+14 %), combine
1.960 ms (+8 %); at 16K it equals leanb (3.421 / 7.150 ms). With 512 channels a 4K dispatch has 8
tokens per channel (PUTs of 4 + 4 rows, twice as many PUTs and signals), and the combine's forward
warps have 8 rows per channel. Plan item 2.4's "more SMs" lever is closed for 4K; the scale-up stage
has to be shortened inside the warp (double-buffered staging, round 2).

**The spread comes from the kernel-side change, not the transport (gate 9512, pushed into the same
allocation's last minutes):** the kern arm (marker-zero transport + `CXI_EP_SKIP_COMBINE_FLUSH` +
`CXI_EP_LOCAL_SELF_SIGNAL`) shows the same picture as leanb at 4K: dispatch 0.936 ms (−1.2 %),
combine rank median 1.763 ms (−2.1 %) and best 1.677 ms, but the per-rank distribution is bimodal
(1.68–1.75 and 1.80–1.85 ms) so the headline is 1.831 ms (+1.0 %). In the candidate the rare slow
iterations hit rail pairs together (patterns `S...S...`); with the flush removed each rank is slow
independently with probability ≈0.25 per iteration (slow count 22–28 of 100 on every rank, no
pairing), so with eight ranks almost every iteration has one slow rank. The slow rank's excess is
≈80 µs at 4K and ≈330 µs at 16K, proportional to the token count. The lean transport on top of kern
changes neither the typical time nor the spread (leanb ≈ kern), and buys dispatch about 1 %.

**What the spread is (resolved from the records, no new gate needed).** `measure()` records a
CUDA event pair around each call without a per-iteration synchronisation, so a rank's windows are
contiguous and `window_i = T_i − T_{i−1}` with `T_i` the absolute end of iteration *i* on that rank. The
headline metric takes the maximum of `window_i` across ranks, which equals the common duration plus
`max_rank(δ_i − δ_{i−1})` when the ranks' kernel ends carry an independent skew `δ`. With the flush,
each combine ended on both rail peers only after both had drained everything, so the ends were tightly
aligned (the rare slow iterations hit rail pairs together). Without the flush each rank ends when its
peer's last signal arrives, the two directions are independent, and the ends carry a per-rank skew of
≈80 µs (4K) / ≈330 µs (16K). The skew is absorbed by the next kernel's entry barrier and costs no
throughput: the slowest rank's host wall time per iteration over the timed loop (`host_us_per_iteration`
= total GPU time / iterations) improves on every arm.

| V4 Flash FP8 mixed, same allocation, wall per iteration (slowest rank) | cand | kern | leanb | dbuf |
|---|---:|---:|---:|---:|
| 4K dispatch | 0.944 ms (18.7 GB/s) | 0.935 (18.9) | 0.934 (18.9) | 0.932 (19.0) |
| 4K combine | 1.804 ms (18.7) | 1.767 (19.1) | 1.759 (19.2) | 1.757 (19.2) |
| 4K dispatch + combine cycle | 2.747 ms | 2.702 (−1.6 %) | 2.699 (−1.7 %) | 2.688 (−2.1 %) |
| 16K dispatch | 3.418 ms (20.7) | — | 3.412 (20.7) | 3.414 (20.7) |
| 16K combine | 6.915 ms (19.6) | — | 6.878 (19.7) | 6.898 (19.6) |

(`pipeline_1102/effective_rate.py ... --wall`; dbuf and its leanb reference are from job 3835199 on the
same node pair, cand/kern/leanb from job 3835147.) Conclusions: (1) dropping the combine flush and the
NIC self-signal is worth 2.1 % of combine and 1 % of dispatch time at 4K; (2) the lean transport
(lean-a/lean-b) adds at most 0.3 % on top; (3) the double-buffered staging adds nothing measurable at
4K or 16K, so the scale-up stage is not on the combine's critical path (or the pipeline drains every
three tokens at `update_tails` anyway); (4) the headline metric must be read together with the wall
time whenever a change alters how the ranks' ends align. Position against the user's target: 19.0 GB/s
dispatch and 19.2 GB/s combine effective at 4K, versus 20 GB/s wanted (0.884 / 1.691 ms); the
remaining gap is 48 µs on dispatch and 66 µs on combine per call.

**Cadence with cheap signals (job 3835199's idle minutes, zero-code arms on lean-b, 4K, wall per
iteration):** dispatch regular interval 8 (first 4) 0.961 ms vs 0.933 (+3.1 %), combine batch 8 (first 4)
1.784 ms vs 1.758 (+1.5 %). Denser notification still loses at 4K even with two-command signals; the
cost is on the NIC/wire side (more, smaller PUTs and their flush/fence round trips), not on the GPU
issue side. Together with the 128-SM result this closes every zero-code lever of the plan.

**Second node pair (job 3835540, nid007646/nid007666, 16:42–17:07 CET, `source-1102-iso-dbg-v1`):** all
four transport arms pass sustained 16K FP8+BF16 on the dbuf archive; the 4K/16K repeats reproduce the
first pair within 0.3 %.

| wall per iteration (slowest rank), V4 Flash FP8 mixed | cand | kern | leana | leanb |
|---|---:|---:|---:|---:|
| 4K dispatch | 0.946 ms | 0.936 (−1.1 %) | 0.942 (−0.4 %) | 0.934 (−1.2 %) |
| 4K combine | 1.803 ms | 1.767 (−2.0 %) | 1.768 (−1.9 %) | 1.759 (−2.4 %) |
| 4K cycle | 2.750 ms | 2.701 (−1.8 %) | 2.713 (−1.4 %) | 2.692 (−2.1 %) |
| 16K dispatch | 3.451 ms | 3.419 (−0.9 %) | 3.390 (−1.8 %) | 3.412 (−1.1 %) |
| 16K combine | 6.945 ms | 6.896 (−0.7 %) | 6.887 (−0.8 %) | 6.884 (−0.9 %) |

Headline metric on the same gates: 4K combine +0.8 to +1.5 %, 16K combine +3.3 to +3.6 % (the end-skew
inflation described above), dispatch −0.2 to −2.1 %. The lean-b transport is the best arm on every row
but only by 0.1–0.5 % over kern. **One context per channel is a loss (gate 9714, leanb + `CXI_EP_CONTEXTS=257`, 4K):** dispatch 1.019 ms
(+7.7 % vs cand, wall), combine 1.850 ms (+2.6 %), and the per-rank spread widens further (1.68–2.10 ms).
With 256 queues each carrying half the commands the NIC drains worse, as the F-campaign note on "few
PUTs per queue" already said; the sibling-channel sharing of a queue is not what limits the lean arms.
The flush-only / self-signal-only attribution gates did not fit the allocation (kern vs cand in the
holder job's matrix covers the pair).

### 4.5 Position at the end of the day and what is queued

Against the user's target of 20 GB/s effective for both operations at 4K (0.884 / 1.691 ms at the
22.5 GB/s bound), the best arm (lean-b transport + no combine flush + no NIC self-signal) stands at
**0.934 ms dispatch (18.9 GB/s) and 1.759 ms combine (19.2 GB/s)** wall per iteration on two node pairs,
i.e. −1.2 % and −2.4 % against the candidate's 0.946 / 1.803; the dispatch+combine cycle is −2.1 %.
Every zero-code lever of §2 has now been measured and closed: more SMs (+8–14 %), one context per channel
(+3–8 %), denser dispatch cadence (+3 %), smaller combine batches (+1.5 %), double-buffered scale-up
staging (0 %). The transport's command savings are real but small because the issue side is not the
critical path at 4K; the entry barrier is skew-dominated; the wire phase and the two epilogues are.

What would move the remaining 48 µs (dispatch) and 66 µs (combine) per call is DeepEP-level: the copy
epilogue of dispatch (0.09 ms) and the reduce epilogue of combine (0.08 ms) as separate kernels after the
main kernel, the entry barrier that cannot overlap the previous kernel's tail (0.11 ms), and the
combine's late first PUT (0.40 ms) that the double buffer did not move, so it is the forward warps'
reduction rate, not the scale-up warps, that gates the wire start. The traced gates queued for tonight
(cand / kern / leanb at 4K) are meant to measure exactly these phases on the new code.

Queued unattended in the normal-partition holder job 3835100 (start estimate 22:00 CET, after this
session's certificate expires): the candidate reference (9000–9003), the lean matrix without the
128-SM arm (kern / leana / leanb ladders and three counterbalanced repeats with cand; 24 gates), the
double-buffer matrix without 128-SM arms (leanb stress, dbuf ladder, repeats; 11 gates), three extra
leanb repeats, and the three trace gates (`source-1102-lean-trace-v1`, kind rewritten to `ep`,
validate offline with `runner/validate_trace.py`, analyse with `pipeline_1101/trace_timeline.py`).
Results land in `jobs/3835100/results/` on Clariden; `pipeline_1102/effective_rate.py <dir> '^92\d\d-'
--ref cand --wall` and `summarize_arms.py` read them. A failed gate pauses the controller
(`PAUSED.json`); resume with a `RESUME.json` carrying a reason.

Jobs used this afternoon: 3835147 (debug, lean companion), 3835199 (debug, double-buffer companion),
3835540 (debug, isolation), 3835100 (normal, holder, pending). None of the user's own jobs were touched.

## 5. Evening: debug-partition slices, trace decomposition of the lean path, the first-PUT convoy

Certificate refreshed at 21:00 CET; the normal-partition holder 3835100 had slipped to 07:33 CET 11-03, so
the pending matrix was cut into 25-minute debug slices (2 nodes each; `pipeline_1102/launch_debug_1102.py`
installs, preflights and submits with the partition override; `package_trace_dbg*_1102.py`,
`package_sms32_dbg_1102.py`, `package_credit_dbg_1102.py` size the gates so that `timeout + 180 s` fits
the remaining allocation at every start).

### 5.1 Slices and jobs

| Job | Snapshot | Pair | Gates | Outcome |
|---|---|---|---|---|
| 3837687 | `source-1102-trace-dbg-v1` (= lean-trace code) | nid006286/006298 | 9900 trace cand, 9901 trace kern, then repeats | 9900 PASS; 9901 **FAIL in the trace validator**: it required the combine flush scopes (203/207) that `CXI_EP_SKIP_COMBINE_FLUSH` removes. Controller paused; the poller watched `jobs/<id>/results/PAUSED.json` instead of `jobs/<id>/PAUSED.json` and missed it, 17 minutes idle. Correctness of 9901 itself PASS; its traces are complete and used below. |
| 3837809 | `source-1102-trace-dbg-v2` (validator follows the knobs: 203/207 not required without the flush, 212 not required with `CXI_LEAN_CSTATE`, 211 not required with `CXI_LEAN_FENCE`; counts reported) | nid006286/006298 | 9901 trace kern, 9902 trace leanb, 9903–9910 cand/kern/leanb repeats | all 10 PASS (18.6 min) |
| 3837850 | `source-1102-sms32-dbg-v1` (= dbuf code) | — | leanb at 32 SMs ladder + repeats, cand/leanb references | queued, start 22:15 CET |
| 3837957 | `source-1102-credit-dbg-v1` (cached credits, ABI 4) | — | leanc ladder incl. sustained 16K, cand/leanb/leanc repeats | queued |

The patched validator was checked offline against the 9900 and 9901 traces before the second submission
(`combine_flush_scopes` 6144 for cand, 0 for kern; CSTATE and fence submissions 18 528 / 18 480).

### 5.2 Third node pair (job 3837809, wall per iteration, slowest rank; cand 3 gates, kern 2, leanb 3)

| | cand | kern | leanb |
|---|---:|---:|---:|
| 4K dispatch | 0.947 ms (18.7 GB/s) | 0.934 (−1.3 %) | 0.934 (−1.3 %, 18.9 GB/s) |
| 4K combine | 1.803 (18.8) | 1.764 (−2.2 %) | 1.755 (−2.7 %, 19.3 GB/s) |
| 4K cycle | 2.747 | 2.699 (−1.8 %) | 2.690 (−2.1 %) |
| 16K dispatch | 3.427 (20.7) | 3.414 (−0.4 %) | 3.412 (−0.4 %) |
| 16K combine | 6.913 (19.6) | 6.879 (−0.5 %) | 6.866 (−0.7 %) |

Same picture as the two pairs of the afternoon (§4.4). The headline metric again shows combine +0.5…+3 %
for the flush-less arms (end-skew inflation, §4.4); the wall time is the throughput figure.

### 5.3 Where the lean path's time goes (4K, traced builds, medians over 24 captures)

Dispatch (kernel-relative ms; `trace_timeline.py`, `wire_curve.py`, `receiver_duty.py`):

| Milestone | cand (9900) | kern (9901) | leanb (9902) |
|---|---:|---:|---:|
| Entry barrier end / roles start | 0.118 | 0.093 | 0.094 |
| First packed PUT: scope start → **emitted** | 0.133 → 0.248 | 0.108 → 0.217 | 0.110 → 0.21 |
| 50 % of remote bytes emitted / last PUT emitted | 0.344 / 0.405 | 0.313 / 0.371 | 0.29 / 0.33 |
| Receivers: first remote tail observed | 0.378 | 0.377 | 0.401 |
| Receivers: last remote tail observed | 1.036 | 1.043 | 1.060 |
| Kernel end / CUDA event (incl. copy epilogue) | 1.129 / 1.260 | 1.124 / 1.244 | 1.152 / 1.243 |
| Doorbells / status reads per rank | 1031 / 2444 | 1029 / 2441 | 516 / 1304 |
| CSTATE / fence / combine-flush scopes per gate | 18 528 / 18 528 / 6144 | 18 480 / 18 480 / 0 | 0 / 10 500 / 0 |

- The **receivers are idle 86 % of their role** (256 receiver warps per rank; median wait 0.75 ms of a
  0.87 ms role, processing 0.11 ms): the receive side is not the limit.
- From the first emission to the last observation the NIC delivers 17.7 MB in 0.79–0.84 ms, i.e.
  **21–22.5 GB/s, at the ceiling**. Measured from the first PUT *attempt* the same phase reads 19 GB/s. The
  dispatch wire phase therefore loses nothing to the link; it starts ~0.1 ms late.
- **First-PUT convoy.** Every channel's first PUT (4 rows, 17 KB) spends 102 µs in the transport on every
  block (p90 110): the lock wait is 47 µs median / 97 p90, and for the lock holders the credit check
  (`emit`'s status read of the NIC-written read pointer, event 202) is 86 µs at p90 against 1–3 µs later in
  the kernel. 128 contexts read the status at the same instant after the barrier. The 12-row PUTs later cost
  25 µs (kern) and 15 µs (leanb: no marker, no CSTATE, fence halved); the convoy is identical in all arms.
  Barrier savings (−25 µs) do not reach the end of the kernel because the convoy, not the barrier, sets the
  first emission.

Combine (`combine_prewire.py`):

| Milestone | cand | kern | leanb |
|---|---:|---:|---:|
| Barrier end | 0.108 | 0.086 | 0.076 |
| First local (scale-up) token at a forward warp | 0.227 | 0.203 | 0.205 |
| First packed PUT emitted / 50 % / last | 0.304 / 0.371 / **1.787** | 0.284 / 0.355 / 0.484 | 0.282 / 0.348 / 0.464 |
| First / last channel's remote rows complete (138) | 1.624 / 1.974 | 1.388 / 1.884 | 1.344 / 1.878 |
| Kernel end / CUDA event | 1.976 / 2.062 | 1.886 / 1.966 | 1.880 / 1.963 |

Without the flush the forward warps submit all 512 PUTs by 0.48 ms (cand: 1.79 ms, lock waits 115 ms
summed per capture against 8 ms). The wire phase then runs 0.28 → 1.88 ms: 33.8 MB in 1.60 ms =
**21.1 GB/s**, 0.1 ms over the 1.503 ms bound. What remains is the 0.28 ms before the first PUT: barrier
(0.08, skew up to 0.1 ms between ranks), the first local token at 0.20 (the forward warp waits for the
slowest local peer's scale-up warp), the first 4-row batch at 0.28; plus the 0.08 ms reduce epilogue.

### 5.4 Consequences and the two slices queued on them

1. **Dispatch**: remove the convoy and the first emission moves from 0.21–0.25 to ~0.12 ms; with the NIC
   draining at the ceiling that is −0.1 ms of 0.934 → ≈0.84 ms = 21 GB/s effective, above the target.
   Two candidates:
   - *Fewer channels* (`source-1102-sms32-dbg-v1`, job 3837850): the elastic buffer takes 4 channels per
     SM, so 32 SMs give 128 channels, one per context (no lock sibling), 32 rows per channel (PUTs of 4,
     16 and 12 rows). Zero code. Risk: fewer scale-up/forward warps for the NVLink part.
   - *Cached credits* (`prepare_credit_1102.py`, `source-1102-credit-dbg-v1`, job 3837957): `emit` keeps
     the last NIC read pointer in the context (`tx_rp32_cache`, ABI 4, context 256 bytes) and reads the
     status only when the cached, conservative free count is below 2 + 2·8 units; a stale pointer
     under-counts free slots and never over-counts them (CPU ring model in `test_queue_credit.cc`: slow
     and fast NIC, delayed write-back, wraps, margins 0–16). Host sets `CXI_RP32_UNKNOWN` at open and
     recycle; the queue inventory prints cumulative status reads. Variants `cache-a` (marker-zero + cache)
     and `lean-c` (lean-b + cache). The 10/30 cached-credit candidate stalled at 16K on the delivery-v3
     base without attribution (gate 521), so the ladder includes sustained 16K before any repeat.
     At kernel start the cache still holds the previous kernel's last read, taken when the ring was nearly
     drained, so the first PUTs should emit without any status read.
2. **Combine**: the wire runs at 21 GB/s; the target (1.691 ms) needs −65 µs from the 0.28 ms pre-wire
   phase, which is skew + barrier + the scale-up handoff, i.e. DeepEP-level (start the scale-up copies
   before the barrier completes, or overlap the previous kernel's tail). The credit cache also removes the
   status reads from the forward warps' 512 PUTs (currently 25 µs each under the lock).

### 5.5 32 SMs (job 3837850, nid007481/007666): correct, slower — lever closed

All three ladder gates pass at 32 SMs (irregular stress, 4K FP8/BF16 on five routings, dropped tokens), so
128 channels on 129 contexts is a legal configuration. Wall per iteration against cand and leanb (64 SMs)
on the same pair:

| 4K | cand | leanb | leanb32 |
|---|---:|---:|---:|
| dispatch | 0.953 ms | 0.944 (−0.9 %) | 0.975 (+2.3 %) |
| combine | 1.813 | 1.769 (−2.4 %) | 1.828 (+0.8 %) |
| cycle | 2.763 | 2.707 (−2.0 %) | 2.810 (+1.7 %) |
| 16K combine | 6.931 | 6.886 (−0.7 %) | 7.132 (+2.9 %) |

Halving the channels does not shorten the convoy enough to pay for the halved scale-up/forward
parallelism (the NVLink side of both kernels loses more than the NIC side gains). Together with the 128-SM
and 257-context results of §4.4 this closes the channel-count axis in both directions; the first-PUT cost
has to come out of the transport (cached credits, job 3837957) rather than out of the kernel geometry.

### 5.6 Cached credits (job 3837957, nid006799/006815): correct, status reads gone, time unchanged

Every lean-c gate passes: irregular stress, 4K FP8/BF16 on five routings, dropped tokens and the sustained
16K that stalled the 10/30 candidate, then the 4K/16K repeats. The queue inventory confirms the mechanism:
4 634–4 652 status reads per rank for 4.6 M commands (one per ~1 000 commands, i.e. only when the
conservative count ran below the margin) where the uncached variants read the status for every command.

| 4K, wall per iteration | cand | leanb | leanc |
|---|---:|---:|---:|
| dispatch | 0.947 ms | 0.931 (−1.8 %) | 0.930 (−1.9 %) |
| combine | 1.800 | 1.755 (−2.5 %) | 1.754 (−2.6 %) |
| cycle | 2.748 | 2.687 (−2.2 %) | 2.683 (−2.4 %) |
| 16K dispatch / combine | 3.423 / 6.931 | 3.408 / 6.870 | 3.401 / 6.876 |

So the NIC status read was not what the first PUT waited for: with the read removed the first PUT's
100 µs (and the end-to-end time) stay the same. Either the convoy is in the remaining GPU→host/NIC path
of the first emission (ring stores, system fence, doorbell, under 128 simultaneous first emissions) or it is
off the critical path and the wire itself, or the peer's skew, sets the end. The traced lean-c snapshot
(`source-1102-credit-trace-v1`: lean-c-trace, cache-a-trace, lean-b-trace on one pair) is queued to settle
this: if the first emission moves to ~0.12 ms and the receive end does not, the convoy is irrelevant and
the remaining dispatch loss is the wire rate under this traffic; if the first emission stays at ~0.21 ms,
the 100 µs is in the ring write, fence or doorbell and the trace's 201/209 scopes will say which.

Cached credits are kept as a qualified-by-ladder transport option (`cache-a`, `lean-c`): no measurable
gain at 4K/16K, 99.9 % fewer status reads, ABI 4. They do not go into the candidate until a gain is shown.
