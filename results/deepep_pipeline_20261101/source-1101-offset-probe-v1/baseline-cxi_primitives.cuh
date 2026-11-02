#pragma once
#include <cuda_runtime.h>
#include "cxi_gin_abi.h"
#include "cassini_user_defs.h"

namespace cxi_gin {
constexpr uint64_t default_timeout=10000000000ULL;
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

// Caller owns the context lock. Serial command-consumption checks deliberately
// trade throughput for simple, bounded queue reuse during initial bring-up.
__device__ __forceinline__ bool emit(CxiGpuContext& c,const uint64_t* command,bool transfer,
                                   uint32_t* abort=nullptr,uint64_t timeout=default_timeout) {
  for(unsigned i=0;i<8;i++)c.tx_queue[c.tx_wp32*4+i]=command[i];
  __threadfence_system();unsigned next=c.tx_wp32+2;if(next>=c.tx_size32)next=8;
  store64(c.tx_doorbell,next/2);c.tx_wp32=next;
  uint64_t start=clock64();uint32_t status;
  do {status=load32((uint32_t*)c.tx_queue);
    if(status>>16)return fail(c,3,status);
    if(expired(start,timeout,abort))return fail(c,4,status,next/2);
  }while((status&65535)!=next/2);
  if(transfer)c.posted++;return true;
}
__device__ __forceinline__ bool flush_locked(CxiGpuContext& c,uint32_t* abort=nullptr,uint64_t timeout=default_timeout) {
  if(c.completed==c.posted)return true;
  uint64_t start=clock64();
  do {
    uint64_t command[8]{};auto* get=(c_ct_cmd*)command;
    get->command.cmd_type=C_CMD_TYPE_CT;get->command.cmd_size=C_CMD_SIZE_64B;get->command.opcode=C_CMD_CT_GET;get->ct=c.ct_id;
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
  __threadfence_system();return true;
}
__device__ __forceinline__ bool region(CxiGpuContext& c,const CxiWindow* w,int peer,uint64_t off,uint64_t size) {
  if(!w || w->abi_version!=CXI_GIN_ABI_VERSION || peer<0 || unsigned(peer)>=w->peers)return fail(c,10,peer);
  if(off>w->bytes || size>w->bytes-off || off>=(1ULL<<56))return fail(c,11,off,size);
  return true;
}
__device__ __forceinline__ bool put_locked(CxiGpuContext& c,const CxiWindow* dst,uint64_t dstoff,
    const CxiWindow* src,uint64_t srcoff,uint64_t bytes,int peer,uint32_t* abort=nullptr) {
  if(!region(c,dst,peer,dstoff,bytes) || !region(c,src,0,srcoff,bytes))return false;
  __threadfence_system();
  while(bytes) {
    uint64_t words[8]{};auto* cmd=(c_full_dma_cmd*)words;
    cmd->command.cmd_type=C_CMD_TYPE_DMA;cmd->command.cmd_size=C_CMD_SIZE_64B;cmd->command.opcode=C_CMD_PUT;
    cmd->index_ext=dst->peer[peer].index_ext;cmd->lac=src->local_lac;
    cmd->event_send_disable=1;cmd->event_success_disable=1;cmd->event_ct_ack=1;
    cmd->restricted=1;cmd->flush=1;cmd->ct=c.ct_id;cmd->eq=c.eq_id;
    *(uint32_t*)&cmd->dfa=dst->peer[peer].dfa;
    cmd->remote_offset=dstoff;cmd->local_addr=src->local_iova+srcoff;
    unsigned n=bytes>CXI_GIN_MAX_CHUNK?CXI_GIN_MAX_CHUNK:unsigned(bytes);cmd->request_len=n;
    if(!emit(c,words,true,abort))return false;
    dstoff+=n;srcoff+=n;bytes-=n;
  }
  return true;
}
__device__ __forceinline__ bool state_locked(CxiGpuContext& c,const CxiWindow* dst,int peer,uint32_t* abort=nullptr) {
  uint64_t words[8]{};auto* st=(c_cstate_cmd*)words;
  st->command.cmd_type=C_CMD_TYPE_IDC;st->command.cmd_size=C_CMD_SIZE_32B;st->command.opcode=C_CMD_CSTATE;
  st->length=sizeof(c_cstate_cmd);st->restricted=1;st->flush=1;
  st->event_send_disable=1;st->event_success_disable=1;st->event_ct_ack=1;
  st->index_ext=dst->peer[peer].index_ext;st->ct=c.ct_id;st->eq=c.eq_id;
  st->write_lac=dst->local_lac;return emit(c,words,false,abort);
}
__device__ __forceinline__ bool add_locked(CxiGpuContext& c,const CxiWindow* dst,uint64_t off,uint64_t amount,int peer,uint32_t* abort=nullptr) {
  if(!region(c,dst,peer,off,8) || (off&7))return fail(c,12,off);
  if(!flush_locked(c,abort) || !state_locked(c,dst,peer,abort))return false;
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
  __threadfence_system();return emit(c,words,true,abort);
}
__device__ __forceinline__ bool flush(CxiGpuContext& c,uint32_t* abort=nullptr,uint64_t timeout=default_timeout) {
  if(!acquire(c,abort,timeout))return false;bool ok=flush_locked(c,abort,timeout);release(c);return ok;
}
} // namespace cxi_gin
