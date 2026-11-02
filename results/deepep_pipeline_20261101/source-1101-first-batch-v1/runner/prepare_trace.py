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
    scope={'__file__':str(ROOT/'tools/cxi_gin/experiments/trace_v1/prepare.py')}
    exec(compile(source,'dispatch_instrumentation','exec'),scope)
    scope['prepare'](ep,None)
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
