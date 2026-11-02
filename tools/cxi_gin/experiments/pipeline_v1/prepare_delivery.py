"""Experimental same-endpoint delivery batching over bounded publication.

Each registered window has its own CXI PID. Keep one destination-window/peer epoch
per context, and flush it before switching endpoints. A DC marker repeats the last
payload byte using its still-live source IOVA; it must not target a scratch MR.
"""
from pathlib import Path
from package import replace


def prepare(snapshot):
    root=Path(snapshot)/'backend'
    abi=root/'include/cxi_gin_abi.h'
    replace(abi,'#define CXI_GIN_ABI_VERSION 2','#define CXI_GIN_ABI_VERSION 3')
    replace(abi,'  uint64_t tx_doorbells, tx_commands; // cumulative diagnostics, updated under lock',
            '''  uint64_t tx_doorbells, tx_commands; // cumulative diagnostics, updated under lock
  CxiWindow* pending_dst;
  uint64_t pending_local_addr, pending_remote_offset;
  uint32_t pending_lac, pending_peer;''')
    primitive=root/'device/cxi_primitives.cuh'
    replace(primitive,'\nnamespace cxi_gin {','''
#ifndef CXI_BATCH_DELIVERY
#define CXI_BATCH_DELIVERY 0
#endif
namespace cxi_gin {''')
    replace(primitive,'__device__ __forceinline__ bool flush_locked(CxiGpuContext& c,uint32_t* abort=nullptr,uint64_t timeout=default_timeout) {',
            '''__device__ __forceinline__ bool delivery_flush_locked(CxiGpuContext& c,uint32_t* abort,uint64_t timeout);
__device__ __forceinline__ bool flush_locked(CxiGpuContext& c,uint32_t* abort=nullptr,uint64_t timeout=default_timeout) {
#if CXI_BATCH_DELIVERY
  if(!delivery_flush_locked(c,abort,timeout))return false;
#endif''')
    replace(primitive,'__device__ __forceinline__ bool put_locked(CxiGpuContext& c,const CxiWindow* dst,uint64_t dstoff,',
            '''// Closed same-endpoint epoch: payload CT_SEND events plus a DC/CT_ACK
// PUT on the identical destination PID/PTE. Repeat one final payload byte from
// its original registered source, which remains live until this flush completes.
// The caller holds the context lock throughout submission and completion.
__device__ __forceinline__ bool delivery_flush_locked(CxiGpuContext& c,uint32_t* abort,uint64_t timeout) {
  const auto* w=c.pending_dst;
  if(!w)return true;
  int peer=c.pending_peer;
  if(!region(c,w,peer,c.pending_remote_offset,1))return false;
  uint64_t words[8]{};auto* cmd=(c_full_dma_cmd*)words;
  cmd->command.cmd_type=C_CMD_TYPE_DMA;cmd->command.cmd_size=C_CMD_SIZE_64B;cmd->command.opcode=C_CMD_PUT;
  cmd->index_ext=w->peer[peer].index_ext;cmd->lac=c.pending_lac;
  cmd->event_send_disable=1;cmd->event_success_disable=1;cmd->event_ct_ack=1;
  cmd->restricted=1;cmd->flush=1;cmd->ct=c.ct_id;cmd->eq=c.eq_id;
  *(uint32_t*)&cmd->dfa=w->peer[peer].dfa;
  cmd->remote_offset=c.pending_remote_offset;cmd->local_addr=c.pending_local_addr;
  cmd->request_len=1;
  if(!emit(c,words,true,abort,timeout,true))return false;
  c.pending_dst=nullptr;
  return true;
}
__device__ __forceinline__ bool put_locked(CxiGpuContext& c,const CxiWindow* dst,uint64_t dstoff,''')
    replace(primitive,'  if(!region(c,dst,peer,dstoff,bytes) || !region(c,src,0,srcoff,bytes))return false;',
            '''  if(!region(c,dst,peer,dstoff,bytes) || !region(c,src,0,srcoff,bytes))return false;
#if CXI_BATCH_DELIVERY
  // Different registrations have different PIDs. Never use one window's DC
  // marker as evidence for another window or peer. Close the old epoch first.
  if(bytes && c.pending_dst && (c.pending_dst!=dst || c.pending_peer!=unsigned(peer)))
    if(!flush_locked(c,abort))return false;
#endif''')
    old='''    cmd->event_send_disable=1;cmd->event_success_disable=1;cmd->event_ct_ack=1;
    cmd->restricted=1;cmd->flush=1;cmd->ct=c.ct_id;cmd->eq=c.eq_id;
    *(uint32_t*)&cmd->dfa=dst->peer[peer].dfa;'''
    new='''    cmd->event_send_disable=1;cmd->event_success_disable=1;
    cmd->event_ct_ack=CXI_BATCH_DELIVERY?0:1;cmd->event_ct_send=CXI_BATCH_DELIVERY?1:0;
    cmd->restricted=1;cmd->flush=CXI_BATCH_DELIVERY?0:1;cmd->ct=c.ct_id;cmd->eq=c.eq_id;
    *(uint32_t*)&cmd->dfa=dst->peer[peer].dfa;'''
    replace(primitive,old,new)
    replace(primitive,'    if(!emit(c,words,true,abort,default_timeout,aggregate))return false;',
            '''    if(!emit(c,words,true,abort,default_timeout,aggregate))return false;
#if CXI_BATCH_DELIVERY
    c.pending_dst=const_cast<CxiWindow*>(dst);c.pending_peer=unsigned(peer);
    c.pending_lac=src->local_lac;c.pending_local_addr=src->local_iova+srcoff+n-1;
    c.pending_remote_offset=dstoff+n-1;
#endif''')
    plugin=root/'host/gin_plugin.cc'
    replace(plugin,'  if(x->device && getenv("CXI_QUEUE_INVENTORY")) {', '''  if(x->device)for(const auto& c:x->host)
    if(c.pending_dst || c.tx_unpublished) {
      // Pending software publication cannot be recovered by queue teardown.
      // completed is only the last GPU-observed CT value: a final signal may
      // already have completed in hardware without another explicit flush.
      // Preserve the baseline checked-close path for such non-reusable queues.
      fprintf(stderr,"CXI unpublished context pending=%p unpublished=%u posted=%llu completed=%llu\\n",
        (void*)c.pending_dst,c.tx_unpublished,(unsigned long long)c.posted,(unsigned long long)c.completed);
      TD(1);
    }
  if(x->device && getenv("CXI_QUEUE_INVENTORY")) {''')
    host=root/'host/cxi_resources.cc'
    replace(host,'     state->tx_unpublished || state->posted!=state->completed || cxi_channel_error(q))',
            '     state->pending_dst || state->tx_unpublished || state->posted!=state->completed || cxi_channel_error(q))')
    replace(host,'  q->descriptor.signal_window=nullptr;q->descriptor.signal_offset=0;',
            '''  q->descriptor.signal_window=nullptr;q->descriptor.signal_offset=0;
  q->descriptor.pending_local_addr=0;q->descriptor.pending_remote_offset=0;
  q->descriptor.pending_lac=0;q->descriptor.pending_peer=0;''')
