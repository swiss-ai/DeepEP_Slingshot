#pragma once
#include "../gin_device_common.h"
#include "cxi_primitives.cuh"

namespace nccl { namespace gin { namespace cxi {
NCCL_DEVICE_INLINE CxiGpuContext& context(ncclGinCtx ctx) {
  return static_cast<CxiGpuContext*>(ctx.handle)[ctx.contextId];
}
NCCL_DEVICE_INLINE void require(bool ok){if(!ok)asm volatile("trap;");}
NCCL_DEVICE_INLINE bool signal(CxiGpuContext& c,int peer,ncclGinSignalDescriptor s,ncclGinSignalOp_t op,uint64_t arg) {
  if(s.type==NCCL_GIN_SIGNAL_TYPE_NONE)return true;
  if(op!=ncclGinSignalInc && op!=ncclGinSignalAdd)return cxi_gin::fail(c,40,op);
  uint64_t value=op==ncclGinSignalInc?1:arg;
  CxiWindow* w=nullptr;uint64_t offset=0;
  if(s.type==NCCL_GIN_SIGNAL_TYPE_INDEXED) {
    if(s.indexedSignal.signalId>=c.nsignals)return cxi_gin::fail(c,41,s.indexedSignal.signalId,c.nsignals);
    w=c.signal_window;offset=c.signal_offset+8*s.indexedSignal.signalId;
  } else if(s.type==NCCL_GIN_SIGNAL_TYPE_VA) {
    w=static_cast<CxiWindow*>(s.vaSignal.signalWindow);offset=s.vaSignal.signalOffset;
  } else return cxi_gin::fail(c,42,s.type);
  // Conservative initial implementation: weak signals also wait for all prior
  // transfers in this context. This is stronger than their minimum guarantee.
  return cxi_gin::add_locked(c,w,offset,value,peer);
}
struct Request {uint64_t magic;uint64_t context;};
static_assert(sizeof(Request)<=sizeof(ncclGinRequest_t),"CXI request ABI");
constexpr uint64_t request_magic=0x435849464c555348ULL;
}}}

template<> struct ncclGinApi_Put<NCCL_NET_DEVICE_GIN_CXI> {
  template<typename Coop>
  NCCL_DEVICE_INLINE static void call(ncclGinCtx ctx,Coop coop,int peer,bool hasWins,ncclGinWindow_t dst,size_t dstoff,
      ncclGinWindow_t src,size_t srcoff,size_t bytes,ncclGinSignalDescriptor signal,ncclGinSignalOp_t op,uint64_t arg,
      bool hasCounter,ncclGinCounter_t counter,bool,ncclGinDescriptorSmem*,cuda::thread_scope,cuda::thread_scope,uint32_t optFlags) {
    coop.sync();
    if(coop.thread_rank()==0) {
      auto& c=nccl::gin::cxi::context(ctx);nccl::gin::cxi::require(cxi_gin::acquire(c));
      bool ok=!hasWins || cxi_gin::put_locked(c,(CxiWindow*)dst,dstoff,(CxiWindow*)src,srcoff,bytes,peer,nullptr,
          bool(optFlags & ncclGinOptFlagsAggregateRequests));
      if(ok)ok=nccl::gin::cxi::signal(c,peer,signal,op,arg);
      if(ok && hasCounter) {
        if(counter>=c.ncounters)ok=cxi_gin::fail(c,43,counter,c.ncounters);
        else if((ok=cxi_gin::flush_locked(c)))atomicAdd((unsigned long long*)(c.counters+counter),1ULL);
      }
      cxi_gin::release(c);nccl::gin::cxi::require(ok);
    }
    coop.sync();
  }
};
template<> struct ncclGinApi_PutValue<NCCL_NET_DEVICE_GIN_CXI> {
  template<typename Coop,typename T>
  NCCL_DEVICE_INLINE static void call(ncclGinCtx ctx,Coop coop,int peer,ncclGinWindow_t dst,size_t off,T data,
      ncclGinSignalDescriptor signal,ncclGinSignalOp_t op,uint64_t arg,bool,ncclGinDescriptorSmem*,cuda::thread_scope,cuda::thread_scope,uint32_t) {
    static_assert(sizeof(T)<=8,"CXI inline value size");coop.sync();
    if(coop.thread_rank()==0) {
      uint64_t value=0;memcpy(&value,&data,sizeof(data));auto& c=nccl::gin::cxi::context(ctx);
      nccl::gin::cxi::require(cxi_gin::acquire(c));
      bool ok=cxi_gin::value_locked(c,(CxiWindow*)dst,off,value,sizeof(T),peer);
      if(ok)ok=nccl::gin::cxi::signal(c,peer,signal,op,arg);
      cxi_gin::release(c);nccl::gin::cxi::require(ok);
    }
    coop.sync();
  }
};
template<> struct ncclGinApi_Get<NCCL_NET_DEVICE_GIN_CXI> {
  template<typename Coop>
  NCCL_DEVICE_INLINE static void call(ncclGinCtx ctx,Coop,int,ncclGinWindow_t,size_t,ncclGinWindow_t,size_t,size_t,bool,ncclGinDescriptorSmem*,uint32_t) {
    cxi_gin::fail(nccl::gin::cxi::context(ctx),44);asm volatile("trap;"); // Outside the initial DeepEP EP subset.
  }
};
template<> struct ncclGinApi_FlushAsync<NCCL_NET_DEVICE_GIN_CXI> {
  NCCL_DEVICE_INLINE static void call(ncclGinCtx ctx,uint32_t,ncclGinRequest_t* req,bool,ncclGinDescriptorSmem*,uint32_t) {
    auto& c=nccl::gin::cxi::context(ctx);nccl::gin::cxi::require(cxi_gin::flush(c));
    auto* out=reinterpret_cast<nccl::gin::cxi::Request*>(req);out->magic=nccl::gin::cxi::request_magic;out->context=(uint64_t)&c;
  }
};
template<> struct ncclGinApi_Wait<NCCL_NET_DEVICE_GIN_CXI> {
  NCCL_DEVICE_INLINE static ncclResult_t call(ncclGinCtx ctx,ncclGinRequest_t& req,bool,ncclGinDescriptorSmem*,cuda::memory_order,uint32_t*,uint64_t) {
    auto* r=reinterpret_cast<nccl::gin::cxi::Request*>(&req);auto& c=nccl::gin::cxi::context(ctx);
    if(r->magic!=nccl::gin::cxi::request_magic || r->context!=(uint64_t)&c){cxi_gin::fail(c,45);return ncclInvalidUsage;}
    __threadfence_system();return ncclSuccess;
  }
  NCCL_DEVICE_INLINE static void call(ncclGinCtx ctx,ncclGinRequest_t& req,bool desc,ncclGinDescriptorSmem* scratch,cuda::memory_order ord,uint32_t* abort) {
    nccl::gin::cxi::require(call(ctx,req,desc,scratch,ord,abort,0)==ncclSuccess);
  }
};
template<> struct ncclGinApi_Flush<NCCL_NET_DEVICE_GIN_CXI> {
  template<typename Coop>
  NCCL_DEVICE_INLINE static ncclResult_t call(ncclGinCtx ctx,Coop coop,bool,ncclGinDescriptorSmem*,cuda::memory_order,uint32_t* abort,uint64_t timeout) {
    coop.sync();auto& c=nccl::gin::cxi::context(ctx);
    if(coop.thread_rank()==0)cxi_gin::flush(c,abort,timeout?timeout:cxi_gin::default_timeout);
    coop.sync();return cxi_gin::load64(c.diagnostic)?ncclSystemError:ncclSuccess;
  }
  template<typename Coop>
  NCCL_DEVICE_INLINE static void call(ncclGinCtx ctx,Coop coop,bool desc,ncclGinDescriptorSmem* scratch,cuda::memory_order ord,uint32_t* abort) {
    nccl::gin::cxi::require(call(ctx,coop,desc,scratch,ord,abort,cxi_gin::default_timeout)==ncclSuccess);
  }
};
template<> struct ncclGinApi_SupportsStrongSignal<NCCL_NET_DEVICE_GIN_CXI> {
  NCCL_DEVICE_INLINE static bool call(ncclGinCtx){return true;}
};
template<> struct ncclGinApi_FlushesAllPutsOnAnySignal<NCCL_NET_DEVICE_GIN_CXI> {
  NCCL_DEVICE_INLINE static bool call(ncclGinCtx){return false;}
};
template<> struct ncclGinApi_GetSignalPtr<NCCL_NET_DEVICE_GIN_CXI> {
  NCCL_DEVICE_INLINE static ncclGinOffsetPtr call(ncclGinCtx ctx,ncclGinSignal_t id) {
    auto& c=nccl::gin::cxi::context(ctx);nccl::gin::cxi::require(id<c.nsignals);return {c.signals+id,0};
  }
};
template<> struct ncclGinApi_GetCounterPtr<NCCL_NET_DEVICE_GIN_CXI> {
  NCCL_DEVICE_INLINE static ncclGinOffsetPtr call(ncclGinCtx ctx,ncclGinCounter_t id) {
    auto& c=nccl::gin::cxi::context(ctx);nccl::gin::cxi::require(id<c.ncounters);return {c.counters+id,0};
  }
};
template<> struct ncclGinApi_ResetSignal<NCCL_NET_DEVICE_GIN_CXI> {
  NCCL_DEVICE_INLINE static void call(ncclGinCtx ctx,ncclGinSignalDescriptor s) {
    auto& c=nccl::gin::cxi::context(ctx);uint64_t* p=nullptr;
    if(s.type==NCCL_GIN_SIGNAL_TYPE_INDEXED){nccl::gin::cxi::require(s.indexedSignal.signalId<c.nsignals);p=c.signals+s.indexedSignal.signalId;}
    else if(s.type==NCCL_GIN_SIGNAL_TYPE_VA){auto* w=(CxiWindow*)s.vaSignal.signalWindow;nccl::gin::cxi::require(cxi_gin::region(c,w,0,s.vaSignal.signalOffset,8));p=(uint64_t*)(w->local_pointer+s.vaSignal.signalOffset);}
    nccl::gin::cxi::require(p!=nullptr);cxi_gin::store64(p,0);
  }
};
template<> struct ncclGinApi_ResetCounter<NCCL_NET_DEVICE_GIN_CXI> {
  NCCL_DEVICE_INLINE static void call(ncclGinCtx ctx,ncclGinCounter_t id) {
    auto& c=nccl::gin::cxi::context(ctx);nccl::gin::cxi::require(id<c.ncounters);cxi_gin::store64(c.counters+id,0);
  }
};
