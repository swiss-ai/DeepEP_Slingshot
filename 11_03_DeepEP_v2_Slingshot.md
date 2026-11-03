# 2026-11-03 — DeepEP v2 direct-CXI: release matrix result, the command-ring memory question, ATS ring access

Continues `11_02_DeepEP_v2_Slingshot.md` (§5: first-PUT convoy, closed levers). Target unchanged: 20 GB/s
effective at 4K for dispatch (≤ 0.884 ms) and combine (≤ 1.691 ms) against the 22.5 GB/s payload ceiling.

## 1. Holder job 3835100 (normal partition, nid007560/007561, 07:47–11:47 CET): release matrix passed

All 45 gates PASS (stress, 4K, dropped, sustained-16K ladders for kern/lean-a/lean-b/dbuf, repeats, and the
three trace gates 9800–9802). Wall per iteration, slowest rank (`effective_rate.py ... 'repeat' --ref cand --wall`):

| 4K / 16K | cand | dbuf | kern | lean-a | lean-b |
|---|---:|---:|---:|---:|---:|
| 4K dispatch (fresh) | 0.944 (18.7) | 0.933 (19.0) | 0.934 (18.9) | 0.941 (18.8) | 0.932 (19.0) |
| 4K combine | 1.801 (18.8) | 1.757 (19.2) | 1.762 (19.2) | 1.768 (19.1) | 1.758 (19.2) |
| 4K cycle | 2.744 | 2.692 | 2.697 | 2.709 | 2.690 |
| 16K dispatch (fresh) | 3.423 (20.7) | 3.411 (20.8) | 3.407 (20.8) | 3.388 (20.9) | 3.411 (20.8) |
| 16K combine | 6.929 (19.5) | 6.881 (19.7) | 6.876 (19.7) | 6.880 (19.7) | 6.877 (19.7) |

Fourth node pair with the same numbers as the three debug pairs of 11-02 (lean-b 4K 0.930–0.934 /
1.754–1.759 ms). The matrix qualifies lean-b + `CXI_EP_SKIP_COMBINE_FLUSH=1` + `CXI_EP_LOCAL_SELF_SIGNAL=1`
as the release candidate; the 20 GB/s target is still 50 µs (dispatch) and 65 µs (combine) away.

## 2. Where the command ring lives, and why the first access is slow

Question of the morning: GDAKI (NCCL GIN's IB backend) and NVSHMEM IBGDA keep the work queue and the
completion queue in GPU memory and touch the NIC only through the doorbell BAR; our backend lets the GPU
write the libcxi command queue, which is driver memory. Does the GPU access amount to MMIO, and can the
queue move to GPU memory?

Backend facts (`backend/host/cxi_resources.cc`): `cxil_alloc_cmdq` allocates the TX and triggered
queues; `map(p,bytes,io=false)` registers `cq->cmds32` with `cudaHostRegisterMapped` and, if that is
refused, silently with `cudaHostRegisterIoMemory`; the doorbell page is registered as IO memory by design;
the per-context structs (lock, cursors) are `cudaMalloc`'d GPU memory; the device writes a command as eight
plain 64-bit stores followed by `__threadfence_system()` and reads the NIC-written status word in the ring's
first slot with `ld.acquire.sys`.

Driver and library facts (HewlettPackard/shs-cxi-driver and shs-libcxi on GitHub, read 2026-11-03):
- The queue is kernel memory: `cass_cq.c` `cxi_cq_alloc_buf_internal()` → `alloc_pages_node(GFP_KERNEL|__GFP_ZERO, order)`,
  `dma_map_page`, hardware base `txq_cfg.mem_q_base`. User mapping: `cxi_user_mmap.c` `MMAP_LOGICAL` →
  `remap_pfn_range(..., PAGE_SHARED)` — cacheable for the CPU, but a `VM_PFNMAP` mapping that the CUDA
  driver cannot pin, so plain `cudaHostRegisterMapped` fails and the IO-memory fallback is what the GPU gets
  (to be confirmed by the diagnostic in §3). The doorbell CSR page is `MMAP_PHYSICAL`, write-combining.
- The installed stack (SHS 13.1.0: cray-libcxi 1.0.2 / libcxi.so.1.5.0, cray-cxi-driver 1.0.0, built
  2026-01-27) offers only `CXI_OP_CQ_ALLOC`; `cxi_cq_alloc_opts` has `count, policy, stat_cnt_pool, flags
  (USER, IS_TX, TX_ETHERNET, TX_WITH_TRIG_CMDS), lcid, lpe_cdt_thresh_id`. No user or device memory option.
- Upstream added exactly what we need after that release: driver commit 3656644 (2026-02-18, "Add user
  buffer support for command queues", `CXI_OP_CQ_ALLOC_BUF`, `cxi_cq_alloc_opts_buf {buf, is_host_mem,
  dmabuf_fd, dmabuf_offset}`, host buffer must be physically contiguous), libcxi commit 575b201 (2026-02-18,
  `cxil_alloc_buf_cmdq`, symbol node LIBCXI_1.11), driver commit e1de7f9 "KI-gpu" (2026-04-02) and libcxi
  commit 61173ec "ki cq buffer in device memory" (2026-05-26: "Add support for cq buffer allocated in device
  (gpu) memory"; the user initialises the status region). "KI" is kernel-initiated: HPE is building the
  GPU-resident command queue itself. Tags: `release/shs-14.0.1` (2026-06-12) is the first driver tag dated
  after the feature; libcxi's README places LIBCXI_1.11 in SHS 15.0. Not installable by us; a request to
  CSCS for the SHS release that ships `cxil_alloc_buf_cmdq` is the path to a GDAKI-style queue.
- Interim option on the installed stack: GH200 address translation through the host page tables (ATS).
  If the device reports `cudaDevAttrPageableMemoryAccessUsesHostPageTables=1`, the kernel can dereference
  the ring's host virtual address directly, as cacheable system memory over C2C, with no `cudaHostRegister`
  at all. Tested in §3 (`CXI_RING_ACCESS=ats`).

## 3. Diagnostic and ATS slice (`source-1103-ringdiag-v1`, parent `source-1102-dbuf-v1`, host code only)

`prepare_ringdiag_1103.py`: `CXI_MAP` lines (requested/registered flag, first attempt's error, device
pointer, backing VMA from /proc/self/maps) for the first eight mappings per rank, `CXI_GPU_ADDRESSING`
(pageable access, host page tables, host-register support) at resource open, cumulative `cuda_maps` /
`iomem_fallbacks` in the pool report, `ring=ats|register` in the queue inventory, and the `CXI_RING_ACCESS`
knob (ATS honoured only when the device reports host page tables; otherwise a line says so and the
registration path is used). Gates 9A10 (leanb, diagnostic), 9A11 (ats 4K correctness), 9A12 (ats 4K repeat)
staged into the idle holder 3835100 at 11:05 CET; the full sequence (adds leanb repeats, ats stress and
4K/16K repeats) submitted to the debug partition after the login-node preflight.

Results, gate 9A10 (holder 3835100, nid007560/007561, 11:04–11:06 CET, PASS):
- `CXI_GPU_ADDRESSING gpu=N pageable_memory_access=1 uses_host_page_tables=1 direct_managed_from_host=1
  host_register_supported=1` on every GPU: the nodes run in ATS mode.
- Every command ring took the fallback: `CXI_MAP ... bytes=65536 requested=Mapped registered=IoMemory
  first_rc=1(invalid argument) ... vma=[... rw-s 00040000 00:05 264 /dev/cxi0]`; the doorbell pages are
  `requested=IoMemory registered=IoMemory` (4096 B, same device file); the writeback/diagnostic pages
  (`[heap]`) register plainly. Pool totals per rank: `cuda_maps=798 iomem_fallbacks=266` = 133 channels ×
  6 mappings, with exactly the TX and triggered rings (133 × 2) falling back. TX ring 64 KB = 1024 × 64 B
  (`tx_size32=2048`, first slot the NIC-written status).
- Conclusion: the GPU's eight 64-bit command stores, the system fence and the status loads are uncached
  IO-memory transactions over C2C. That is the mechanism of the first-PUT convoy (and of the 1–3 µs a
  quiet ring access still costs).

Results, gates 9A11/9A12 (ATS ring access, same pair, 11:06–11:09 CET): both PASS (4K correctness over
all routings and dtypes; 4K repeat). `ring=ats` on every queue, `cuda_maps=532 iomem_fallbacks=0` (only the
doorbell, writeback and diagnostic pages are registered). Wall per iteration (slowest rank), same pair:

| 4K | leanb (6 gates) | ats (9A12) | cand (3 gates) |
|---|---:|---:|---:|
| dispatch (fresh) | 0.933 ms (19.0) | 0.932 (−0.1 %) | 0.945 |
| dispatch (cached) | 0.923 (19.2) | 0.923 (0.0 %) | 0.938 |
| combine | 1.758 (19.2) | 1.766 (+0.4 %) | 1.802 |
| cycle | 2.689 | 2.689 (0.0 %) | 2.746 |

Second pair (debug job 3841492, nid007652/007666, 11:18–11:38 CET, `source-1103-ringdiag-v1`, 8 gates all
PASS): the ATS ring passes the irregular stress, 4K correctness and the 4K/16K repeats; wall per iteration
ats vs leanb: 4K dispatch 0.968 ±6.4 % vs 0.933 (+3.8 %, one noisy gate), cached dispatch 0.928 vs 0.923,
combine 1.767 vs 1.765, cycle 2.695 vs 2.695; 16K ats 3.410 / 6.908 ms. ATS is a correct alternative to the
IO-memory registration and not a faster one.

Removing the IO-memory mapping of the rings changes nothing in time. Either the first access is as slow
through ATS (then the cost is the system-memory round trip itself, not the mapping attribute), or the first
PUT became cheap and the kernel end did not follow (the convoy was never on the critical path). The traced
gates A100–A102 (`source-1103-ringdiag-trace-v1`, staged 11:11 CET into the holder) decide.

Results, gates A100/A101 (traced ATS vs registered ring, same pair, 11:10–11:17 CET). Both gates ran to
completion with full traces (72 files each, sizes as the 9802 reference); the holder's own controller
(`source-1102-hold-v1`) marked them FAIL with its inline rule `{200,203,207} <= kinds`, which predates the
knob-aware validator (the skip-flush knob removes 203/207; the same rule paused job 3837687 on 11-02). The
knob-aware validator (`source-1103-ringdiag-trace-v1/runner/validate_trace.py`) passes both offline (rc 0).
`put_split.py`, first PUT of a channel (median / p90, µs, 24 captures):

| first PUT | A101 registered (IO memory) | A100 ATS (host page tables) | lean-b 11-02 (§5.7) |
|---|---:|---:|---:|
| total | 97 / 104 | 107 / 114 | 101 / 109 |
| lock wait (200) | 44 / 91 | 49 / 101 | 47 / 96 |
| credit status load (202) | 3.6 / 81 | 3.3 / 90 | 3.5 / 85 |
| emit: ring store + fence (201) | 3.1 / 3.7 | 3.1 / 3.6 | 3.1 / 3.7 |
| first PUT emitted (rank) | 0.22 ms | 0.21 ms | 0.20 ms |
| last PUT of a channel, total | 15.4 / 17.7 | 15.4 / 17.9 | 15.4 / 17.6 |

**The mapping attribute is not the cause.** Through ATS the ring is ordinary cacheable system memory for the
GPU, and the lock holder's first status load still takes ~90 µs at p90 while later accesses take 3 µs. What
is common to both paths: host DRAM across C2C, system-scope accesses, 128 contexts at the same instant after
the barrier. Two mechanisms remain: contention at a shared point of the GPU→host path (then spreading the
first accesses in time makes each cheap) or a per-context first-touch latency that does not depend on
concurrency. §3.1 tests this with a start stagger. Either way the GPU-resident command queue (upstream
KI CQ, §2) is the structural fix, because it removes the host round trip from the command path altogether.

### 3.1 Start stagger (`source-1103-stagger-trace-v1`, `prepare_stagger_1103.py`, knob `CXI_EP_STAGGER_NS`)

Each dispatch scale-out sender warp sleeps `channel_idx × N ns` right after the entry barrier (N = 400:
0–102 µs, the convoy's length; N = 800: 0–204 µs). Traced gates A110 (400), A111 (800), A112 (control),
A113 (400 + ATS). A110/A111 staged into the holder's last 20 minutes (its controller pauses after every
skip-flush trace gate; resumed between them); the full slice submitted to the debug partition.
Reading: if a late channel's first access costs ~3 µs the cost is contention; if it still costs ~90 µs it is
per-context latency. If the early channels' emission at ~0.11 ms moves the receivers' last observation, the
convoy is on the critical path.

Results, A110 (400 ns) and A111 (800 ns) against A101 (control), holder pair, 11:21–11:26 CET; both pass the
knob-aware validator offline (the holder's controller paused after each, see above). `__nanosleep` saturates
at ~55 µs on this GPU, so the realised stagger is 0–55 µs in both arms (channel bands start at 0.113 /
0.125 / 0.126 / 0.160 ms for 400 ns and 0.114 / 0.164 / 0.164 / 0.165 ms for 800 ns, against 0.107 ms for
every band in the control). `stagger_split.py`, medians over 24 captures:

| first PUT by channel band | control A101 | 400 ns A110 | 800 ns A111 |
|---|---|---|---|
| ch 0–63: total / lock / status load (med, p90 µs) | 97 / 44 / 4 (p90 104 / 91 / 81) | 99 / 54 / 2.7 (p90 109 / 96 / 41) | 96 / 57 / 2.4 (p90 107 / 94 / 6.6) |
| ch 64–127 | 97 / 44 / 4 (p90 104 / 91 / 81) | 67 / 42 / 2.8 (p90 95 / 83 / 7.8) | 29 / 7.8 / 2.7 (p90 82 / 70 / 5.9) |
| ch 128–191 | 98 / 45 / 4 (p90 104 / 91 / 81) | 61 / 25 / 2.6 (p90 69 / 56 / 7.7) | 24 / 8.2 / 2.7 (p90 32 / 18 / 6.0) |
| ch 192–255 | 98 / 45 / 36 (p90 105 / 92 / 81) | 50 / 31 / 2.5 (p90 57 / 44 / 7.7) | 23 / 8.0 / 2.6 (p90 31 / 17 / 5.8) |
| rank first emission | 0.216 ms | 0.205 | 0.203 |
| receivers first / last observation | 0.394 / 1.060 ms (`wire_curve`) | 0.353 / 1.048 | 0.319 / 1.054 |
| kernel end (trace) | 1.166 ms | 1.155 | 1.150 |

Three conclusions:
1. **The ~85 µs status load is contention.** Spread over 55 µs, the lock holder's first status load costs
   6–8 µs at p90 instead of 81–90, on both the IO-memory and (A100) the ATS ring. The cost is the
   simultaneous first system-memory access of 128 contexts, wherever the ring is mapped.
2. **The lock pairs do not separate.** `get_qp_mode` gives each SM two contexts and maps channels (s,0)/(s,2)
   and (s,1)/(s,3) onto them, so the siblings are two global indices apart and the per-channel stagger
   delays them by only 0.8–1.6 µs: the second always waits for the first's whole PUT, which is why the
   lock wait stays 8–57 µs and the band-0 total stays ~97 µs. A stagger that separates siblings (by
   channel-in-SM, not by global index) would be the next refinement if the start mattered.
3. **The start barely matters for the end.** The first arrivals move 40–75 µs earlier, the last observation
   only 6–12 µs and the kernel end 11–16 µs (traced build). From the first emission to the last observation
   the wire phase stays 0.85 ms for 17.7 MB (20.8 GB/s observed), so the dispatch's remaining time is the
   wire phase itself (bidirectional traffic at 92 % of the `cxi_write_bw` ceiling) plus the barrier and
   epilogue, not the convoy. Untraced timing on the same pair (A114, `source-1103-stagger-dbg-v1`, 400 ns,
   4K repeat, PASS) confirms it on the wall clock: dispatch 0.935 ms vs lean-b 0.933 (+0.2 %), cached
   dispatch 0.920 vs 0.923, combine 1.752 vs 1.758, cycle 2.695 vs 2.689. A116 (800 ns, 150 s budget) was
   killed by the harness timeout (returncode 124) during the DeepEP JIT rebuild that every new knob value
   needs: a budgeting error of mine, not a kernel failure; the untraced slice was resubmitted with 300 s for
   the first gate of each knob value (`source-1103-stagger-dbg-v2`, replacing the cancelled 3841684). It
   and the traced slice (job 3841611: A110–A113 on a second pair, incl. stagger + ATS) are queued on the
   debug partition for the record; their monitors mirror into `results/deepep_pipeline_20261101/job-<id>/`.

**Second pair, for the record (jobs 3841611 traced and 3841702 untraced, finished 14:30–15:30 CET).** Same
picture as the holder pair. Untraced wall per iteration (slowest rank), 4K mixed FP8: dispatch_fresh
leanb 0.932 / st400 0.933 / st800 0.944 ms (+1.3 %), combine 1.757 / 1.755 / 1.757, cycle 2.690 / 2.689 /
2.699; st400 at 16K 3.412 / 6.871 (A118, with A117 correctness PASS). Traced, channels 192–255: lock-holder
status load (200) med/p90 47.6/97.0 µs for leanb, 7.8/17.0 with st400, 8.1/16.9 with st800, 37.5/68.6 with
st400 on the ATS ring; first channel start moved from 0.108 to 0.164 (st400) and 0.230 ms (st800) while the
receivers' last observation moved 1.119 → 1.120 → 1.109 and the kernel end 1.158 → 1.157 → 1.147 ms. The
convoy is contention and is off the dispatch critical path; both jobs' gates PASS (knob-aware validator).

### 3.2 Position after the morning

- Dispatch at 4K: 0.932 ms wall = 19.0 GB/s effective. The first-PUT convoy is explained (contention of the
  simultaneous first host-memory accesses, mapping-independent) and shown to be off the critical path; the
  time is the wire phase at 92 % of the measured ceiling plus the barrier (~0.09 ms) and the copy epilogue
  (~0.09 ms). The remaining 50 µs to 20 GB/s are therefore in the wire phase's own efficiency (bidirectional
  traffic, 2 KB packets, 17 KB first PUTs) or in the DeepEP-level fixed phases, not in the transport's start.
- Combine at 4K: 1.758 ms = 19.2 GB/s. Unchanged: the 0.28 ms pre-wire phase (§4) is the lever.
- Transport: ATS ring access and the registered ring are equivalent; a GPU-resident command queue needs the
  SHS release with `cxil_alloc_buf_cmdq` (request to CSCS).
- Jobs today: 3835100 (holder, release matrix + staged gates 9A10–9A12, A100, A101, A110, A111, A114, A116),
  3841492 (ATS ladder, second pair), 3841611 (traced stagger, queued), 3841684 (untraced stagger, queued).
  None of the user's own jobs touched.

## 4. Combine: what the three DeepEP-level levers can give (estimate, not measured)

Pre-wire phase of the traced lean-b combine (11_02 §5.3): barrier end 0.08 ms (8-rank GIN barrier plus
grid sync, mostly inter-rank skew), first local token at a forward warp 0.20 ms (scale-up warps publish a
tail every `kNumScaleupUpdateInterval = 3` tokens at ~8 µs per token, the forward warp waits for the slowest
local peer's tail), first PUT 0.28 ms (first 4-row batch). Wire phase 21.1 GB/s from there. Needed: −65 µs.

1. First scale-up tail after one token (then every 3): −15 to −20 µs on the handoff. Low risk; mirrors
   `CXI_EP_FIRST_INTERVAL` on the dispatch side.
2. Barrier split: `comm::gpu_barrier` already runs the NVLink (scale-up) barrier on SM 0 and the GIN
   (scale-out) barrier on the other SMs in parallel, but everybody then meets at a grid sync, so the
   scale-up warps wait for the slowest remote rank although their NVLink writes only need the four local
   GPUs. Let the scale-up warps start after the NVLink barrier, and gate only the forward warps' first PUT
   on the GIN barrier through a flag written by the SM that completes it. The scale-up stage then overlaps
   the inter-rank skew; the first PUT moves to max(barrier end, first batch ready) ≈ 0.20 ms: −80 µs if
   the wire end follows the start, which it does while the NIC is busy from the first PUT. Moderate change
   in `hybrid_combine.cuh` / `comm.cuh`; the hazard is buffer reuse, which the GIN barrier still protects
   because only the forward warps write remotely, and the scale-up tails cleaned before the barrier are
   local-only state covered by the NVLink barrier.
3. Smaller first batch (2 rows): −20 to −40 µs, to be re-swept on lean-b where a PUT costs 15 µs.
Together they address ~0.1 ms of the 0.28 ms; the combine target needs 65 µs, so they are sufficient on
paper, with lever 2 carrying most of it. Not started; waits on the dispatch-side decision.

## 5. Combine levers, built and run (afternoon; `prepare_combine_1103.py`, snapshots `source-1103-combine-v1` and `source-1103-combine-trace-v1`)

User decision 15:30 CET: concentrate on the combine; run autonomously for ~4 h and submit jobs. Target:
4K combine from 1.758 ms (19.2 GB/s) to ≤ 1.691 ms (20 GB/s), −65 µs, out of the pre-wire stretch of §4.

### 5.1 Baseline decomposition the levers act on (A112-trace-leanb-4k, job 3841611, medians of 24 captures)

| milestone (ms from kernel start) | lean-b |
|---|---:|
| entry barrier end (131) | 0.089 |
| first local token at a forward warp (134) | 0.206 |
| first PUT start / emitted (116) | 0.248 / 0.283 |
| scale-up role end (132) | 0.346 |
| last PUT emitted (116) | 0.463 |
| first / last channel remote-tail arrival (138) | 1.363 / 1.877 |
| kernel end (130) | 1.878 |

All 512 PUTs of a rank are submitted by 0.46 ms and the wire drains until 1.88 ms: the combine is
wire-bound from the first emission on (1.595 ms for the payload whose serialisation bound is 1.503 ms,
94 %). Moving the first emission earlier therefore moves the end by the same amount, unlike the dispatch
convoy of §3.1. Between barrier end and first local token lie 117 µs: the scale-up warps publish their
first tail after `kNumScaleupUpdateInterval = 3` rounds of the linked-list loop, and a round sends one
token to each of the four local peers (TMA load, store over NVLink, ~30 µs per round).

### 5.2 The two new kernel knobs (both archives patched identically; `combine-levers-1103.diff`, 94 added lines)

- `CXI_EP_COMBINE_FIRST_TAIL` (0 = unchanged, 1 used): rounds before the first tail publication, then
  every 3 as before. In `update_tails`: `update_counter == (first_tail_pending ? FIRST_TAIL : 3)`.
- `CXI_EP_COMBINE_SPLIT_BARRIER` (0/1): the entry barrier's halves gate the two roles separately. Same
  operations as `comm::gpu_barrier` (entry grid sync; SM 0 warp 0 does the NVLink `red.add` on the phase
  word and increments the counter; SM 1's first forward warp runs `gin_barrier_wo_local_sync` on context 0
  with 32 threads) but no closing grid sync: every scale-up warp polls the NVLink phase word itself (the
  counter is read before the grid sync so all SMs agree on phase and target), and the forward warps poll a
  module-level flag `cxi_ep_combine_gin_barrier_flag` (reset by the SM-1 forward warp before the grid
  sync, set with `st.release.sys` after its GIN wait) before their first remote PUT (all three PUT paths)
  and before the end signal. Hazards are unchanged: scale-up state (tails, scale-up buffers) is node-local
  and covered by the NVLink barrier; remote writes and the end signal are covered by the GIN barrier.
  Falls back to `gpu_barrier` when either rank dimension is 1 or `kNumSMs < 2`.
- Lever 3 is the existing `CXI_EP_COMBINE_FIRST_BATCH` (4 in the release candidate; 2 and 1 tried).

Compile check on the login node with the JIT's exact flags (`-ccbin g++-14 -std=c++20 ... sm_90a`), kernel
instance of the 4K case (`hybrid_combine_impl<false,true,64,4,4,2,4,4096,4096,256,6,129,...>`): both
knob sets 216 registers, 0 spill bytes, 320-byte stack (same as unpatched).

### 5.3 Gates

`source-1103-combine-v1` (parent ringdiag-v1, DeepEP.tar.gz + nvcc wrapper + ep_benchmark; arms
leanb 0/0/4, tail1 1/0/4, split 0/1/4, both 1/1/4 as FIRST_TAIL/SPLIT_BARRIER/FIRST_BATCH): C100–C102
4K correctness of split/both/tail1 (fp8+bf16, five routings, two seeds), C103 leanb-repeat2, C104–C106
split/both/tail1 repeat2 (each requires its correctness gate), C107–C10A repeat3 of both/leanb/split/tail1.
`source-1103-combine-trace-v1` (parent ringdiag-trace-v1, both archives): T100–T105 traced 4K of leanb,
split, both, bothfb2 (1/1/2), tail1, bothfb1 (1/1/1), one gate per knob set.

### 5.4 Round 1 results (job 3843432, nid007645/007653, 16:06–16:21 CET; all 11 gates PASS)

Correctness of split, both and tail1 at 4K (fp8+bf16, five routings, two seeds): PASS at the first attempt.
Wall per iteration (slowest rank), 4K mixed FP8, two repeat gates per arm:

| arm (FIRST_TAIL/SPLIT/FIRST_BATCH) | combine ms | vs lean-b | dispatch_fresh ms | kernel min / median / max over rank-iterations (µs) |
|---|---:|---:|---:|---|
| leanb 0/0/4 | 1.756 | — | 0.933 | 1669 / 1756 / 1859 |
| tail1 1/0/4 | 1.761 | +0.3 % | 0.933 | 1676 / 1758 / 1895 |
| split 0/1/4 | 1.758 | +0.1 % | 0.935 | 1590 / 1743 / 1973 |
| both 1/1/4 | 1.752 | −0.2 % | 0.935 | 1588 / 1744 / 1937 |

Nothing moves the period. The per-iteration kernel durations tell why the split cannot help here: its best
iterations are 80 µs shorter (1.59 vs 1.67 ms) but the distribution spreads from 1.59 to 1.97 ms and the
period stays at 1.75. The inter-rank skew that the entry barrier absorbs is between the four rail pairs
(each pair has its own two NICs and its own wire end), and every node holds one rank of every pair, so the
node-local NVLink barrier waits for the slowest pair exactly as the global barrier did; the split only lets
the fast pairs drift, which the headline metric (median of the per-iteration rank maximum) shows as +4.4 %.
tail1 alone does not move the first PUT: the first batch still needs four remote rows, and after the first
tail the next comes three rounds later, so the first PUT waits for round 4 instead of round 3.

Traced on the same pair (job 3843434, medians of 24 captures, ms from each rank's kernel start):

| arm | barrier end | first local | first PUT emitted | pre-wire (PUT − barrier) | kernel end |
|---|---:|---:|---:|---:|---:|
| leanb (T100) | 0.072 | 0.200 | 0.275 | 0.194 | 1.875 |
| split (T101) | 0.134 | 0.192 | 0.266 | 0.106 | 1.862 |
| both (T102) | 0.092 | 0.170 | 0.270 | 0.091 | 1.853 |
| bothfb2 (T103) | 0.169 | 0.164 | 0.226 | 0.040 | 1.798 |
| tail1 (T104) | 0.082 | 0.177 | 0.277 | 0.197 | 1.870 |

With the early tail and a two-row first batch the first PUT follows the GIN barrier by 40 µs instead of
194 µs. Whether the period follows is the round-2 question (job 3843685: tail1fb2, tail1fb1, bothfb2
untraced). Steady-state detail from the lean-b captures: the first token reaches a forward channel 50 µs
after the barrier in the first iteration after a host sync but 140 µs in steady state, uniformly over all
channels; later bursts keep the same ~45 µs spacing (three rounds of ~15 µs). The first three rounds of
the scale-up warps are what is slow in steady state, not the rounds after.

Trace-capture caveat found while aligning the eight ranks on the GPU global timer: the three captured
iterations of a traced gate are 1.4–1.6 s apart (the trace readout pauses the loop), so iterations 1 and 2
start from an idle GPU and NIC, and only iteration 0 (right after the warm-up loop) reflects a warm start:
there the first token reaches a forward channel 50 µs after the barrier and the first PUT is emitted 115 µs
after it (lean-b), against 140 and 200 µs in the paused captures. Steady-state numbers must come from the
untraced repeats; traces give the ordering and the warm iteration 0. Within a node the four ranks' kernel
ends spread by 35–75 µs per iteration (the four rail pairs' wire ends differ), which is the skew the next
barrier absorbs. The traced job's T104 (tail1) ended with rank 0 exiting 1 after all correctness, timing
and trace files were written (compiler reports not copied, launcher log empty); the untraced tail1 gates
C102/C106/C10A passed, so this is treated as a trace-infrastructure flake. T105 (bothfb1) did not run: the
paused job was cancelled at 16:35 to free the debug slot for round 2 (job 3843685).

### 5.5 Round 2 (job 3843685, new pair nid007646/007655, 17:24 CET): first-batch sweep with the early tail

Correctness at 4K (fp8+bf16, five routings, two seeds): tail1fb2, tail1fb1 and bothfb2 PASS. Wall per
iteration (slowest rank), 4K mixed FP8, one repeat gate each (repeat3 gates follow after a resume):

| arm (FIRST_TAIL/SPLIT/FIRST_BATCH) | combine ms | vs lean-b | kernel min / median / max (µs) |
|---|---:|---:|---|
| leanb 0/0/4 | 1.775 (19.0 GB/s) | — | 1673 / 1767 / 1928 |
| tail1fb2 1/0/2 | 1.742 (19.4 GB/s) | −1.9 % (−33 µs) on this gate; see below | 1661 / 1739 / 1824 |
| tail1fb1 1/0/1 | 6.702 | +278 % | 5670 / 6638 / 7717 |

After the resume the repeat3 gates ran (D17 tail1fb2 1.765, D18 tail1fb1 6.691, D1A leanb 1.760 ms), so
per gate: leanb 1.775 / 1.760, tail1fb2 1.742 / 1.765 ms — the gate-to-gate spread on this pair (±15 µs,
against ±2 µs on the morning's pair) is as large as the difference, and the dispatch+combine cycle is equal
(2.692 / 2.695 vs 2.707 / 2.674). Over both repeats tail1fb2 is −0.8 % (1.753 vs 1.767, −14 µs): a gain of at
most a few tens of µs, not yet distinguishable from pair noise; round 3 adds three more repeats of each on
a third pair plus 16K. The one-row first batch is pathological: exact results but 4× the time,
bimodal at 5.9–6.2 and 7.1–7.6 ms per iteration; dispatch unchanged. This is the known 128-byte PUT-alignment
cliff of our GPU-issued path (11_01 log, alignment probe: a combine row is 8256 bytes = 64 mod 128, so a
PUT starting at an odd row is 4.3× slower): a one-row first batch makes every channel's second batch start
at row 1. Two rows (and the qualified four) keep every batch boundary on an even row. fb1 is excluded; the
same explains the 1.9× / 3.4× of first interval 1 / 2 on the dispatch side recorded on 11-01. The bothfb2 repeat gate (D16) hit the inner 90 s
test timeout on this pair (D15 before it needed 115 s wall) and paused the job; resumed at 17:38 with
bothfb2-repeat3 dropped and 200 s timeouts for the remaining tail1fb2 / tail1fb1 / lean-b repeat3 gates.

### 5.6 Round 3 (job 3843956, pair nid007481/007499, 17:44–17:59 CET; nine gates, all PASS)

A quiet pair (lean-b gates within ±3 µs). Wall per iteration, mixed FP8, slowest rank:

| arm | 4K combine (gates) | vs lean-b | 4K cycle | 16K combine | 16K dispatch |
|---|---|---:|---:|---:|---:|
| leanb 0/0/4 | 1.758, 1.759, 1.754, 1.756 | — | 2.692 | 6.860 (19.7 GB/s) | 3.404 |
| tail1fb2 1/0/2 | 1.741, 1.740, 1.746 | **−16 µs (−0.9 %)** | 2.675 (−17 µs) | 6.857 | 3.404 |
| fb2 0/0/2 | 1.753 | −4 µs | 2.689 | — | — |

The early tail with the two-row first batch is a consistent gain of 16 µs at 4K (19.4 GB/s) and nothing at
16K; the two-row batch alone gives nothing, so the gain is the early tail made usable by the smaller first
batch. Dispatch unchanged in every arm (0.931–0.938 ms, pair noise). The round-2 pair's −33 / +5 µs pair of
gates is bracketed by this: real, small.

### 5.7 Position at 18:00 CET and what is left

Of the 65 µs the 4K combine needs for 20 GB/s, the pre-wire levers deliver 16 µs. The reasons, all measured
today: the split barrier cannot shorten anything because the inter-rank skew lives between the four rail
pairs and every node holds one rank of every pair (§5.4); the early tail alone cannot move the first PUT
while the first batch needs four rows (§5.4); a one-row first batch is pathological (§5.5); once the first
PUT follows the barrier by ~40 µs (traced, §5.4), the rest of the period is the barrier latency and skew
wait for the slowest pair plus the slowest pair's wire phase at 94–97 % of the bidirectional ceiling, and
the epilogue. Per iteration the four pairs' wire ends spread by 35–75 µs (§5.4 global-timer alignment), so
every iteration pays roughly the mean-to-max of that spread in the barrier of the next.

Remaining levers, none started: (1) the wire phase itself — PUT size pattern and the per-pair spread (the
dispatch's wire efficiency is at 92 %, the combine's at 94–97 %); (2) overlapping the next iteration's
scale-up stage with the current wire phase would need the combine to be split across two kernels or
pipelined across micro-batches, a DeepEP-level restructuring; (3) the epilogue kernel between combines
(~50 µs of the period) could be fused into the consumer. Candidate status: lean-b with the two kernel knobs
remains the qualified release (release matrix §1); `CXI_EP_COMBINE_FIRST_TAIL=1` with
`CXI_EP_COMBINE_FIRST_BATCH=2` is exact on two pairs (correctness fp8+bf16, five routings, two seeds,
twice) and 16 µs faster at 4K, but has not been through the irregular-token stress or a release matrix;
`CXI_EP_COMBINE_SPLIT_BARRIER` is exact but useless in this topology and stays at 0.
