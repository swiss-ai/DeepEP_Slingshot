#!/usr/bin/env python3
"""Combine pre-wire levers (2026-11-03 afternoon): two DeepEP-level knobs on the hybrid combine kernel.

Traced lean-b combine at 4K (11_02 log §5.3, 11_03 log §4; A112 of job 3841611): entry barrier end
0.089 ms, first local token at a forward warp 0.206 ms, first PUT emitted 0.283 ms, wire from there at
~21 GB/s. The 65 us between the release candidate (1.758 ms) and the 20 GB/s target (1.691 ms) sit in
this pre-wire stretch; a third lever, CXI_EP_COMBINE_FIRST_BATCH, already exists (prepare_first_batch.py).

CXI_EP_COMBINE_FIRST_TAIL (0 = unchanged): rounds of the scale-up loop before the first tail
publication; afterwards every kNumScaleupUpdateInterval (3) rounds as before. A round sends one token to
each local peer, so today the forward warps' first token waits for three rounds of NVLink stores.

CXI_EP_COMBINE_SPLIT_BARRIER (0/1): the entry barrier's two halves gate the two warp roles separately.
The scale-up warps write only the local peers (NVLink TMA stores and tail words) and wait for the NVLink
barrier alone, on the phase word; the forward warps wait for the rail (GIN) barrier only, before their
first remote PUT and before the end signal, through a flag set by the SM-1 forward warp that completes
it and reset before the entry grid sync. The barrier operations themselves are those of
comm::gpu_barrier (entry grid sync, red.add on the NVLink phase word from SM 0, GIN signal/wait on
context 0 from SM 1); only the closing grid sync is gone. Hazards are unchanged: scale-up state (tails,
scale-up buffers) is local to the node and covered by the NVLink barrier; the remote writes and the end
signal into the rail peer's workspace are covered by the GIN barrier.
"""
import sys, tarfile, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'pipeline_v1'))
from package import replace  # noqa: E402

BARRIER_OLD = '''    comm::gpu_barrier<true, kNumScaleoutRanks, kNumScaleupRanks,
                      kNumSMs, kNumThreads, kNumQPs, kNumTimeoutCycles, comm::kHybridCombineTag0, false, true, true>(
        gin, workspace_layout, scaleout_rank_idx, scaleup_rank_idx, sm_idx, thread_idx);
'''
BARRIER_NEW = '''    constexpr bool kSplitBarrier = CXI_EP_COMBINE_SPLIT_BARRIER and kNumScaleupRanks > 1 and kNumScaleoutRanks > 1 and kNumSMs >= 2;
    [[maybe_unused]] int nvl_phase = 0;
    [[maybe_unused]] int nvl_target = 0;
    if constexpr (kSplitBarrier) {
        // CXI_EP_COMBINE_SPLIT_BARRIER: the operations of comm::gpu_barrier (entry grid sync, NVLink
        // red.add on the phase word from SM 0, GIN signal/wait on context 0 from SM 1) without the closing
        // grid sync. The scale-up warps wait for the NVLink barrier on the phase word themselves (they write
        // local peers only); the forward warps wait for the GIN barrier through the flag before their first
        // remote PUT and before the end signal. The phase word is read before the grid sync so that every
        // SM sees the same phase as SM 0, which increments the counter after the sync.
        const int nvl_status = static_cast<int>((*workspace_layout.get_nvl_barrier_counter_ptr()) & 3);
        nvl_phase = nvl_status & 1;
        nvl_target = (nvl_status >> 1) ? 0 : kNumScaleupRanks;
        if (sm_idx == 1 and thread_idx == kNumScaleupWarps * 32)
            cxi_ep_combine_gin_barrier_flag = 0;
        cooperative_groups::this_grid().sync();
        if (sm_idx == 0 and warp_idx == 0) {
            if (lane_idx < kNumScaleupRanks)
                ptx::red_add_rel_sys(gin.get_sym_ptr<ncclTeamTagLsa>(workspace_layout.get_nvl_barrier_signal_ptr(nvl_phase), lane_idx),
                                     (nvl_status >> 1) ? -1 : 1);
            __syncwarp();
            if (lane_idx == 0)
                atomicAdd(workspace_layout.get_nvl_barrier_counter_ptr(), 1);
        }
        if (sm_idx == 1 and warp_idx == kNumScaleupWarps) {
            comm::gin_barrier_wo_local_sync<kNumScaleoutRanks, 1, 32, kNumQPs, kNumTimeoutCycles, ncclTeamTagRail, comm::kHybridCombineTag0, false>(
                gin.nccl_dev_comm, scaleout_rank_idx, scaleup_rank_idx, 0, lane_idx);
            __syncwarp();
            if (lane_idx == 0)
                ptx::st_release_sys(&cxi_ep_combine_gin_barrier_flag, 1);
        }
    } else {
        comm::gpu_barrier<true, kNumScaleoutRanks, kNumScaleupRanks,
                          kNumSMs, kNumThreads, kNumQPs, kNumTimeoutCycles, comm::kHybridCombineTag0, false, true, true>(
            gin, workspace_layout, scaleout_rank_idx, scaleup_rank_idx, sm_idx, thread_idx);
    }
'''
SCALEUP_WAIT = '''        if constexpr (kSplitBarrier) {
            // Wait for the NVLink barrier only: this role writes the local peers only.
            if (lane_idx == 0) {
                const int* nvl_signal_ptr = workspace_layout.get_nvl_barrier_signal_ptr(nvl_phase);
                comm::timeout_while<kNumTimeoutCycles>([=](const bool& is_last_check) {
                    if (ptx::ld_acquire_sys<int>(nvl_signal_ptr) == nvl_target)
                        return true;
                    if (is_last_check)
                        printf("DeepEP combine (split NVLink barrier) timeout, scale-out: %d, scale-up: %d, channel: %d, phase: %d, target: %d, signal: %d\\n",
                               scaleout_rank_idx, scaleup_rank_idx, channel_idx, nvl_phase, nvl_target, ptx::ld_acquire_sys<int>(nvl_signal_ptr));
                    return false;
                });
            }
            __syncwarp();
        }
'''
FORWARD_HELPER = '''        [[maybe_unused]] bool gin_barrier_seen = not kSplitBarrier;
        const auto wait_gin_barrier = [&]() {
            if constexpr (kSplitBarrier) {
                if (gin_barrier_seen)
                    return;
                if (lane_idx == 0) {
                    comm::timeout_while<kNumTimeoutCycles>([=](const bool& is_last_check) {
                        if (ptx::ld_acquire_sys<int>(&cxi_ep_combine_gin_barrier_flag) == 1)
                            return true;
                        if (is_last_check)
                            printf("DeepEP combine (split GIN barrier) timeout, scale-out: %d, scale-up: %d, channel: %d\\n",
                                   scaleout_rank_idx, scaleup_rank_idx, channel_idx);
                        return false;
                    });
                }
                __syncwarp();
                gin_barrier_seen = true;
            }
        };
'''


def prepare(snapshot, archives=('DeepEP.tar.gz', 'DeepEP-trace.tar.gz')):
    out = Path(snapshot)
    for archive in archives:
      with tempfile.TemporaryDirectory() as d:
        ep = Path(d)
        with tarfile.open(out / archive) as a: a.extractall(ep)
        f = ep / 'deep_ep/include/deep_ep/impls/hybrid_combine.cuh'
        # Knob definitions (anchor present in the plain and the traced archive alike).
        replace(f, 'static_assert(CXI_EP_SKIP_COMBINE_FLUSH == 0 || CXI_EP_SKIP_COMBINE_FLUSH == 1);\n',
                '''static_assert(CXI_EP_SKIP_COMBINE_FLUSH == 0 || CXI_EP_SKIP_COMBINE_FLUSH == 1);
#ifndef CXI_EP_COMBINE_FIRST_TAIL
#define CXI_EP_COMBINE_FIRST_TAIL 0
#endif
static_assert(CXI_EP_COMBINE_FIRST_TAIL >= 0 && CXI_EP_COMBINE_FIRST_TAIL <= 64, "scale-up rounds before the first tail, 0 = regular interval");
#ifndef CXI_EP_COMBINE_SPLIT_BARRIER
#define CXI_EP_COMBINE_SPLIT_BARRIER 0
#endif
static_assert(CXI_EP_COMBINE_SPLIT_BARRIER == 0 || CXI_EP_COMBINE_SPLIT_BARRIER == 1);
''')
        # The GIN-barrier flag: one JIT module per kernel instance, so one flag per instance. Declared
        # unconditionally (a non-dependent name must resolve even in the discarded constexpr branch).
        replace(f, 'namespace deep_ep::elastic {\n', '''namespace deep_ep::elastic {

// CXI_EP_COMBINE_SPLIT_BARRIER: 1 once the SM-1 forward warp has completed the rail (GIN) barrier of the
// current launch; reset to 0 before the entry grid sync of every launch.
__device__ int cxi_ep_combine_gin_barrier_flag = 0;
''')
        replace(f, BARRIER_OLD, BARRIER_NEW)
        # Scale-up role: wait for the NVLink barrier on the phase word.
        anchor = '''        // Adjust registers
        if constexpr (kAdjustRegisters)
            ptx::warpgroup_reg_dealloc<kNumRegistersForScaleupWarps>();
'''
        replace(f, anchor, anchor + SCALEUP_WAIT)
        # Forward role: the GIN-barrier wait helper, then its four call sites (every remote PUT path and
        # the end signal).
        anchor = '''        // Adjust registers
        if constexpr (kAdjustRegisters)
            ptx::warpgroup_reg_alloc<kNumRegistersForForwardWarps>();
'''
        replace(f, anchor, anchor + FORWARD_HELPER)
        replace(f, '                if (packed_first_j >= 0 and ptx::elect_one_sync()) {\n',
                '''                if (packed_first_j >= 0)
                    wait_gin_barrier();
                if (packed_first_j >= 0 and ptx::elect_one_sync()) {
''')
        replace(f, '            if (last_src_scaleout_rank_idx >= 0 and ptx::elect_one_sync()) {\n',
                '''            if (last_src_scaleout_rank_idx >= 0 and last_src_scaleout_rank_idx != scaleout_rank_idx)
                wait_gin_barrier();
            if (last_src_scaleout_rank_idx >= 0 and ptx::elect_one_sync()) {
''')
        replace(f, '''stored_src_scaleup_rank_idx >= 0);  // Deduplicate w.r.t. scaleup rank index if expanded mode is disabled
                if (ptx::elect_one_sync()) {
''', '''stored_src_scaleup_rank_idx >= 0);  // Deduplicate w.r.t. scaleup rank index if expanded mode is disabled
                if (src_scaleout_rank_idx != scaleout_rank_idx)
                    wait_gin_barrier();
                if (ptx::elect_one_sync()) {
''')
        replace(f, '''        if (lane_idx < kNumScaleoutRanks) {
            // Update remote tails
''', '''        wait_gin_barrier();
        if (lane_idx < kNumScaleoutRanks) {
            // Update remote tails
''')
        # First scale-up tail after CXI_EP_COMBINE_FIRST_TAIL rounds instead of kNumScaleupUpdateInterval.
        replace(f, '        int update_counter = 0;\n', '''        int update_counter = 0;
        static_assert(CXI_EP_COMBINE_FIRST_TAIL <= kNumScaleupUpdateInterval, "the first tail comes no later than the regular interval");
        [[maybe_unused]] bool first_tail_pending = CXI_EP_COMBINE_FIRST_TAIL > 0;
''')
        replace(f, '            if (finish or update_counter == kNumScaleupUpdateInterval) {\n',
                '            if (finish or update_counter == (first_tail_pending ? CXI_EP_COMBINE_FIRST_TAIL : kNumScaleupUpdateInterval)) {\n')
        replace(f, '''                update_counter = 0;
            }
            __syncwarp();
        };
''', '''                update_counter = 0;
                first_tail_pending = false;
            }
            __syncwarp();
        };
''')
        with tarfile.open(out / archive, 'w:gz') as a: a.add(ep, arcname='.')
    anchor = "    args=['-DCXI_EP_SKIP_COMBINE_FLUSH='+str(skip_flush),'-DCXI_EP_LOCAL_SELF_SIGNAL='+str(self_signal)]+args\n"
    replace(out / 'backend/tests/nvcc_wrapper.py', anchor, anchor +
            "    first_tail=int(os.environ.get('CXI_EP_COMBINE_FIRST_TAIL','0')); split_barrier=int(os.environ.get('CXI_EP_COMBINE_SPLIT_BARRIER','0'))\n"
            "    assert 0<=first_tail<=3 and split_barrier in (0,1)\n"
            "    args=['-DCXI_EP_COMBINE_FIRST_TAIL='+str(first_tail),'-DCXI_EP_COMBINE_SPLIT_BARRIER='+str(split_barrier)]+args\n")
    replace(out / 'backend/tests/ep_benchmark.py', "    case['local_self_signal']=int(os.environ.get('CXI_EP_LOCAL_SELF_SIGNAL','0'))\n",
            "    case['local_self_signal']=int(os.environ.get('CXI_EP_LOCAL_SELF_SIGNAL','0'))\n"
            "    case['combine_first_tail']=int(os.environ.get('CXI_EP_COMBINE_FIRST_TAIL','0'))\n"
            "    case['combine_split_barrier']=int(os.environ.get('CXI_EP_COMBINE_SPLIT_BARRIER','0'))\n")
    return out


if __name__ == '__main__':
    prepare(sys.argv[1], tuple(sys.argv[2:]) or ('DeepEP.tar.gz', 'DeepEP-trace.tar.gz')); print('prepared', sys.argv[1])
