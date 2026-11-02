"""Patch NEW private source/header copies, never the tested baseline release."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil

HERE=Path(__file__).resolve().parent
def edit(path,old,new,count=1):
    text=path.read_text()
    assert text.count(old)==count,(str(path),old[:100],text.count(old),count)
    path.write_text(text.replace(old,new))

def prepare(ep,headers):
    host=ep/'csrc/elastic/buffer.hpp'
    shutil.copyfile(HERE/'host_trace.hpp',host.parent/'host_trace.hpp')
    host.write_text('#include "host_trace.hpp"\n'+host.read_text())
    api=ep/'csrc/python_api.cpp'
    edit(api,'    m.doc() =', '''    m.def("_ep_trace_host_enable", [](bool enabled) {ep_trace_host::enable(enabled);});
    m.def("_ep_trace_host_read", []() {
        ep_trace_host::active=false; pybind11::list result;
        for (const auto& e:ep_trace_host::events) result.append(pybind11::make_tuple(e.name,e.ns));
        return result;
    });
    m.doc() =''')
    edit(host,'        // Cached mode must have responding handles','        ep_trace_host::mark("dispatch_enter");\n        // Cached mode must have responding handles')
    # Both dispatch and combine share stream dependency helpers; only mark the
    # first occurrence to keep this host trace explicitly dispatch-scoped.
    text=host.read_text();needle='        const auto compute_stream = stream_control_prologue(previous_event, allocate_on_comm_stream, async_with_compute_stream);'
    assert text.count(needle)==2
    text=text.replace(needle,'        ep_trace_host::mark("stream_prologue_begin");\n'+needle+'\n        ep_trace_host::mark("stream_prologue_end");',1);host.write_text(text)
    for old,new in [
        ('        launch_dispatch(x.data_ptr(), sf_ptr,','        ep_trace_host::mark("hybrid_launch_begin");\n        launch_dispatch(x.data_ptr(), sf_ptr,'),
        ('        // Received token counters','        ep_trace_host::mark("hybrid_launch_end");\n        ep_trace_host::mark("receive_counts_begin");\n        // Received token counters'),
        ('        // Allocate received tensors','        ep_trace_host::mark("receive_counts_end");\n        ep_trace_host::mark("output_allocation_begin");\n        // Allocate received tensors'),
        ('        // Launch copy kernels with full SMs','        ep_trace_host::mark("output_allocation_end");\n        ep_trace_host::mark("copy_launch_begin");\n        // Launch copy kernels with full SMs'),
        ('        // Stream control\n        const auto event = stream_control_epilogue(\n            {x, sf,','        ep_trace_host::mark("copy_launch_end");\n        ep_trace_host::mark("stream_epilogue_begin");\n        // Stream control\n        const auto event = stream_control_epilogue(\n            {x, sf,')]:edit(host,old,new)
    # Place the return boundary immediately before dispatch's final return.
    text=host.read_text();start=text.index('ep_trace_host::mark("stream_epilogue_begin")');end=text.index('\n    combine(',start)
    part=text[start:end];idx=part.index('        return ')
    part=part[:idx]+'        ep_trace_host::mark("stream_epilogue_end");\n        ep_trace_host::mark("dispatch_exit");\n'+part[idx:]
    host.write_text(text[:start]+part+text[end:])

    d=ep/'deep_ep/include/deep_ep/impls/hybrid_dispatch.cuh'
    edit(d,'    // Global parallel barriers','    ep_trace::Scope trace_kernel(100, 0, 0, lane_idx == 0);\n    const auto trace_initial=ep_trace::begin(lane_idx == 0);\n    // Global parallel barriers')
    edit(d,'    // The golden layout','    ep_trace::finish(101,trace_initial);\n    // The golden layout')
    edit(d,'        // Assign shared memory','        ep_trace::Scope trace_notify(102,0,0,lane_idx==0);\n        // Assign shared memory')
    edit(d,'        const int scaleout_warp_idx =','        ep_trace::Scope trace_scaleout(103,0,0,lane_idx==0);\n        const int scaleout_warp_idx =')
    edit(d,'        const int forward_warp_idx =','        ep_trace::Scope trace_forward(104,0,0,lane_idx==0);\n        const int forward_warp_idx =')
    edit(d,'                gin.red_add_rel<ncclTeamTagRail>(ptr, signaled_tail - old_signaled_tail, lane_idx);',
         '                ep_trace::Scope trace_signal(110,channel_idx,lane_idx);\n                gin.red_add_rel<ncclTeamTagRail>(ptr, signaled_tail - old_signaled_tail, lane_idx);')
    edit(d,'            // Wait for this rank to have data (or finish)','            const auto trace_arrival=ep_trace::begin(lane_idx==0);\n            // Wait for this rank to have data (or finish)')
    edit(d,'            // Process one chunk from the current rank','            ep_trace::finish(105,trace_arrival,channel_idx,recv_scaleout_rank_idx);\n            // Process one chunk from the current rank')
    edit(d,'                // Read top-k indices','                const auto trace_token=ep_trace::begin(lane_idx==0);\n                const auto trace_src=lane_idx==0 ? *tma_buffer.get_src_token_global_idx_ptr() : 0;\n                // Read top-k indices')
    edit(d,'                // Record metadata at forward','                ep_trace::finish(108,trace_token,trace_src,channel_idx);\n                // Record metadata at forward')
    edit(d,'                    const auto dst_ptr = gin.get_sym_ptr<ncclTeamTagLsa>(',
         '                    ep_trace::Scope trace_nvl(109,stored_dst_scaleup_rank_idx,*tma_buffer.get_src_token_global_idx_ptr());\n                    const auto dst_ptr = gin.get_sym_ptr<ncclTeamTagLsa>(')
    edit(d,'            // Load top-k indices and weights', '            const auto trace_pack=ep_trace::begin(lane_idx==0);\n            // Load top-k indices and weights')
    edit(d,'            // Preload the next token (overlapping with the IBGDA issues)', '            ep_trace::finish(112,trace_pack,token_idx,channel_idx);\n            // Preload the next token (overlapping with the IBGDA issues)')
    edit(d,'            if (stored_dst_slot_idx >= 0 and stored_dst_scaleout_rank_idx != scaleout_rank_idx) {\n                gin.put',
         '            if (stored_dst_slot_idx >= 0 and stored_dst_scaleout_rank_idx != scaleout_rank_idx) {\n                ep_trace::Scope trace_put(111,token_idx,stored_dst_scaleout_rank_idx);\n                gin.put')
    edit(d,'    // Scale-up barrier to ensure data arrival','    const auto trace_final=ep_trace::begin(lane_idx==0);\n    // Scale-up barrier to ensure data arrival')
    edit(d,'    // Trigger the copy epilogue kernel','    ep_trace::finish(106,trace_final);\n    // Trigger the copy epilogue kernel')
    c=ep/'deep_ep/include/deep_ep/impls/dispatch_copy_epilogue.cuh'
    edit(c,'    // Will block until the main dispatch kernel',
         '    ep_trace::Scope trace_copy(120,0,0,lane_idx==0);\n    const auto trace_dep=ep_trace::begin(lane_idx==0);\n    // Will block until the main dispatch kernel')
    edit(c,'    cudaGridDependencySynchronize();','    cudaGridDependencySynchronize();\n    ep_trace::finish(121,trace_dep);')

    p=headers/'cxi_primitives.cuh'
    shutil.copyfile(HERE/'device_trace.cuh',headers/'device_trace.cuh')
    p.write_text('#include "device_trace.cuh"\n'+p.read_text())
    edit(p,'  if(c.abi_version!=CXI_GIN_ABI_VERSION)', '  ep_trace::Scope trace_lock(200,(uint64_t)&c);\n  if(c.abi_version!=CXI_GIN_ABI_VERSION)')
    edit(p,'  for(unsigned i=0;i<8;i++)c.tx_queue', '  ep_trace::Scope trace_emit(201,(uint64_t)&c,transfer);\n  for(unsigned i=0;i<8;i++)c.tx_queue')
    edit(p,'  uint64_t start=clock64();uint32_t status;', '  const auto trace_consumption=ep_trace::begin();\n  uint64_t start=clock64();uint32_t status;')
    edit(p,'  if(transfer)c.posted++;return true;', '  ep_trace::finish(202,trace_consumption,(uint64_t)&c);\n  if(transfer)c.posted++;return true;')
    edit(p,'  if(c.completed==c.posted)return true;', '  ep_trace::Scope trace_flush(203,(uint64_t)&c,c.posted-c.completed);\n  if(c.completed==c.posted)return true;')
    edit(p,'  if(!region(c,dst,peer,dstoff,bytes)', '  ep_trace::Scope trace_payload(204,bytes,peer);\n  if(!region(c,dst,peer,dstoff,bytes)')
    edit(p,'  if(!region(c,dst,peer,off,8)', '  ep_trace::Scope trace_add(205,(uint64_t)&c,peer);\n  if(!region(c,dst,peer,off,8)')
    # Full duration of a GIN put, including lock, optional completion and signal.
    g=headers/'gin_cxi.cuh'
    edit(g,'      auto& c=nccl::gin::cxi::context(ctx);nccl::gin::cxi::require(cxi_gin::acquire(c));',
         '      ep_trace::Scope trace_gin(206,bytes,ctx.contextId);\n      auto& c=nccl::gin::cxi::context(ctx);nccl::gin::cxi::require(cxi_gin::acquire(c));')
    return {'source':str(ep),'headers':str(headers),'scope':'dispatch GPU stages + host boundaries + direct CXI operations; no transport algorithm change'}

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('source',type=Path);p.add_argument('headers',type=Path);a=p.parse_args()
    result=prepare(a.source,a.headers)
    result['patched_sha256']={str(x):hashlib.sha256(x.read_bytes()).hexdigest() for x in [a.source/'csrc/elastic/buffer.hpp',a.source/'csrc/python_api.cpp',a.headers/'cxi_primitives.cuh',a.headers/'gin_cxi.cuh']}
    print(json.dumps(result,indent=2))
