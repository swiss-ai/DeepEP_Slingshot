"""Private instrumentation; not applied to the ordinary benchmark sources."""
from pathlib import Path
import shutil
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[3]
def edit(p,old,new,count=1):
    t=p.read_text();assert t.count(old)==count,(p,old[:90],t.count(old),count);p.write_text(t.replace(old,new))
def prepare_ep(ep):
    # Reuse the established dispatch/host boundaries, excluding old backend edits.
    source=(ROOT/'tools/cxi_gin/experiments/trace_v1/prepare.py').read_text()
    source=source[:source.index("    p=headers/'cxi_primitives.cuh'")]
    # Both the search and replacement strings in the reused trace generator
    # must preserve the compile-time guard around the original per-row PUT.
    source=source.replace(
        'if (stored_dst_slot_idx >= 0 and stored_dst_scaleout_rank_idx != scaleout_rank_idx)',
        'if (!CXI_EP_PACK_ROWS and stored_dst_slot_idx >= 0 and stored_dst_scaleout_rank_idx != scaleout_rank_idx)')
    scope={'__file__':str(ROOT/'tools/cxi_gin/experiments/trace_v1/prepare.py')}
    exec(compile(source,'dispatch_instrumentation','exec'),scope)
    scope['prepare'](ep,None)
    packed=ep/'deep_ep/include/deep_ep/impls/hybrid_dispatch.cuh'
    edit(packed,'                    if (lane_idx != scaleout_rank_idx && pending > 0) {',
         '                    if (lane_idx != scaleout_rank_idx && pending > 0) {\n'
         '                        ep_trace::Scope trace_packed_put(113,\n'
         '                            (uint64_t(channel_idx) << 32) | uint32_t(lane_idx),\n'
         '                            (uint64_t(stored_old_scaleout_tail) << 32) | uint32_t(pending));')
    edit(packed,'                gin.red_add_rel<ncclTeamTagRail>(ptr, signaled_tail - old_signaled_tail, lane_idx);',
         '                gin.red_add_rel<ncclTeamTagRail>(ptr, signaled_tail - old_signaled_tail, lane_idx);\n'
         '                ep_trace::finish(114,trace_signal.start,\n'
         '                    uint64_t(channel_idx) | (uint64_t(lane_idx) << 16) | (uint64_t(finish_flag) << 32),\n'
         '                    (uint64_t(stored_old_scaleout_tail) << 32) | uint32_t(stored_scaleout_tail));')
    edit(packed,'            ep_trace::finish(105,trace_arrival,channel_idx,recv_scaleout_rank_idx);',
         '            ep_trace::finish(105,trace_arrival,channel_idx,recv_scaleout_rank_idx);\n'
         '            const auto trace_consumed_tail = ptx::exchange(stored_scaleout_old_tail_idx, recv_scaleout_rank_idx);\n'
         '            const auto trace_available_tail = ptx::exchange(stored_scaleout_tail_idx, recv_scaleout_rank_idx);\n'
         '            ep_trace::finish(115,ep_trace::begin(lane_idx==0),\n'
         '                (uint64_t(channel_idx) << 32) | uint32_t(recv_scaleout_rank_idx),\n'
         '                (uint64_t(trace_consumed_tail) << 32) | uint32_t(trace_available_tail));')
    base=ep/'deep_ep/include/deep_ep/impls'
    for name in ['hybrid_dispatch.cuh','dispatch_copy_epilogue.cuh','hybrid_combine.cuh','combine_reduce_epilogue.cuh']:
        # DeepEP's JIT include hasher accepts only canonical angle includes.
        p=base/name;p.write_text('#include <deep_ep/impls/device_trace.cuh>\n'+p.read_text())
    shutil.copyfile(HERE/'device_trace.cuh',base/'device_trace.cuh')
    p=base/'hybrid_combine.cuh'
    edit(p,'    // Global parallel barriers for scale-out subteam and scale-up subteam',
         '    ep_trace::Scope trace_kernel(130,0,0,lane_idx==0);\n    const auto trace_initial=ep_trace::begin(lane_idx==0);\n    // Global parallel barriers for scale-out subteam and scale-up subteam')
    edit(p,'    // Adjust register count at certain cases','    ep_trace::finish(131,trace_initial);\n    // Adjust register count at certain cases')
    edit(p,'    if (warp_idx < kNumScaleupWarps) {','    if (warp_idx < kNumScaleupWarps) {\n        ep_trace::Scope trace_scaleup(132,0,0,lane_idx==0);')
    edit(p,'        const auto forward_warp_idx =','        ep_trace::Scope trace_forward(133,0,0,lane_idx==0);\n        const auto forward_warp_idx =')
    edit(p,'            // Wait all tails to arrive','            const auto trace_local=ep_trace::begin(lane_idx==0);\n            // Wait all tails to arrive')
    edit(p,'            // Increase received count','            ep_trace::finish(134,trace_local,channel_idx,src_token_global_idx);\n            const auto trace_reduce=ep_trace::begin(lane_idx==0);\n            // Increase received count')
    edit(p,'        // Issue the last RDMA','        // Issue the last RDMA')
    edit(p,'                last_send_token_buffer_ptr = send_token_buffer.get_base_ptr();\n            }',
         '                last_send_token_buffer_ptr = send_token_buffer.get_base_ptr();\n            }\n            ep_trace::finish(135,trace_reduce,channel_idx,src_token_global_idx);')
    edit(p,'                ptx::tma_store_wait();\n\n                // Issue only if not local rank',
         '                const auto trace_tma=ep_trace::begin();\n                ptx::tma_store_wait();\n                ep_trace::finish(136,trace_tma,channel_idx,last_src_scaleout_rank_idx);\n\n                // Issue only if not local rank')
    edit(p,'        // Update, wait and clean','        const auto trace_finish=ep_trace::begin(lane_idx==0);\n        // Update, wait and clean')
    edit(p,'        // Wait tail arrival','        ep_trace::finish(137,trace_finish,channel_idx);\n        const auto trace_remote=ep_trace::begin(lane_idx==0);\n        // Wait tail arrival')
    edit(p,'    // No barrier at epilogue','    ep_trace::finish(139,ep_trace::begin(lane_idx==0));\n    // No barrier at epilogue')
    edit(p,'        __syncwarp();\n    }\n\n    ep_trace::finish(139',
         '        __syncwarp();\n        ep_trace::finish(138,trace_remote,channel_idx);\n    }\n\n    ep_trace::finish(139')
    pc=base/'hybrid_combine.cuh'
    edit(pc,'                if (packed_first_j >= 0 and ptx::elect_one_sync()) {\n                    ptx::tma_store_wait();\n                    gin.put<ncclTeamTagRail>(',
         '                if (packed_first_j >= 0 and ptx::elect_one_sync()) {\n                    ptx::tma_store_wait();\n'
         '                    ep_trace::Scope trace_packed_combine(116,\n'
         '                        (uint64_t(channel_idx) << 32) | uint32_t(packed_peer),\n'
         '                        (uint64_t(packed_first_j) << 32) | uint32_t(packed_last_j));\n'
         '                    gin.put<ncclTeamTagRail>(')
    edit(pc,'                    // Record only for the (now unused) single-row path bookkeeping.\n                    last_src_scaleout_rank_idx = -1;\n                    continue;',
         '                    ep_trace::finish(135,trace_reduce,channel_idx,src_token_global_idx);\n'
         '                    last_src_scaleout_rank_idx = -1;\n                    continue;')
    p=base/'combine_reduce_epilogue.cuh'
    edit(p,'    // Will block until the main combine kernel',
         '    ep_trace::Scope trace_epilogue(140,0,0,lane_idx==0);\n    const auto trace_dependency=ep_trace::begin(lane_idx==0);\n    // Will block until the main combine kernel')
    edit(p,'    cudaGridDependencySynchronize();','    cudaGridDependencySynchronize();\n    ep_trace::finish(141,trace_dependency);')

def prepare_headers(d):
    shutil.copyfile(HERE/'device_trace.cuh',d/'device_trace.cuh')
    p=d/'cxi_primitives.cuh';t=p.read_text();p.write_text('#include "device_trace.cuh"\n'+t)
    edit(p,'  if(c.abi_version!=CXI_GIN_ABI_VERSION)', '  ep_trace::Scope trace_lock(200,(uint64_t)&c);\n  if(c.abi_version!=CXI_GIN_ABI_VERSION)')
    edit(p,'  for(unsigned i=0;i<8;i++)c.tx_queue', '  ep_trace::Scope trace_emit(201,(uint64_t)&c,transfer);\n  for(unsigned i=0;i<8;i++)c.tx_queue')
    if 'while(true)' in t:
        edit(p,'  while(true) {','  const auto trace_capacity=ep_trace::begin();\n  while(true) {')
        edit(p,'  ep_trace::Scope trace_emit(201', '  ep_trace::finish(202,trace_capacity,(uint64_t)&c,c.tx_wp32);\n  ep_trace::Scope trace_emit(201')
    else:
        edit(p,'  uint64_t start=clock64();uint32_t status;', '  const auto trace_capacity=ep_trace::begin();\n  uint64_t start=clock64();uint32_t status;')
        edit(p,'  if(transfer)c.posted++;return true;', '  ep_trace::finish(202,trace_capacity,(uint64_t)&c,c.tx_wp32);\n  if(transfer)c.posted++;return true;')
    edit(p,'  if(c.completed==c.posted)return true;', '  ep_trace::Scope trace_flush(203,(uint64_t)&c,c.posted-c.completed);\n  if(c.completed==c.posted)return true;')
    edit(p,'    uint64_t value;', '    const auto trace_writeback=ep_trace::begin();\n    uint64_t value;')
    edit(p,'    if((value>>48)&127)', '    ep_trace::finish(207,trace_writeback,(uint64_t)&c,c.posted);\n    if((value>>48)&127)')
    edit(p,'    uint32_t status;', '    const auto trace_consume=ep_trace::begin();\n    uint32_t status;')
    edit(p,'    if(c.completed>c.posted)', '    ep_trace::finish(208,trace_consume,(uint64_t)&c,c.completed);\n    if(c.completed>c.posted)')
    edit(p,'  if(!region(c,dst,peer,dstoff,bytes)', '  ep_trace::Scope trace_payload(204,(uint64_t)&c,bytes);\n  if(!region(c,dst,peer,dstoff,bytes)')
    edit(p,'  if(!region(c,dst,peer,off,8)', '  ep_trace::Scope trace_signal(205,(uint64_t)&c,peer);\n  if(!region(c,dst,peer,off,8)')
    p=d/'gin_cxi.cuh'
    edit(p,'      auto& c=nccl::gin::cxi::context(ctx);nccl::gin::cxi::require(cxi_gin::acquire(c));',
         '      ep_trace::Scope trace_put(206,ctx.contextId,bytes);\n      auto& c=nccl::gin::cxi::context(ctx);nccl::gin::cxi::require(cxi_gin::acquire(c));')

    p=d/'cxi_primitives.cuh'
    edit(p,'  if(!c.tx_unpublished)return;',
         '  if(!c.tx_unpublished)return;\n  ep_trace::Scope trace_publish(209,(uint64_t)&c,c.tx_unpublished);')
    edit(p,'  if(!w)return true;',
         '  if(!w)return true;\n  ep_trace::Scope trace_delivery(210,(uint64_t)&c,c.pending_peer);')
    edit(p,'  uint64_t words[8];cxi_build_fence_command(words);',
         '  ep_trace::Scope trace_hw_fence(211,(uint64_t)&c,c.posted);\n  uint64_t words[8];cxi_build_fence_command(words);')
    edit(p,'  uint64_t words[8]{};auto* st=(c_cstate_cmd*)words;',
         '  ep_trace::Scope trace_cstate(212,(uint64_t)&c,peer);\n  uint64_t words[8]{};auto* st=(c_cstate_cmd*)words;')
    edit(p,'  uint64_t words[8]{};auto* hdr=(c_idc_hdr*)words;auto* amo=(c_small_amo_payload*)(words+2);',
         '  ep_trace::Scope trace_atomic(213,(uint64_t)&c,amount);\n  uint64_t words[8]{};auto* hdr=(c_idc_hdr*)words;auto* amo=(c_small_amo_payload*)(words+2);')
    edit(p,'  const auto trace_capacity=ep_trace::begin();',
         '  uint32_t trace_rp32=0;\n  const auto trace_capacity=ep_trace::begin();')
    edit(p,'    uint32_t rp32=(status&65535)*2;',
         '    uint32_t rp32=(status&65535)*2;\n    trace_rp32=rp32;')
    edit(p,'  ep_trace::finish(202,trace_capacity,(uint64_t)&c,c.tx_wp32);',
         '  ep_trace::finish(202,trace_capacity,(uint64_t)&c,c.tx_wp32);\n'
         '  ep_trace::finish(214,ep_trace::begin(),(uint64_t)&c,(uint64_t(trace_rp32)<<32)|uint32_t(c.tx_wp32));')
