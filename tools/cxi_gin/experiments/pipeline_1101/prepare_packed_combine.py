"""EP8 combine packing: channel-major scale-out receive layer, contiguous per-channel send slices,
one PUT per batch of consecutive reduced rows. Transport unchanged.

Facts this relies on (verified in the pinned bd1e1669 hybrid kernels):
- Dispatch channel c on rank (s,u) owns tokens t with t % kNumChannels == c and sends them, in
  increasing t, to channel slice c of rank (s',u); the dispatch forwarder appends forward
  metadata in slot order, so the combine forward warp of channel c sees remote-origin tokens of
  channel c in increasing t.
- With kAllowMultipleReduction and kUseScaleoutRankLayout (2 scale-out ranks <= top-k), the
  scale-out receive buffer has one layer per scale-out rank; the remote writer owns layer
  `scaleout_rank_idx`, the local bypass owns its own layer, and the epilogue reads layer r for
  token t only when t has an expert on scale-out rank r. Unwritten slots are never read.
Permutation: slot(t) = packed_channel_base(kNumMaxTokensPerRank, kNumChannels, t % kNumChannels)
             + t / kNumChannels. Consecutive same-channel tokens map to consecutive slots.
"""
import tarfile, tempfile
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'pipeline_v1'))
from package import replace  # noqa: E402

HELPER = '''#pragma once
#ifdef __CUDACC__
#define CXI_PACKC_HD __host__ __device__
#else
#define CXI_PACKC_HD
#endif
namespace deep_ep { namespace elastic {
// Channel-major slot of token `t` inside one scale-out receive layer. Bijective on
// [0, max_tokens): channel c = t % channels owns slots [base(c), base(c) + count(c)).
CXI_PACKC_HD constexpr int packed_combine_slot(int max_tokens, int channels, int t) {
    const int c = t % channels;
    return c * (max_tokens / channels) + (c < max_tokens % channels ? c : max_tokens % channels) + t / channels;
}
}}
#undef CXI_PACKC_HD
'''


def prepare(snapshot):
    out = Path(snapshot)
    with tempfile.TemporaryDirectory() as tmp:
        ep = Path(tmp)
        with tarfile.open(out / 'DeepEP.tar.gz') as a: a.extractall(ep)
        (ep / 'deep_ep/include/deep_ep/common/cxi_packed_combine.cuh').write_text(HELPER)
        h = ep / 'deep_ep/include/deep_ep/impls/hybrid_combine.cuh'
        replace(h, '#pragma once', '''#pragma once
#ifndef CXI_EP_PACK_COMBINE
#define CXI_EP_PACK_COMBINE 0
#endif
#ifndef CXI_EP_COMBINE_BATCH
#define CXI_EP_COMBINE_BATCH 16
#endif
#ifndef CXI_EP_PACK_COMBINE_CHANNELS
#define CXI_EP_PACK_COMBINE_CHANNELS 256
#endif
static_assert(CXI_EP_PACK_COMBINE == 0 || CXI_EP_PACK_COMBINE == 1);
static_assert(CXI_EP_COMBINE_BATCH >= 1 && CXI_EP_COMBINE_BATCH <= 64);
#include <deep_ep/common/cxi_packed_combine.cuh>''')
        # Static guards: only the configuration this prototype was designed for.
        replace(h, '''    // Utils
    const auto sm_idx = static_cast<int>(blockIdx.x);
    const auto thread_idx = static_cast<int>(threadIdx.x);
    const auto warp_idx = ptx::get_warp_idx();
    const auto lane_idx = ptx::get_lane_idx();
    constexpr bool kDoExpandedSend = not kAllowMultipleReduction and kUseExpandedLayout;''',
'''    // Utils
    const auto sm_idx = static_cast<int>(blockIdx.x);
    const auto thread_idx = static_cast<int>(threadIdx.x);
    const auto warp_idx = ptx::get_warp_idx();
    const auto lane_idx = ptx::get_lane_idx();
    constexpr bool kDoExpandedSend = not kAllowMultipleReduction and kUseExpandedLayout;
    static_assert(!CXI_EP_PACK_COMBINE || (kAllowMultipleReduction && kUseScaleoutRankLayout && !kUseExpandedLayout),
                  "Packed combine prototype requires multiple-reduction rank layout without expansion");
    static_assert(!CXI_EP_PACK_COMBINE || kNumScaleoutRanks == 2, "Packed combine prototype requires exactly two scale-out nodes");
    static_assert(!CXI_EP_PACK_COMBINE || kNumChannels == CXI_EP_PACK_COMBINE_CHANNELS,
                  "Packed combine channel count must match the epilogue's compile-time constant");
    // The batch limit is an upper bound on a run of consecutive rows; small token counts have
    // fewer rows per channel than the limit and simply never trigger an early flush.''')
        # Forward warp: batch state and a batch flush replacing the deferred single-row PUT.
        replace(h, '''        const auto flush_last_tma_and_issue_rdma = [&]() {
            if (last_src_scaleout_rank_idx >= 0 and ptx::elect_one_sync()) {
                ptx::tma_store_wait();

                // Issue only if not local rank
                if (last_src_scaleout_rank_idx != scaleout_rank_idx) {''',
'''        // Packed combine: consecutive remote-origin rows of this channel are staged at their
        // channel-local position j of the send slice and land at the same relative position of
        // the channel-major receive layer, so one PUT covers [first_j, last_j].
        int packed_first_j = -1, packed_last_j = -1, packed_peer = -1;
        void* packed_dst_base = nullptr; void* packed_src_base = nullptr;
        const auto flush_packed_batch = [&](const bool& final_batch) {
            if constexpr (CXI_EP_PACK_COMBINE) {
                if (packed_first_j >= 0 and ptx::elect_one_sync()) {
                    ptx::tma_store_wait();
                    gin.put<ncclTeamTagRail>(
                        packed_dst_base, packed_src_base,
                        (packed_last_j - packed_first_j + 1) * token_layout.get_num_bytes<false>(),
                        packed_peer, final_batch ? 0 : ncclGinOptFlagsAggregateRequests);
                }
                __syncwarp();
                packed_first_j = -1;
            }
        };
        const auto flush_last_tma_and_issue_rdma = [&]() {
            if constexpr (CXI_EP_PACK_COMBINE) {
                // Only release the shared TMA staging buffer; the PUT is issued per batch.
                if (ptx::elect_one_sync())
                    ptx::tma_store_wait();
                __syncwarp();
                return;
            }
            if (last_src_scaleout_rank_idx >= 0 and ptx::elect_one_sync()) {
                ptx::tma_store_wait();

                // Issue only if not local rank
                if (last_src_scaleout_rank_idx != scaleout_rank_idx) {''')
        replace(h, '''                const auto recv_token_buffer = scaleout_recv_buffer.get_rank_buffer(scaleout_recv_buffer_rank_idx).get_token_buffer(src_token_idx);
                const auto send_token_buffer = src_scaleout_rank_idx == scaleout_rank_idx ?
                    recv_token_buffer :
                    scaleout_send_buffer.get_token_buffer(i);

                // Write into scale-out send buffer or local rank recv buffer bypass
                if (ptx::elect_one_sync()) {
                    ptx::tma_store_1d(send_token_buffer.get_base_ptr(), tma_buffer.get_base_ptr(),
                                    token_layout.get_num_bytes<false>());
                    ptx::tma_store_commit();
                }
                __syncwarp();
''',
'''                if constexpr (CXI_EP_PACK_COMBINE) {
                    const int packed_slot = packed_combine_slot(kNumMaxTokensPerRank, kNumChannels, src_token_idx);
                    const auto recv_token_buffer = scaleout_recv_buffer.get_rank_buffer(scaleout_recv_buffer_rank_idx).get_token_buffer(packed_slot);
                    if (src_scaleout_rank_idx == scaleout_rank_idx) {
                        // Local bypass: same channel-major position in this rank's own layer.
                        if (ptx::elect_one_sync()) {
                            ptx::tma_store_1d(recv_token_buffer.get_base_ptr(), tma_buffer.get_base_ptr(),
                                              token_layout.get_num_bytes<false>());
                            ptx::tma_store_commit();
                        }
                        __syncwarp();
                    } else {
                        const int j = src_token_idx / kNumChannels;
                        const bool contiguous = packed_first_j >= 0 and packed_peer == src_scaleout_rank_idx and j == packed_last_j + 1;
                        EP_DEVICE_ASSERT(src_token_idx % kNumChannels == channel_idx);
                        if (not contiguous) {
                            flush_packed_batch(false);
                            packed_first_j = j; packed_peer = src_scaleout_rank_idx;
                            packed_dst_base = recv_token_buffer.get_base_ptr();
                            packed_src_base = scaleout_send_buffer.get_token_buffer(j).get_base_ptr();
                        }
                        packed_last_j = j;
                        if (ptx::elect_one_sync()) {
                            ptx::tma_store_1d(scaleout_send_buffer.get_token_buffer(j).get_base_ptr(), tma_buffer.get_base_ptr(),
                                              token_layout.get_num_bytes<false>());
                            ptx::tma_store_commit();
                        }
                        __syncwarp();
                        if (packed_last_j - packed_first_j + 1 >= CXI_EP_COMBINE_BATCH)
                            flush_packed_batch(false);
                    }
                    // Record only for the (now unused) single-row path bookkeeping.
                    last_src_scaleout_rank_idx = -1;
                    continue;
                }
                const auto recv_token_buffer = scaleout_recv_buffer.get_rank_buffer(scaleout_recv_buffer_rank_idx).get_token_buffer(src_token_idx);
                const auto send_token_buffer = src_scaleout_rank_idx == scaleout_rank_idx ?
                    recv_token_buffer :
                    scaleout_send_buffer.get_token_buffer(i);

                // Write into scale-out send buffer or local rank recv buffer bypass
                if (ptx::elect_one_sync()) {
                    ptx::tma_store_1d(send_token_buffer.get_base_ptr(), tma_buffer.get_base_ptr(),
                                    token_layout.get_num_bytes<false>());
                    ptx::tma_store_commit();
                }
                __syncwarp();
''')
        replace(h, '''        // Issue the last RDMA
        if constexpr (kAllowMultipleReduction)
            flush_last_tma_and_issue_rdma();''',
'''        // Issue the last RDMA
        if constexpr (kAllowMultipleReduction) {
            flush_last_tma_and_issue_rdma();
            flush_packed_batch(true);
        }''')
        e = ep / 'deep_ep/include/deep_ep/impls/combine_reduce_epilogue.cuh'
        replace(e, '#pragma once', '''#pragma once
#ifndef CXI_EP_PACK_COMBINE
#define CXI_EP_PACK_COMBINE 0
#endif
#ifndef CXI_EP_PACK_COMBINE_CHANNELS
#define CXI_EP_PACK_COMBINE_CHANNELS 256
#endif
#include <deep_ep/common/cxi_packed_combine.cuh>''')
        replace(e, '''    // Read from buffers and do reduction
    for (int token_idx = global_warp_idx; token_idx < num_combined_tokens; token_idx += kNumWarps * kNumSMs) {''',
'''    static_assert(!CXI_EP_PACK_COMBINE || (kAllowMultipleReduction && kUseRankLayout && !kUseExpandedLayout && kNumScaleoutRanks == 2),
                  "Packed combine epilogue requires the two-node multiple-reduction rank layout");
    // Read from buffers and do reduction
    for (int token_idx = global_warp_idx; token_idx < num_combined_tokens; token_idx += kNumWarps * kNumSMs) {
        // Packed combine stores token t of every layer at its channel-major slot.
        const int comm_token_idx = CXI_EP_PACK_COMBINE ?
            packed_combine_slot(kNumMaxTokensPerRank, CXI_EP_PACK_COMBINE_CHANNELS, token_idx) : token_idx;''')
        replace(e, '''                    comm_buffer.get_rank_buffer(slot_idx).get_token_buffer(token_idx).get_base_ptr());''',
                   '''                    comm_buffer.get_rank_buffer(slot_idx).get_token_buffer(comm_token_idx).get_base_ptr());''')
        replace(e, '''                        .get_token_buffer(token_idx).get_topk_weights_ptr() + lane_idx;''',
                   '''                        .get_token_buffer(comm_token_idx).get_topk_weights_ptr() + lane_idx;''')
        with tarfile.open(out / 'DeepEP.tar.gz', 'w:gz') as a: a.add(ep, arcname='.')
    (out / 'runner/cxi_packed_combine.cuh').write_text(HELPER)
    # Compiler wrapper: defines from the environment; channel constant from SM count.
    replace(out / 'backend/tests/nvcc_wrapper.py', "    packed=int(os.environ.get('CXI_EP_PACK_ROWS','0'))",
'''    packc=int(os.environ.get('CXI_EP_PACK_COMBINE','0')); batch=int(os.environ.get('CXI_EP_COMBINE_BATCH','16'))
    assert packc in (0,1) and 1 <= batch <= 64
    channels=4*int(os.environ.get('CXI_EP_SMS','64'))
    args=['-DCXI_EP_PACK_COMBINE='+str(packc),'-DCXI_EP_COMBINE_BATCH='+str(batch),'-DCXI_EP_PACK_COMBINE_CHANNELS='+str(channels)]+args
    packed=int(os.environ.get('CXI_EP_PACK_ROWS','0'))''')
    replace(out / 'backend/tests/ep_benchmark.py', "    case['packed_remote_rows']=",
        "    case['packed_combine']=bool(int(os.environ.get('CXI_EP_PACK_COMBINE','0')))\n    case['combine_batch']=int(os.environ.get('CXI_EP_COMBINE_BATCH','16'))\n    case['packed_remote_rows']=")
    v = out / 'runner/validate_gate.py'
    replace(v, "        packed = env.get('CXI_EP_PACK_ROWS')", '''        packc = env.get('CXI_EP_PACK_COMBINE')
        if packc is not None:
            require(packc in ('0','1'), 'invalid packed-combine mode')
            reports = list((Path(destination)/'compiler-reports').rglob('*.txt'))
            require(reports and all('-DCXI_EP_PACK_COMBINE='+packc+' ' in p.read_text() for p in reports),
                    'packed-combine compiler evidence missing or mismatched')
        packed = env.get('CXI_EP_PACK_ROWS')''')
    replace(v, "            if packed is not None:", '''            if packc is not None:
                require(all(r.get('packed_combine') is bool(int(packc)) for r in rows),
                        'packed-combine rank evidence missing or mismatched')
            if packed is not None:''')


if __name__ == '__main__':
    prepare(sys.argv[1]); print('prepared', sys.argv[1])
