#pragma once
#include <cuda_runtime.h>
#include "cxi_gin_abi.h"
#include "cassini_user_defs.h"
#include "cxi_queue_credit.h"
#include "cxi_fence_command.h"
#ifndef CXI_HW_SIGNAL_FENCE
#define CXI_HW_SIGNAL_FENCE 0
#endif
#ifndef CXI_TX_PENDING_LIMIT
#define CXI_TX_PENDING_LIMIT 0
#endif
#ifndef CXI_CT_THRESHOLD_FLUSH
#define CXI_CT_THRESHOLD_FLUSH 0
#endif

#ifndef CXI_TX_BATCH_LIMIT
#define CXI_TX_BATCH_LIMIT 1
#endif
static_assert(CXI_TX_BATCH_LIMIT >= 1 && CXI_TX_BATCH_LIMIT <= 64, "bounded TX publication");

#ifndef CXI_BATCH_DELIVERY
#define CXI_BATCH_DELIVERY 0
#endif
#ifndef CXI_ZERO_DELIVERY_MARKER
#define CXI_ZERO_DELIVERY_MARKER 0
#endif
#ifndef CXI_LEAN_FENCE
#define CXI_LEAN_FENCE 0
#endif
#ifndef CXI_LEAN_CSTATE
#define CXI_LEAN_CSTATE 0
#endif
#ifndef CXI_LEAN_FOLD_MARKER
#define CXI_LEAN_FOLD_MARKER 0
#endif
static_assert(!CXI_LEAN_FOLD_MARKER || CXI_BATCH_DELIVERY, "the marker fold replaces the batched-delivery marker");
namespace cxi_gin {
constexpr uint64_t default_timeout=10000000000ULL;
// CxiGpuContext::lean_state bits (host initialises the field to lean_fence_due).
constexpr uint32_t lean_fence_due=1u;         // a fenced-before-signal transfer was posted since the last CQ fence
constexpr uint32_t lean_last_is_put=2u;       // newest ring entry is the pending payload PUT and is unpublished
constexpr uint32_t lean_cstate_mask=0x1FF00u; // bits 8..12 index_ext, 13..15 write_lac, 16 valid
__device__ __forceinline__ uint32_t lean_cstate_key(unsigned index_ext,unsigned write_lac) {
  return (1u<<16)|((index_ext&31u)<<8)|((write_lac&7u)<<13);
}
__device__ __forceinline__ uint64_t load64(const uint64_t* p) {
  uint64_t v;asm volatile("ld.acquire.sys.global.u64 %0, [%1];":"=l"(v):"l"(p):"memory");return v;
}
__device__ __forceinline__ uint32_t load32(const uint32_t* p) {
  uint32_t v;asm volatile("ld.acquire.sys.global.u32 %0, [%1];":"=r"(v):"l"(p):"memory");return v;
}
__device__ __forceinline__ void store64(uint64_t* p,uint64_t v) {
  asm volatile("st.release.sys.global.u64 [%0], %1;"::"l"(p),"l"(v):"memory");
}
__device__ __forceinline__ bool fail(CxiGpuContext& c,unsigned code,uint64_t a=0,uint64_t b=0) {
  if(c.diagnostic){store64(c.diagnostic+1,a);store64(c.diagnostic+2,b);store64(c.diagnostic,code);}return false;
}
__device__ __forceinline__ bool expired(uint64_t start,uint64_t timeout,uint32_t* abort) {
  return (abort && load32(abort)) || clock64()-start>timeout;
}
__device__ __forceinline__ bool acquire(CxiGpuContext& c,uint32_t* abort=nullptr,uint64_t timeout=default_timeout) {
  if(c.abi_version!=CXI_GIN_ABI_VERSION)return fail(c,1,c.abi_version);
  uint64_t start=clock64();
  while(atomicCAS(&c.lock,0u,1u)!=0){if(expired(start,timeout,abort))return fail(c,2);__nanosleep(64);}
  __threadfence();return true;
}
__device__ __forceinline__ void release(CxiGpuContext& c){__threadfence();atomicExch(&c.lock,0u);}

// Caller owns the context lock. Each producer has already system-fenced its
// descriptor writes before releasing the lock. Preserve that guarantee even when
// another producer becomes the publisher; this variant only amortizes doorbells.
__device__ __forceinline__ void publish_locked(CxiGpuContext& c) {
  c.lean_state&=~lean_last_is_put; // a doorbelled entry can no longer be rewritten
  if(!c.tx_unpublished)return;
  __threadfence_system();
  store64(c.tx_doorbell,c.tx_wp32/2);
  c.tx_doorbells++;
  c.tx_unpublished=0;
}

// Caller owns the context lock. Wait for capacity, not for every command to be
// consumed. Completion tracking and flush-before-signal ordering are unchanged.
// AggregateRequests may defer a bounded number of doorbells. Flush/signals force publication.
__device__ __forceinline__ bool emit(CxiGpuContext& c,const uint64_t* command,bool transfer,
                                   uint32_t* abort=nullptr,uint64_t timeout=default_timeout,bool aggregate=false) {
  uint64_t start=clock64();
  c.lean_state&=~lean_last_is_put; // any new command supersedes the pending PUT as newest entry
  while(true) {
    uint32_t status=load32((uint32_t*)c.tx_queue);
    if(status>>16)return fail(c,3,status);
    uint32_t rp32=(status&65535)*2;
    if(!cq_positions_valid(c.tx_size32,c.tx_wp32,rp32))return fail(c,46,status,c.tx_wp32);
    if(cq_free_slots32(c.tx_size32,c.tx_wp32,rp32)>=2 &&
       (!CXI_TX_PENDING_LIMIT || cq_pending_commands(c.tx_size32,c.tx_wp32,rp32)<CXI_TX_PENDING_LIMIT))break;
    // Never wait for NIC credits while unsubmitted descriptors occupy the ring.
    publish_locked(c);
    if(expired(start,timeout,abort))return fail(c,4,status,c.tx_wp32);
    __nanosleep(64);
  }
  for(unsigned i=0;i<8;i++)c.tx_queue[c.tx_wp32*4+i]=command[i];
  __threadfence_system();unsigned next=c.tx_wp32+2;if(next>=c.tx_size32)next=8;
  c.tx_wp32=next;c.tx_unpublished++;c.tx_commands++;
  if(transfer)c.posted++;
  if(!aggregate || c.tx_unpublished>=CXI_TX_BATCH_LIMIT)publish_locked(c);
  return true;
}
__device__ __forceinline__ bool delivery_flush_locked(CxiGpuContext& c,uint32_t* abort,uint64_t timeout);
__device__ __forceinline__ bool flush_locked(CxiGpuContext& c,uint32_t* abort=nullptr,uint64_t timeout=default_timeout) {
#if CXI_BATCH_DELIVERY
  if(!delivery_flush_locked(c,abort,timeout))return false;
#endif
  publish_locked(c);
  if(c.completed==c.posted){c.lean_state&=~lean_fence_due;return true;}
  uint64_t start=clock64();
  do {
    uint64_t command[8]{};auto* get=(c_ct_cmd*)command;
    get->command.cmd_type=C_CMD_TYPE_CT;get->command.cmd_size=C_CMD_SIZE_64B;get->command.opcode=C_CMD_CT_GET;get->ct=c.ct_id;
#if CXI_CT_THRESHOLD_FLUSH
    // HPE libcxi hip_cntr_test.cpp cntr_trigger(): request CT writeback once
    // all currently posted transfers have acknowledged. Keep the context lock
    // until that observation: no later transfer can satisfy this threshold.
    // Only one trigger/writeback is outstanding on this context's CT queue.
    if(c.posted >= (1ULL<<48))return fail(c,47,c.posted);
    get->command.opcode=C_CMD_CT_TRIG_EVENT;get->trig_ct=c.ct_id;
    get->ct_success=1;get->set_ct_success=1;get->threshold=c.posted;
#endif
    store64(c.ct_writeback,0);
    for(unsigned j=0;j<8;j++)c.ct_queue[c.ct_wp32*4+j]=command[j];
    __threadfence_system();unsigned next=c.ct_wp32+2;if(next>=c.ct_size32)next=8;
    store64(c.ct_doorbell,next/2);c.ct_wp32=next;
    uint64_t value;
    do {value=load64(c.ct_writeback);if(expired(start,timeout,abort))return fail(c,5,c.posted,value);}while(!(value&(1ULL<<63)));
    if((value>>48)&127)return fail(c,6,value,c.posted);
    c.completed=value&((1ULL<<48)-1);
    uint32_t status;
    do {status=load32((uint32_t*)c.ct_queue);
      if(status>>16)return fail(c,7,status);
      if(expired(start,timeout,abort))return fail(c,8,status,next/2);
    }while((status&65535)!=next/2);
    if(c.completed>c.posted)return fail(c,9,c.completed,c.posted);
  }while(c.completed<c.posted);
  c.lean_state&=~lean_fence_due; // everything posted is delivered; no fence needed before the next signal
  __threadfence_system();return true;
}
__device__ __forceinline__ bool region(CxiGpuContext& c,const CxiWindow* w,int peer,uint64_t off,uint64_t size) {
  if(!w || w->abi_version!=CXI_GIN_ABI_VERSION || peer<0 || unsigned(peer)>=w->peers)return fail(c,10,peer);
  if(off>w->bytes || size>w->bytes-off || off>=(1ULL<<56))return fail(c,11,off,size);
  return true;
}
// Closed same-endpoint epoch: payload CT_SEND events plus a DC/CT_ACK
// PUT on the identical destination PID/PTE. Repeat one final payload byte from
// its original registered source, which remains live until this flush completes.
// The caller holds the context lock throughout submission and completion.
__device__ __forceinline__ bool delivery_flush_locked(CxiGpuContext& c,uint32_t* abort,uint64_t timeout) {
  const auto* w=c.pending_dst;
  if(!w)return true;
#if CXI_LEAN_FOLD_MARKER
  if(c.lean_state&lean_last_is_put) {
    // Close the epoch on the pending PUT itself: it is the newest ring entry and not yet
    // doorbelled, so its descriptor can still be rewritten. Delivery semantics equal the
    // zero-byte marker (flush bit, CT_ACK); the CT still counts one event for this command and
    // c.posted is unchanged, so flush accounting is identical.
    unsigned slot=c.tx_wp32==8?c.tx_size32-2:c.tx_wp32-2;
    auto* cmd=(c_full_dma_cmd*)(c.tx_queue+slot*4);
    cmd->event_ct_send=0;cmd->event_ct_ack=1;cmd->flush=1;
    __threadfence_system();
    c.lean_state&=~lean_last_is_put;c.pending_dst=nullptr;
    return true;
  }
#endif
  int peer=c.pending_peer;
  if(!region(c,w,peer,c.pending_remote_offset,1))return false;
  uint64_t words[8]{};auto* cmd=(c_full_dma_cmd*)words;
  cmd->command.cmd_type=C_CMD_TYPE_DMA;cmd->command.cmd_size=C_CMD_SIZE_64B;cmd->command.opcode=C_CMD_PUT;
  cmd->index_ext=w->peer[peer].index_ext;cmd->lac=c.pending_lac;
  cmd->event_send_disable=1;cmd->event_success_disable=1;cmd->event_ct_ack=1;
  cmd->restricted=1;cmd->flush=1;cmd->ct=c.ct_id;cmd->eq=c.eq_id;
  *(uint32_t*)&cmd->dfa=w->peer[peer].dfa;
  cmd->remote_offset=c.pending_remote_offset;cmd->local_addr=c.pending_local_addr;
  cmd->request_len=CXI_ZERO_DELIVERY_MARKER?0:1;
  if(!emit(c,words,true,abort,timeout,true))return false;
  c.pending_dst=nullptr;c.lean_state|=lean_fence_due;
  return true;
}
__device__ __forceinline__ bool put_locked(CxiGpuContext& c,const CxiWindow* dst,uint64_t dstoff,
    const CxiWindow* src,uint64_t srcoff,uint64_t bytes,int peer,uint32_t* abort=nullptr,bool aggregate=false) {
  if(!region(c,dst,peer,dstoff,bytes) || !region(c,src,0,srcoff,bytes))return false;
#if CXI_BATCH_DELIVERY
  // Different registrations have different PIDs. Never use one window's DC
  // marker as evidence for another window or peer. Close the old epoch first.
  if(bytes && c.pending_dst && (c.pending_dst!=dst || c.pending_peer!=unsigned(peer)))
    if(!flush_locked(c,abort))return false;
#endif
  __threadfence_system();
  while(bytes) {
    uint64_t words[8]{};auto* cmd=(c_full_dma_cmd*)words;
    cmd->command.cmd_type=C_CMD_TYPE_DMA;cmd->command.cmd_size=C_CMD_SIZE_64B;cmd->command.opcode=C_CMD_PUT;
    cmd->index_ext=dst->peer[peer].index_ext;cmd->lac=src->local_lac;
    cmd->event_send_disable=1;cmd->event_success_disable=1;
    cmd->event_ct_ack=CXI_BATCH_DELIVERY?0:1;cmd->event_ct_send=CXI_BATCH_DELIVERY?1:0;
    cmd->restricted=1;cmd->flush=CXI_BATCH_DELIVERY?0:1;cmd->ct=c.ct_id;cmd->eq=c.eq_id;
    *(uint32_t*)&cmd->dfa=dst->peer[peer].dfa;
    cmd->remote_offset=dstoff;cmd->local_addr=src->local_iova+srcoff;
    unsigned n=bytes>CXI_GIN_MAX_CHUNK?CXI_GIN_MAX_CHUNK:unsigned(bytes);cmd->request_len=n;
    if(!emit(c,words,true,abort,default_timeout,aggregate))return false;
#if CXI_BATCH_DELIVERY
    c.pending_dst=const_cast<CxiWindow*>(dst);c.pending_peer=unsigned(peer);
    c.pending_lac=src->local_lac;c.pending_local_addr=src->local_iova+srcoff+n-1;
    c.pending_remote_offset=dstoff+n-1;
#if CXI_LEAN_FOLD_MARKER
    // The PUT just written is the newest ring entry; it stays rewritable until published.
    if(c.tx_unpublished)c.lean_state|=lean_last_is_put;
#endif
#endif
    c.lean_state|=lean_fence_due;
    dstoff+=n;srcoff+=n;bytes-=n;
  }
  if(!aggregate)publish_locked(c); // includes zero-byte nonaggregated operations
  return true;
}
__device__ __forceinline__ bool state_locked(CxiGpuContext& c,const CxiWindow* dst,int peer,uint32_t* abort=nullptr) {
#if CXI_LEAN_CSTATE
  // CSTATE is command-queue state consumed by later IDC commands; DMA commands carry their own
  // fields and leave it alone. Re-emit only when the (index_ext, write_lac) pair changes.
  const uint32_t key=lean_cstate_key(dst->peer[peer].index_ext,dst->local_lac);
  if((c.lean_state&lean_cstate_mask)==key)return true;
#endif
  uint64_t words[8]{};auto* st=(c_cstate_cmd*)words;
  st->command.cmd_type=C_CMD_TYPE_IDC;st->command.cmd_size=C_CMD_SIZE_32B;st->command.opcode=C_CMD_CSTATE;
  st->length=sizeof(c_cstate_cmd);st->restricted=1;st->flush=1;
  st->event_send_disable=1;st->event_success_disable=1;st->event_ct_ack=1;
  st->index_ext=dst->peer[peer].index_ext;st->ct=c.ct_id;st->eq=c.eq_id;
  st->write_lac=dst->local_lac;
  if(!emit(c,words,false,abort))return false;
#if CXI_LEAN_CSTATE
  c.lean_state=(c.lean_state&~lean_cstate_mask)|key;
#endif
  return true;
}
// Keep payload visibility before notification, but let the NIC enforce the
// dependency. No GPU CT writeback wait here; explicit flush/counters still wait.
// CQ_FENCE is not a transfer and does not increment the completion target.
__device__ __forceinline__ bool signal_fence_locked(CxiGpuContext& c,uint32_t* abort=nullptr) {
#if CXI_BATCH_DELIVERY
  if(!delivery_flush_locked(c,abort,default_timeout))return false;
#endif
#if CXI_LEAN_FENCE
  // Nothing fence-worthy since the last fence or completed flush: that earlier fence already
  // orders this signal after every prior transfer on the context.
  if(!(c.lean_state&lean_fence_due))return true;
#endif
  uint64_t words[8];cxi_build_fence_command(words);
  if(!emit(c,words,false,abort,default_timeout,true))return false;
  c.lean_state&=~lean_fence_due;
  return true;
}
__device__ __forceinline__ bool add_locked(CxiGpuContext& c,const CxiWindow* dst,uint64_t off,uint64_t amount,int peer,uint32_t* abort=nullptr) {
  if(!region(c,dst,peer,off,8) || (off&7))return fail(c,12,off);
#if CXI_HW_SIGNAL_FENCE
  if(!signal_fence_locked(c,abort) || !state_locked(c,dst,peer,abort))return false;
#else
  if(!flush_locked(c,abort) || !state_locked(c,dst,peer,abort))return false;
#endif
  uint64_t words[8]{};auto* hdr=(c_idc_hdr*)words;auto* amo=(c_small_amo_payload*)(words+2);
  hdr->command.cmd_type=C_CMD_TYPE_IDC;hdr->command.cmd_size=C_CMD_SIZE_32B;hdr->command.opcode=C_CMD_ATOMIC;
  hdr->length=32;*(uint32_t*)&hdr->dfa=dst->peer[peer].dfa;hdr->remote_offset=off;
  amo->amo_op=C_AMO_OP_SUM;amo->amo_type=C_AMO_TYPE_UINT64_T;amo->op1_word1=amount;
  return emit(c,words,true,abort);
}
__device__ __forceinline__ bool value_locked(CxiGpuContext& c,const CxiWindow* dst,uint64_t off,uint64_t value,unsigned bytes,int peer,uint32_t* abort=nullptr) {
  if(!bytes || bytes>8 || !region(c,dst,peer,off,bytes))return fail(c,13,bytes);
  if(!state_locked(c,dst,peer,abort))return false;
  uint64_t words[8]{};auto* hdr=(c_idc_hdr*)words;
  hdr->command.cmd_type=C_CMD_TYPE_IDC;hdr->command.cmd_size=C_CMD_SIZE_32B;hdr->command.opcode=C_CMD_PUT;
  hdr->length=16+bytes;*(uint32_t*)&hdr->dfa=dst->peer[peer].dfa;hdr->remote_offset=off;words[2]=value;
  __threadfence_system();if(!emit(c,words,true,abort))return false;
  c.lean_state|=lean_fence_due;return true;
}
__device__ __forceinline__ bool flush(CxiGpuContext& c,uint32_t* abort=nullptr,uint64_t timeout=default_timeout) {
  if(!acquire(c,abort,timeout))return false;bool ok=flush_locked(c,abort,timeout);release(c);return ok;
}
} // namespace cxi_gin
