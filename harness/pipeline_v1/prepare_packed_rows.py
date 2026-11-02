"""EP8-only dispatch staging experiment; transport and notification cadence unchanged.

Each channel owns a disjoint, tightly sized slice of the existing send allocation.
Remote rows are packed into that slice and submitted immediately before the
existing tail notification. There is exactly one remote scale-out peer in EP8.
This prototype is ordinary-build only; existing per-row traces would mislabel
the relocated PUT, so instrumentation must be adapted separately before tracing.
"""
import tarfile
import tempfile
from pathlib import Path
from package import replace


HELPER = '''#pragma once
#ifdef __CUDACC__
#define CXI_PACK_HD __host__ __device__
#else
#define CXI_PACK_HD
#endif
namespace deep_ep { namespace elastic {
// Sum the actual capacities of preceding strided channels, without padding.
CXI_PACK_HD constexpr int packed_channel_base(int max_tokens, int channels, int channel) {
    return channel * (max_tokens / channels) +
           (channel < max_tokens % channels ? channel : max_tokens % channels);
}
}}
#undef CXI_PACK_HD
'''


def prepare(snapshot):
    out = Path(snapshot)
    with tempfile.TemporaryDirectory() as tmp:
        ep = Path(tmp)
        with tarfile.open(out / 'DeepEP.tar.gz') as archive:
            archive.extractall(ep)
        helper = ep / 'deep_ep/include/deep_ep/common/cxi_packed_channel.cuh'
        helper.write_text(HELPER)
        header = ep / 'deep_ep/include/deep_ep/impls/hybrid_dispatch.cuh'
        replace(header, '#pragma once', '''#pragma once
#ifndef CXI_EP_PACK_ROWS
#define CXI_EP_PACK_ROWS 0
#endif
static_assert(CXI_EP_PACK_ROWS == 0 || CXI_EP_PACK_ROWS == 1);
#include <deep_ep/common/cxi_packed_channel.cuh>''')
        replace(header, '    constexpr int kNumExpertsPerRank = kNumExperts / kNumRanks;',
                '''    static_assert(!CXI_EP_PACK_ROWS || kNumScaleoutRanks == 2,
                  "Packed rows prototype requires exactly two scale-out nodes");
    constexpr int kNumExpertsPerRank = kNumExperts / kNumRanks;''')
        replace(header, '        int stored_scaleout_tail = 0, stored_old_scaleout_tail = 0;',
                '''        const int packed_source_base = packed_channel_base(kNumMaxTokensPerRank, kNumChannels, channel_idx);
        int stored_scaleout_tail = 0, stored_old_scaleout_tail = 0;''')
        replace(header, '                const auto signaled_tail = math::pack2<int, int64_t>(finish_flag, stored_scaleout_tail);',
                '''                if constexpr (CXI_EP_PACK_ROWS) {
                    // The same rows become visible at the same progress boundary.
                    // All their TMA stores completed before entering this lambda.
                    const int pending = stored_scaleout_tail - stored_old_scaleout_tail;
                    if (lane_idx != scaleout_rank_idx && pending > 0) {
                        gin.put<ncclTeamTagRail>(
                            scaleout_recv_buffer.get_token_buffer(stored_old_scaleout_tail).get_base_ptr(),
                            scaleout_send_buffer.get_token_buffer(packed_source_base + stored_old_scaleout_tail).get_base_ptr(),
                            pending * tma_buffer.get_num_bytes<false>(), lane_idx,
                            ncclGinOptFlagsAggregateRequests);
                    }
                }
                const auto signaled_tail = math::pack2<int, int64_t>(finish_flag, stored_scaleout_tail);''')
        replace(header, '            // Wait TMA arrival and issue the TMA store into send buffer',
                '''            int packed_remote_slot = 0;
            if constexpr (CXI_EP_PACK_ROWS) {
                // Every lane participates in the shuffle. The result is used only
                // when this token has a remote destination; otherwise it may be -1.
                packed_remote_slot = packed_source_base +
                    ptx::exchange(stored_scaleout_tail, 1 - scaleout_rank_idx) - 1;
            }

            // Wait TMA arrival and issue the TMA store into send buffer''')
        replace(header, 'ptx::tma_store_1d(scaleout_send_buffer.get_token_buffer(token_idx).get_base_ptr(),',
                'ptx::tma_store_1d(scaleout_send_buffer.get_token_buffer(CXI_EP_PACK_ROWS ? packed_remote_slot : token_idx).get_base_ptr(),')
        replace(header, '                if (scaleout_rank_mask ^ (1 << scaleout_rank_idx)) {',
                '''                if (CXI_EP_PACK_ROWS ? (scaleout_rank_mask & ~(1u << scaleout_rank_idx)) :
                                        (scaleout_rank_mask ^ (1 << scaleout_rank_idx))) {''')
        replace(header, '            if (stored_dst_slot_idx >= 0 and stored_dst_scaleout_rank_idx != scaleout_rank_idx) {',
                '            if (!CXI_EP_PACK_ROWS and stored_dst_slot_idx >= 0 and stored_dst_scaleout_rank_idx != scaleout_rank_idx) {')
        with tarfile.open(out / 'DeepEP.tar.gz', 'w:gz') as archive:
            archive.add(ep, arcname='.')
    (out / 'runner/cxi_packed_channel.cuh').write_text(HELPER)
    wrapper = out / 'backend/tests/nvcc_wrapper.py'
    replace(wrapper, "    interval=int(os.environ.get('CXI_EP_UPDATE_INTERVAL','3'))", '''    packed=int(os.environ.get('CXI_EP_PACK_ROWS','0'))
    assert packed in (0,1)
    args=['-DCXI_EP_PACK_ROWS='+str(packed)]+args
    interval=int(os.environ.get('CXI_EP_UPDATE_INTERVAL','3'))''')
    replace(out / 'backend/tests/ep_benchmark.py', "    case['progress_update_interval']=", 
            "    case['packed_remote_rows']=bool(int(os.environ.get('CXI_EP_PACK_ROWS','0')))\n    case['progress_update_interval']=")
    benchmark = out / 'backend/tests/ep_benchmark.py'
    replace(benchmark, "    xb=torch.randn(n,h,dtype=torch.bfloat16,device='cuda')", '''    drop_every=int(os.environ.get('CXI_EP_DROP_EVERY','0'))
    assert drop_every >= 0
    if drop_every:
        idx[::drop_every]=-1
        w[::drop_every]=0
    xb=torch.randn(n,h,dtype=torch.bfloat16,device='cuda')''')
    replace(benchmark, "        tokens_per_node=4*n,global_tokens=ep*n,ep=ep,rank=rank,seed=seed,dispatch_dtype=dtype,",
            "        tokens_per_node=4*n,global_tokens=ep*n,ep=ep,rank=rank,seed=seed,dispatch_dtype=dtype,drop_every=drop_every,")
    replace(benchmark, "    remote=(owners//4!=rank//4).any(1).sum().item()",
            "    remote=((owners>=0)&(owners//4!=rank//4)).any(1).sum().item()")
    replace(out / 'runner/node.sh', 'ulimit -c 0', '''ulimit -c 0
if [ "${CXI_DEVICE_TRACE:-0}" != 0 ]; then
  printf 'Packed-row prototype has no qualified relocated-PUT tracing implementation\\n' >&2
  exit 2
fi''')
    validator = out / 'runner/validate_gate.py'
    replace(validator, "        ep = base / 'ep'", '''
        packed = env.get('CXI_EP_PACK_ROWS')
        if packed is not None:
            require(packed in ('0','1'), 'invalid packed-row mode')
            reports = list((Path(destination)/'compiler-reports').rglob('*.txt'))
            require(reports and all('-DCXI_EP_PACK_ROWS='+packed+' ' in p.read_text() for p in reports),
                    'packed-row compiler evidence missing or mismatched')
        ep = base / 'ep' ''')
    replace(validator, "            keys = {(r['model'], r['tokens_per_gpu'], r['dispatch_dtype'], r['routing'], r['seed']) for r in rows}",
            '''            if packed is not None:
                require(all(r.get('packed_remote_rows') is bool(int(packed)) for r in rows),
                        'packed-row rank evidence missing or mismatched')
                require(all(r.get('drop_every') == int(env.get('CXI_EP_DROP_EVERY','0')) for r in rows),
                        'dropped-token routing test mismatch')
            keys = {(r['model'], r['tokens_per_gpu'], r['dispatch_dtype'], r['routing'], r['seed']) for r in rows}''')
