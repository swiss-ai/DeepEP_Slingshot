#include <nccl_gin.h>
#include <cuda_runtime_api.h>
#include "cxi_resources.h"
#include "cxi_bootstrap.h"
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <unistd.h>
#include <limits.h>
#include <algorithm>
#include <memory>
#include <mutex>
#include <stdexcept>
#include <string>
#include <vector>

namespace {
struct Init {uint64_t comm;ncclDebugLogger_t logger;};
struct Coll {
  int gpu=0,dev=0,rank=0,peers=0;
  unsigned memories=0,contexts=0;
  CxiResources* resources=nullptr;
  std::unique_ptr<CxiBootstrap> bootstrap;
  std::mutex mutex;
};
struct Memory {Coll* coll=nullptr;CxiMemory* memory=nullptr;CxiWindow* device=nullptr;bool counted=false;};
struct Context {
  Coll* coll=nullptr;std::vector<CxiChannel*> channels;std::vector<CxiGpuContext> host;
  CxiGpuContext* device=nullptr;uint64_t* signals=nullptr;Memory* signal_memory=nullptr;
  ncclNetDeviceHandle_v11_t handle{};bool counted=false;
};
std::mutex diagnostics_mutex;
std::vector<Context*> diagnostics_contexts;
void check(int rc,const char* op){if(rc)throw std::runtime_error(std::string(op)+" rc="+std::to_string(rc));}
#define CK(x) check((x),#x)
// This experimental backend cannot recover an errored CUDA context or a NIC
// resource that refused teardown. Terminate the isolated rank and let the
// launcher's kill-on-bad-exit terminate its peers. Continuing would risk freeing
// buffers still accessible to the NIC. This policy is not transparent recovery.
void teardown_check(int rc,const char* operation) {
  if(rc){fprintf(stderr,"CXI-GIN fatal teardown: %s rc=%d; restart process group\n",operation,rc);fflush(stderr);std::_Exit(86);}
}
#define TD(x) teardown_check((x),#x)
template<class F> ncclResult_t boundary(const char* op,F fn) {
  try{fn();return ncclSuccess;}
  catch(const std::exception& e){fprintf(stderr,"CXI-GIN %s: %s\n",op,e.what());return ncclSystemError;}
  catch(...){fprintf(stderr,"CXI-GIN %s: unknown exception\n",op);return ncclInternalError;}
}
std::vector<std::string> devices_list() {
  std::vector<std::string> out;const char* s=getenv("SLINGSHOT_DEVICES");
  while(s && *s){size_t n=strcspn(s,",");out.emplace_back(s,n);s+=n;if(*s==',')s++;}
  return out;
}
int close_memory(Memory* m) {
  if(!m)return 0;
  TD(cudaDeviceSynchronize());
  if(m->memory)TD(cxi_memory_close(m->memory));
  if(m->device)TD(cudaFree(m->device));
  if(m->counted)m->coll->memories--;
  delete m;return 0;
}
void ensure_resources(Coll* c) {
  if(!c->resources)c->resources=cxi_resources_open(c->gpu,c->dev);
}
void close_idle_resources(Coll* c) {
  // The long-lived NCCL bootstrap need not retain an LNI when no registered
  // memory or device context uses it. This also releases deferred PTE/CT IDs.
  if(c->resources && !c->contexts && !c->memories) {
    cxi_resources_report(c->resources,"idle-lni-close");
    TD(cxi_resources_close(c->resources));c->resources=nullptr;
  }
}
Memory* register_memory(Coll* c,void* p,size_t size,int type,int fd=-1,size_t offset=0) {
  if(type!=NCCL_PTR_CUDA && type!=NCCL_PTR_HOST)throw std::runtime_error("unsupported MR type");
  auto* m=new Memory;m->coll=c;
  try {
    CK(cudaSetDevice(c->gpu));ensure_resources(c);m->memory=cxi_memory_register(c->resources,p,size,type==NCCL_PTR_CUDA,fd,offset);
    struct Exchange {CxiPeerAddress peer;uint64_t bytes;};
    Exchange local{cxi_memory_peer(m->memory),size};std::vector<Exchange> all(c->peers);
    c->bootstrap->allgather(&local,sizeof(local),all.data());
    CxiWindow w{};cxi_memory_local(m->memory,&w);w.peers=c->peers;
    for(int i=0;i<c->peers;i++) {
      if(all[i].bytes!=size)throw std::runtime_error("initial CXI backend requires equal symmetric MR sizes");
      w.peer[i]=all[i].peer;
    }
    CK(cudaMalloc(&m->device,sizeof(w)));CK(cudaMemcpy(m->device,&w,sizeof(w),cudaMemcpyHostToDevice));
    c->memories++;m->counted=true;return m;
  }catch(...){close_memory(m);throw;}
}
int close_context(Context* x) {
  if(!x)return 0;TD(cudaSetDevice(x->coll->gpu));
  if(x->device) {
    TD(cudaDeviceSynchronize());
    TD(cudaMemcpy(x->host.data(),x->device,x->host.size()*sizeof(CxiGpuContext),cudaMemcpyDeviceToHost));
  }
  {
    std::lock_guard<std::mutex> guard(diagnostics_mutex);
    diagnostics_contexts.erase(std::remove(diagnostics_contexts.begin(),diagnostics_contexts.end(),x),diagnostics_contexts.end());
  }
  if(x->device)for(const auto& c:x->host)
    if(c.pending_dst || c.tx_unpublished) {
      // Pending software publication cannot be recovered by queue teardown.
      // completed is only the last GPU-observed CT value: a final signal may
      // already have completed in hardware without another explicit flush.
      // Preserve the baseline checked-close path for such non-reusable queues.
      fprintf(stderr,"CXI unpublished context pending=%p unpublished=%u posted=%llu completed=%llu\n",
        (void*)c.pending_dst,c.tx_unpublished,(unsigned long long)c.posted,(unsigned long long)c.completed);
      TD(1);
    }
  if(x->device && getenv("CXI_QUEUE_INVENTORY")) {
    uint64_t commands=0,doorbells=0,pending=0;
    for(const auto& c:x->host){commands+=c.tx_commands;doorbells+=c.tx_doorbells;pending+=c.tx_unpublished;}
    fprintf(stderr,"CXI_TX_PUBLICATION rank=%d cumulative_commands=%llu cumulative_doorbells=%llu unpublished=%llu\n",
      x->coll->rank,(unsigned long long)commands,(unsigned long long)doorbells,(unsigned long long)pending);
  }
  for(size_t i=0;i<x->channels.size();i++)TD(cxi_channel_recycle(x->channels[i],x->device?&x->host[i]:nullptr));
  if(x->device)TD(cudaFree(x->device));
  TD(close_memory(x->signal_memory));
  if(x->signals)TD(cudaFree(x->signals));
  if(x->counted)x->coll->contexts--;
  cxi_resources_report(x->coll->resources,"context-closed");
  fprintf(stderr,"CXI-GIN destroyContext rank=%d contexts=%zu rc=0\n",x->coll->rank,x->channels.size());
  delete x;return 0;
}
ncclResult_t init(void** ctx,uint64_t comm,ncclDebugLogger_t logger) {
  return boundary("init",[&]{*ctx=new Init{comm,logger};});
}
ncclResult_t devices(int* n){return boundary("devices",[&]{*n=devices_list().size();});}
ncclResult_t gin_properties(ncclGinProperties_v14_t* p){p->supportsStrongSignals=true;p->supportsVASignals=true;return ncclSuccess;}
ncclResult_t properties(int dev,ncclNetProperties_v12_t* p) {
  return boundary("getProperties",[&]{
    static std::mutex lock;static std::vector<std::string> names,paths;
    std::lock_guard<std::mutex> guard(lock);
    if(names.empty()) {
      names=devices_list();paths.resize(names.size());
      for(size_t i=0;i<names.size();i++) {
        char resolved[PATH_MAX];std::string path="/sys/class/cxi/"+names[i]+"/device";
        if(!realpath(path.c_str(),resolved))throw std::runtime_error("CXI PCI sysfs path unavailable");
        paths[i]=resolved;
      }
    }
    if(dev<0 || dev>=(int)names.size())throw std::runtime_error("NIC index");
    memset(p,0,sizeof(*p));p->name=const_cast<char*>(names[dev].c_str());p->pciPath=const_cast<char*>(paths[dev].c_str());
    // PCI path hash is stable within a node; GUID is used for topology grouping.
    uint64_t hash=1469598103934665603ULL;for(char c:paths[dev]){hash^=(unsigned char)c;hash*=1099511628211ULL;}p->guid=hash;
    p->ptrSupport=NCCL_PTR_HOST|NCCL_PTR_CUDA|NCCL_PTR_DMABUF;p->regIsGlobal=0;p->forceFlush=0;
    p->speed=200000;p->port=1;p->latency=1;p->maxComms=64;p->maxRecvs=1;
    p->netDeviceType=NCCL_NET_DEVICE_GIN_CXI;p->netDeviceVersion=CXI_GIN_DEVICE_VERSION;
    p->vProps.ndevs=1;p->vProps.devs[0]=dev;p->maxP2pBytes=NCCL_MAX_NET_SIZE_BYTES;
    p->maxCollBytes=NCCL_MAX_NET_SIZE_BYTES;p->maxMultiRequestSize=1;p->railId=dev;p->planeId=0;
  });
}
ncclResult_t listen(void*,int dev,void* handle,void** out) {
  return boundary("listen",[&]{auto* l=cxi_listen(dev);memset(handle,0,NCCL_GIN_HANDLE_MAXSIZE);memcpy(handle,&l->handle,sizeof(l->handle));*out=l;});
}
ncclResult_t connect(void*,void* handles[],int n,int rank,void* listener,void** out) {
  return boundary("connect",[&]{
    auto c=std::unique_ptr<Coll>(new Coll);auto* l=(CxiListener*)listener;
    c->rank=rank;c->peers=n;c->dev=l->device;CK(cudaGetDevice(&c->gpu));
    c->bootstrap.reset(new CxiBootstrap(handles,n,rank,l));
    c->resources=cxi_resources_open(c->gpu,c->dev);
    fprintf(stderr,"CXI-GIN connect rank=%d/%d GPU=%d NICindex=%d\n",rank,n,c->gpu,c->dev);*out=c.release();
  });
}
ncclResult_t create_context(void* coll,ncclGinConfig_v14_t* cfg,void** out,ncclNetDeviceHandle_v11_t** dev) {
  return boundary("createContext",[&]{
    auto* c=(Coll*)coll;std::lock_guard<std::mutex> guard(c->mutex);CK(cudaSetDevice(c->gpu));
    if(cfg->backendVersion!=CXI_GIN_DEVICE_VERSION || cfg->nContexts<1 || cfg->nContexts>512 ||
       cfg->nSignals<0 || cfg->nCounters<0 || cfg->nSignals>1048576 || cfg->nCounters>1048576 ||
       cfg->rankStride<1 || c->peers%cfg->rankStride)throw std::runtime_error("unsupported context configuration");
    auto* x=new Context;x->coll=c;
    try {
      size_t words=(size_t)cfg->nSignals+cfg->nCounters;
      size_t size=std::max<size_t>(65536,((words*cfg->nContexts*8+65535)/65536)*65536);
      CK(cudaMalloc(&x->signals,size));CK(cudaMemset(x->signals,0,size));CK(cudaDeviceSynchronize());
      x->signal_memory=register_memory(c,x->signals,size,NCCL_PTR_CUDA);
      for(int i=0;i<cfg->nContexts;i++) {
        auto* channel=cxi_channel_open(c->resources,cfg->queueDepth>0?cfg->queueDepth:64);x->channels.push_back(channel);
        auto d=cxi_channel_descriptor(channel);d.signals=x->signals+i*words;d.counters=d.signals+cfg->nSignals;
        d.nsignals=cfg->nSignals;d.ncounters=cfg->nCounters;d.signal_window=x->signal_memory->device;d.signal_offset=i*words*8;
        x->host.push_back(d);
      }
      CK(cudaMalloc(&x->device,x->host.size()*sizeof(CxiGpuContext)));
      CK(cudaMemcpy(x->device,x->host.data(),x->host.size()*sizeof(CxiGpuContext),cudaMemcpyHostToDevice));
      x->handle.netDeviceType=NCCL_NET_DEVICE_GIN_CXI;x->handle.netDeviceVersion=CXI_GIN_DEVICE_VERSION;
      x->handle.handle=x->device;x->handle.size=x->host.size()*sizeof(CxiGpuContext);x->handle.needsProxyProgress=0;
      c->contexts++;x->counted=true;*out=x;*dev=&x->handle;
      cxi_resources_report(c->resources,"context-created");
      {std::lock_guard<std::mutex> guard(diagnostics_mutex);diagnostics_contexts.push_back(x);}
      fprintf(stderr,"CXI-GIN createContext rank=%d contexts=%d signals=%d counters=%d stride=%d needsProxyProgress=0\n",
        c->rank,cfg->nContexts,cfg->nSignals,cfg->nCounters,cfg->rankStride);
    }catch(...){close_context(x);throw;}
  });
}
ncclResult_t reg(void* coll,void* p,size_t n,int type,uint64_t,void** mh,void** gh) {
  return boundary("regMrSym",[&]{auto* c=(Coll*)coll;std::lock_guard<std::mutex> guard(c->mutex);auto* m=register_memory(c,p,n,type);*mh=m;*gh=m->device;});
}
ncclResult_t reg_dmabuf(void* coll,void* p,size_t n,int type,uint64_t offset,int fd,uint64_t,void** mh,void** gh) {
  return boundary("regMrSymDmaBuf",[&]{auto* c=(Coll*)coll;std::lock_guard<std::mutex> guard(c->mutex);auto* m=register_memory(c,p,n,type,fd,offset);*mh=m;*gh=m->device;});
}
ncclResult_t dereg(void* coll,void* mh) {
  return boundary("deregMrSym",[&]{auto* c=(Coll*)coll;std::lock_guard<std::mutex> guard(c->mutex);CK(cudaSetDevice(c->gpu));CK(close_memory((Memory*)mh));close_idle_resources(c);});
}
ncclResult_t destroy(void* ctx) {
  return boundary("destroyContext",[&]{auto* x=(Context*)ctx;auto* c=x->coll;std::lock_guard<std::mutex> guard(c->mutex);CK(close_context(x));close_idle_resources(c);});
}
ncclResult_t close_coll(void* coll) {
  return boundary("closeColl",[&]{auto* c=(Coll*)coll;if(c->contexts || c->memories)throw std::runtime_error("live CXI resources at closeColl");TD(cudaSetDevice(c->gpu));TD(cxi_resources_close(c->resources));delete c;});
}
ncclResult_t close_listen(void* l){cxi_listener_close((CxiListener*)l);return ncclSuccess;}
ncclResult_t query(void* ctx,bool* hasError) {
  return boundary("queryLastError",[&]{auto* x=(Context*)ctx;*hasError=false;
    // Only observes GPU diagnostics; this is not a NIC progress engine.
    for(auto* q:x->channels)if(cxi_channel_error(q))*hasError=true;
  });
}
ncclResult_t finalize(void* ctx){delete (Init*)ctx;return ncclSuccess;}
}
extern "C" {
// Read-only post-failure diagnostic access for the isolated test harness. It
// submits no NIC commands and remains usable after CUDA reports a kernel trap.
__attribute__((visibility("default"))) uint64_t cxiGinLastDiagnostic() {
  std::lock_guard<std::mutex> guard(diagnostics_mutex);
  for(auto* x:diagnostics_contexts)for(auto* q:x->channels){auto code=cxi_channel_error(q);if(code)return code;}
  return 0;
}
__attribute__((visibility("default"))) ncclGin_v14_t ncclGinPlugin_v14 = {
  "CXI-Direct-Experimental",init,devices,gin_properties,properties,listen,connect,create_context,
  reg,reg_dmabuf,dereg,destroy,close_coll,close_listen,nullptr,query,finalize
};
}
