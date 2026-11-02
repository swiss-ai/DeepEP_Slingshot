#include "cxi_resources.h"
#include <cstring>
#include <libcxi/libcxi.h>
#include <cuda_runtime_api.h>
#include <cuda.h>
#include <dlfcn.h>
#include <unistd.h>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <ctime>
#include <map>
#include <stdexcept>
#include <string>
#include <vector>
#include <algorithm>

namespace {
void check(int rc, const char* op) {
  if (rc) throw std::runtime_error(std::string(op)+" rc="+std::to_string(rc));
}
#define CK(x) check((x), #x)
double now() {timespec t;clock_gettime(CLOCK_MONOTONIC,&t);return t.tv_sec+t.tv_nsec*1e-9;}
std::string token(const char* name, int index) {
  const char* s=getenv(name);if(!s)throw std::runtime_error(std::string("missing ")+name);
  for(int i=0;i<index;i++){s=strchr(s,',');if(!s)throw std::runtime_error("short Slurm NIC metadata");s++;}
  return std::string(s,strcspn(s,","));
}
void expect(cxi_eq* eq, unsigned kind) {
  const union c_event* e;double deadline=now()+5;
  while(!(e=cxi_eq_get_event(eq))) {if(now()>deadline)throw std::runtime_error("CXI event timeout");usleep(10);}
  unsigned code=cxi_event_rc(e),type=e->hdr.event_type;
  cxi_eq_ack_events(eq);
  if(code!=C_RC_OK || type!=kind)throw std::runtime_error("CXI event type="+std::to_string(type)+" code="+std::to_string(code));
}
void* page_alloc(size_t bytes) {void* p=nullptr;CK(posix_memalign(&p,65536,bytes));memset(p,0,bytes);return p;}
void sync_memops(void* pointer) {
  void* lib=dlopen("libcuda.so.1",RTLD_NOW);if(!lib)throw std::runtime_error("libcuda missing");
  auto fn=reinterpret_cast<CUresult(*)(const void*,CUpointer_attribute,CUdeviceptr)>(dlsym(lib,"cuPointerSetAttribute"));
  unsigned one=1;int rc=fn?fn(&one,CU_POINTER_ATTRIBUTE_SYNC_MEMOPS,(CUdeviceptr)pointer):-1;
  // NCCL's VMM allocations reject the legacy per-pointer SYNC_MEMOPS setter.
  // Preserve its synchronous-copy contract at context scope instead of simply
  // ignoring CUDA_ERROR_NOT_SUPPORTED. This is setup only, not NIC progress.
  if(rc==CUDA_ERROR_NOT_SUPPORTED) {
    auto get=reinterpret_cast<CUresult(*)(void*,CUpointer_attribute,CUdeviceptr)>(dlsym(lib,"cuPointerGetAttribute"));
    auto flags_get=reinterpret_cast<CUresult(*)(unsigned*)>(dlsym(lib,"cuCtxGetFlags"));
    auto flags_set=reinterpret_cast<CUresult(*)(unsigned)>(dlsym(lib,"cuCtxSetFlags"));
    unsigned capable=0,flags=0,verified=0;
    if(get && flags_get && flags_set &&
       get(&capable,CU_POINTER_ATTRIBUTE_IS_GPU_DIRECT_RDMA_CAPABLE,(CUdeviceptr)pointer)==CUDA_SUCCESS && capable &&
       flags_get(&flags)==CUDA_SUCCESS && flags_set(flags|CU_CTX_SYNC_MEMOPS)==CUDA_SUCCESS &&
       flags_get(&verified)==CUDA_SUCCESS && (verified&CU_CTX_SYNC_MEMOPS)) {
      rc=cudaDeviceSynchronize();
      fprintf(stderr,"CXI VMM SYNC_MEMOPS fallback: RDMA-capable=%u context_flags=0x%x sync_rc=%d\n",capable,verified,rc);
    }
  }
  dlclose(lib);CK(rc);
}
struct Map {void* gpu=nullptr;size_t bytes=0;unsigned refs=0;};
}

struct CxiResources {
  int gpu=0;unsigned vni=0,svc=0;
  cxil_dev* dev=nullptr;cxil_lni* lni=nullptr;cxi_cp* cp=nullptr; cxi_cp* trig_cp=nullptr;
  cxi_cq* target=nullptr;cxi_eq* eq=nullptr;cxi_md* eqmd=nullptr;void* eqbuf=nullptr;
  std::map<void*,Map> mappings;
  unsigned memories=0,channels=0;
  std::vector<CxiChannel*> idle_channels;
  uint64_t created_channels=0,reused_channels=0;
  int errors=0;
  void* map(void* p,size_t bytes,bool io) {
    auto it=mappings.find(p);
    if(it!=mappings.end()){if(bytes>it->second.bytes)throw std::runtime_error("overlapping CUDA map");it->second.refs++;return it->second.gpu;}
    unsigned flags=cudaHostRegisterMapped|(io?cudaHostRegisterIoMemory:0);
    auto rc=cudaHostRegister(p,bytes,flags);
    if(rc){cudaGetLastError();rc=cudaHostRegister(p,bytes,cudaHostRegisterMapped|(io?0:cudaHostRegisterIoMemory));}
    CK(rc);void* gp=nullptr;
    rc=cudaHostGetDevicePointer(&gp,p,0);
    if(rc){cudaHostUnregister(p);CK(rc);}
    mappings.emplace(p,Map{gp,bytes,1});return gp;
  }
  int unmap(void* p) {
    if(!p)return 0;auto it=mappings.find(p);if(it==mappings.end())return 0;
    if(it->second.refs>1){it->second.refs--;return 0;}
    int rc=cudaHostUnregister(p);
    if(rc){errors++;fprintf(stderr,"CXI CUDA unregister rc=%d; mapping retained\n",rc);return 1;}
    mappings.erase(it);return 0;
  }
};

struct CxiMemory {
  CxiResources* r=nullptr;cxil_domain* domain=nullptr;cxil_pte* pte=nullptr;cxil_pte_map* pmap=nullptr;
  cxi_md* md=nullptr;void* pointer=nullptr;size_t bytes=0;int fd=-1;bool counted=false;
};

struct CxiChannel {
  CxiResources* r=nullptr;cxi_cq *tx=nullptr,*trig=nullptr;cxi_ct* ct=nullptr;
  void *wb=nullptr,*diag=nullptr,*dbpage=nullptr,*ctdbpage=nullptr;
  bool txmap=false,ctmap=false,dbmap=false,ctdbmap=false,wbmap=false,diagmap=false,counted=false;
  CxiGpuContext descriptor{};
  unsigned depth=0;bool pooled=false;
};

CxiResources* cxi_resources_open(int gpu,int nic_index) {
  auto* r=new CxiResources;r->gpu=gpu;
  try {
    CK(cudaSetDevice(gpu));auto dev=token("SLINGSHOT_DEVICES",nic_index);
    unsigned svc=std::stoul(token("SLINGSHOT_SVC_IDS",nic_index));r->svc=svc;r->vni=std::stoul(token("SLINGSHOT_VNIS",0));
    if(dev.rfind("cxi",0)!=0 || !svc)throw std::runtime_error("invalid allocated CXI service");
    CK(cxil_open_device(std::stoul(dev.substr(3)),&r->dev));
    cxi_svc_desc limits{};cxi_rsrc_use use{};
    int limit_rc=cxil_get_svc(r->dev,svc,&limits),use_rc=cxil_get_svc_rsrc_use(r->dev,svc,&use);
    fprintf(stderr,"CXI service inventory svc=%u limits_rc=%d usage_rc=%d limited=%u\n",svc,limit_rc,use_rc,limits.resource_limits);
    if(!limit_rc)for(int kind=0;kind<CXI_RSRC_TYPE_MAX;kind++)
      fprintf(stderr,"CXI service resource=%d max=%u reserved=%u in_use=%d\n",kind,limits.limits.type[kind].max,
        limits.limits.type[kind].res,use_rc?-1:(int)use.in_use[kind]);
    CK(cxil_alloc_lni(r->dev,&r->lni,svc));
    CK(cxil_alloc_cp(r->lni,r->vni,CXI_TC_BEST_EFFORT,CXI_TC_TYPE_DEFAULT,&r->cp));
    CK(cxil_alloc_trig_cp(r->lni,r->vni,CXI_TC_BEST_EFFORT,CXI_TC_TYPE_DEFAULT,TRIG_LCID,&r->trig_cp));
    r->eqbuf=page_alloc(65536);
    CK(cxil_map(r->lni,r->eqbuf,65536,CXI_MAP_PIN|CXI_MAP_READ|CXI_MAP_WRITE,nullptr,&r->eqmd));
    cxi_eq_attr ea{};ea.queue=r->eqbuf;ea.queue_len=65536;CK(cxil_alloc_evtq(r->lni,r->eqmd,&ea,nullptr,nullptr,&r->eq));
    cxi_cq_alloc_opts qo{};qo.count=64;qo.lcid=r->cp->lcid;qo.policy=CXI_CQ_UPDATE_ALWAYS;
    CK(cxil_alloc_cmdq(r->lni,r->eq,&qo,&r->target));
    fprintf(stderr,"CXI resources GPU=%d NIC=%s service=%u VNI=%u\n",gpu,dev.c_str(),svc,r->vni);
    return r;
  } catch(...) {cxi_resources_close(r);throw;}
}

CxiMemory* cxi_memory_register(CxiResources* r,void* p,size_t bytes,bool device,int supplied_fd,size_t fd_offset) {
  if(!r || !p || !bytes)throw std::runtime_error("invalid memory region");
  auto* m=new CxiMemory;m->r=r;m->pointer=p;m->bytes=bytes;
  try {
    CK(cudaSetDevice(r->gpu));if(device)sync_memops(p);
    cxi_md_hints hints{};int export_rc=-1;
    if(supplied_fd>=0){m->fd=dup(supplied_fd);if(m->fd<0)throw std::runtime_error("dup dmabuf");hints.dmabuf_offset=fd_offset;export_rc=0;}
    else if(device) {
      void* lib=dlopen("libcuda.so.1",RTLD_NOW);
      auto fn=reinterpret_cast<CUresult(*)(void*,CUdeviceptr,size_t,CUmemRangeHandleType,unsigned long long)>(lib?dlsym(lib,"cuMemGetHandleForAddressRange"):nullptr);
      size_t page=sysconf(_SC_PAGESIZE);uintptr_t base=(uintptr_t)p&~(uintptr_t)(page-1);
      size_t aligned=(((uintptr_t)p+bytes+page-1)&~(uintptr_t)(page-1))-base;
      export_rc=fn?fn(&m->fd,base,aligned,CU_MEM_RANGE_HANDLE_TYPE_DMA_BUF_FD,0):-1;
      hints.dmabuf_offset=(uintptr_t)p-base;if(lib)dlclose(lib);
    }
    unsigned flags=CXI_MAP_PIN|CXI_MAP_READ|CXI_MAP_WRITE|(device?CXI_MAP_DEVICE:0);
    int rc=-1;
    if(!export_rc){hints.dmabuf_fd=m->fd;hints.dmabuf_valid=true;rc=cxil_map(r->lni,p,bytes,flags,&hints,&m->md);}
    if(rc && supplied_fd<0){if(m->fd>=0){close(m->fd);m->fd=-1;}rc=cxil_map(r->lni,p,bytes,flags,nullptr,&m->md);}
    CK(rc);
    CK(cxil_alloc_domain(r->lni,r->vni,C_PID_ANY,&m->domain));
    cxi_pt_alloc_opts po{};CK(cxil_alloc_pte(r->lni,r->eq,&po,&m->pte));
    CK(cxil_map_pte(m->pte,m->domain,0,false,&m->pmap));
    union c_cmdu cmd{};cmd.set_state.command.opcode=C_CMD_TGT_SETSTATE;
    cmd.set_state.ptlte_index=m->pte->ptn;cmd.set_state.ptlte_state=C_PTLTE_ENABLED;
    CK(cxi_cq_emit_target(r->target,&cmd));cxi_cq_ring(r->target);expect(r->eq,C_EVENT_STATE_CHANGE);
    memset(&cmd,0,sizeof(cmd));cmd.target.command.opcode=C_CMD_TGT_APPEND;
    cmd.target.ptlte_index=m->pte->ptn;cmd.target.ptl_list=C_PTL_LIST_PRIORITY;
    cmd.target.op_put=1;cmd.target.op_get=1;cmd.target.buffer_id=7;cmd.target.lac=m->md->lac;
    cmd.target.start=CXI_VA_TO_IOVA(m->md,p);cmd.target.length=bytes;
    cmd.target.event_success_disable=1;cmd.target.match_id=CXI_MATCH_ID_ANY;
    CK(cxi_cq_emit_target(r->target,&cmd));cxi_cq_ring(r->target);expect(r->eq,C_EVENT_LINK);
    r->memories++;m->counted=true;return m;
  } catch(...) {cxi_memory_close(m);throw;}
}

CxiPeerAddress cxi_memory_peer(CxiMemory* m) {
  CxiPeerAddress p{};p.nid=m->r->dev->info.nid;p.pid=m->domain->pid;p.pid_bits=m->r->dev->info.pid_bits;
  union c_fab_addr dfa{};uint8_t ext;cxi_build_dfa(p.nid,p.pid,p.pid_bits,0,&dfa,&ext);
  static_assert(sizeof(dfa)==4,"DFA ABI");memcpy(&p.dfa,&dfa,4);p.index_ext=ext;return p;
}
void cxi_memory_local(CxiMemory* m,CxiWindow* w) {
  w->abi_version=CXI_GIN_ABI_VERSION;w->bytes=m->bytes;
  w->local_pointer=(uint64_t)m->pointer;
  w->local_iova=CXI_VA_TO_IOVA(m->md,m->pointer);w->local_lac=m->md->lac;
}

CxiChannel* cxi_channel_open(CxiResources* r,unsigned depth) {
  depth=std::max(depth,64u);
  // CT destruction is deferred by the CXI driver until LNI cleanup. Reuse
  // healthy channels instead of exhausting CT IDs on a long-lived NCCL comm.
  for(auto it=r->idle_channels.begin();it!=r->idle_channels.end();++it) {
    auto* q=*it;
    if(q->depth>=depth){r->idle_channels.erase(it);q->pooled=false;r->reused_channels++;return q;}
  }
  auto* q=new CxiChannel;q->r=r;q->depth=depth;
  try {
    CK(cudaSetDevice(r->gpu));
    cxi_cq_alloc_opts qo{};qo.count=std::max(depth,64u);qo.flags=CXI_CQ_IS_TX;qo.lcid=r->cp->lcid;qo.policy=CXI_CQ_UPDATE_ALWAYS;
    CK(cxil_alloc_cmdq(r->lni,r->eq,&qo,&q->tx));
    q->wb=page_alloc(65536);q->diag=page_alloc(65536);
    auto& d=q->descriptor;d.abi_version=CXI_GIN_ABI_VERSION;
    d.ct_writeback=(uint64_t*)r->map(q->wb,65536,false);q->wbmap=true;
    d.diagnostic=(uint64_t*)r->map(q->diag,65536,false);q->diagmap=true;
    CK(cxil_alloc_ct(r->lni,(c_ct_writeback*)q->wb,&q->ct));
    qo.count=64;qo.flags=CXI_CQ_IS_TX|CXI_CQ_TX_WITH_TRIG_CMDS;qo.lcid=r->trig_cp->lcid;
    CK(cxil_alloc_cmdq(r->lni,r->eq,&qo,&q->trig));
    q->dbpage=(void*)((uintptr_t)q->tx->wp_addr&~(uintptr_t)4095);
    q->ctdbpage=(void*)((uintptr_t)q->trig->wp_addr&~(uintptr_t)4095);
    auto db=(char*)r->map(q->dbpage,4096,true);q->dbmap=true;
    d.tx_doorbell=(uint64_t*)(db+((uintptr_t)q->tx->wp_addr-(uintptr_t)q->dbpage));
    db=(char*)r->map(q->ctdbpage,4096,true);q->ctdbmap=true;
    d.ct_doorbell=(uint64_t*)(db+((uintptr_t)q->trig->wp_addr-(uintptr_t)q->ctdbpage));
    d.tx_queue=(uint64_t*)r->map(q->tx->cmds32,q->tx->size*64,false);q->txmap=true;
    d.ct_queue=(uint64_t*)r->map(q->trig->cmds32,q->trig->size*64,false);q->ctmap=true;
    d.tx_wp32=q->tx->wp32;d.tx_size32=q->tx->size32;d.ct_wp32=q->trig->wp32;d.ct_size32=q->trig->size32;
    d.ct_id=q->ct->ctn;d.eq_id=r->eq->eqn;
    if(getenv("CXI_QUEUE_INVENTORY"))fprintf(stderr,
      "CXI_QUEUE gpu=%d requested=%u tx_size32=%u tx_wp32=%u ct_size32=%u ct_id=%u eq_id=%u\n",
      r->gpu,depth,d.tx_size32,d.tx_wp32,d.ct_size32,d.ct_id,d.eq_id);
    r->channels++;r->created_channels++;q->counted=true;return q;
  } catch(...) {cxi_resources_report(r,"channel-allocation-failed");cxi_channel_close(q);throw;}
}
CxiGpuContext cxi_channel_descriptor(CxiChannel* q){return q->descriptor;}

namespace {
bool cleanup_rc(CxiResources* r,int rc,const char* operation){if(rc){r->errors++;fprintf(stderr,"CXI cleanup %s rc=%d; dependent resources retained\n",operation,rc);}return rc==0;}
// Never release the storage/owner of a resource whose teardown failed.
#define CLEAN_FIELD(r,field,operation) do {if(field){if(!cleanup_rc(r,(operation),#operation))return 1;field=nullptr;}} while(0)
#define UNMAP_FIELD(q,flag,pointer) do {if(q->flag){if(r->unmap(pointer))return 1;q->flag=false;}} while(0)
}
int cxi_channel_close(CxiChannel* q,const CxiGpuContext* state) {
  if(!q)return 0;auto* r=q->r;int before=r->errors;
  if(state){if(q->tx){q->tx->wp32=state->tx_wp32;q->tx->hw_wp32=state->tx_wp32;}if(q->trig){q->trig->wp32=state->ct_wp32;q->trig->hw_wp32=state->ct_wp32;}}
  UNMAP_FIELD(q,txmap,q->tx->cmds32);UNMAP_FIELD(q,ctmap,q->trig->cmds32);
  UNMAP_FIELD(q,dbmap,q->dbpage);UNMAP_FIELD(q,ctdbmap,q->ctdbpage);
  CLEAN_FIELD(r,q->trig,cxil_destroy_cmdq(q->trig));CLEAN_FIELD(r,q->tx,cxil_destroy_cmdq(q->tx));
  CLEAN_FIELD(r,q->ct,cxil_destroy_ct(q->ct));
  UNMAP_FIELD(q,wbmap,q->wb);UNMAP_FIELD(q,diagmap,q->diag);
  free(q->wb);free(q->diag);if(q->counted)r->channels--;delete q;return r->errors!=before;
}
namespace {
// Called only by context destruction after cudaDeviceSynchronize and device
// state capture. No GPU producer is active. This issues local CT_GET commands,
// never TX payload, signal, fence or delivery-marker commands. Steady-state
// dispatch/combine remain entirely GPU-initiated.
int refresh_retired_completion(CxiChannel* q, CxiGpuContext& state) {
  const double deadline=now()+5.0;
  const uint64_t old_completed=state.completed;
  auto failure=[&](const char* reason,uint64_t observed) {
    q->r->errors++;
    fprintf(stderr,"CXI retirement failure gpu=%d ct=%u reason=%s posted=%llu completed=%llu observed=%llu\n",
      q->r->gpu,state.ct_id,reason,(unsigned long long)state.posted,
      (unsigned long long)state.completed,(unsigned long long)observed);
    return 1;
  };
  if(state.completed>state.posted || state.posted>=(1ULL<<48))
    return failure("invalid-completion-range",state.completed);
  auto wait_empty=[&](cxi_cq* cq,uint32_t expected32) {
    for(;;) {
      uint64_t status=__atomic_load_n((uint64_t*)cq->cmds32,__ATOMIC_ACQUIRE);
      c_cq_status decoded{};
      static_assert(sizeof(decoded)==sizeof(status), "CXI CQ status layout changed");
      memcpy(&decoded,&status,sizeof(decoded));
      if(decoded.num_write_cmds_rejected || decoded.fail_command || decoded.return_code!=C_RC_OK)
        return failure("queue-status",status);
      uint32_t rp32=uint32_t(decoded.rd_ptr)*2;
      if(rp32==expected32 || (rp32==0 && expected32==8))return 0;
      if(now()>deadline)return failure("queue-drain-timeout",status);
      usleep(10);
    }
  };
  // Reconcile the CPU helper cursors with the final GPU-owned queue cursors.
  // Updating these fields does not ring a doorbell or publish TX commands.
  q->tx->wp32=q->tx->hw_wp32=state.tx_wp32;
  q->trig->wp32=q->trig->hw_wp32=state.ct_wp32;
  if(wait_empty(q->tx,state.tx_wp32) || wait_empty(q->trig,state.ct_wp32))return 1;
  q->trig->rp32=state.ct_wp32;
  unsigned reads=0;
  for(;;) {
    __atomic_store_n((uint64_t*)q->wb,0ULL,__ATOMIC_RELEASE);
    c_ct_cmd get{};get.ct=q->ct->ctn;
    int rc=cxi_cq_emit_ct(q->trig,C_CMD_CT_GET,&get);
    if(rc)return failure("ct-get-submit",uint64_t(int64_t(rc)));
    cxi_cq_ring(q->trig);reads++;
    uint64_t value;
    do {
      value=__atomic_load_n((uint64_t*)q->wb,__ATOMIC_ACQUIRE);
      if(now()>deadline)return failure("ct-writeback-timeout",value);
      if(!(value&(1ULL<<63)))usleep(10);
    }while(!(value&(1ULL<<63)));
    if((value>>48)&127)return failure("ct-failure",value);
    uint64_t completed=value&((1ULL<<48)-1);
    if(completed<state.completed || completed>state.posted)
      return failure("ct-count-mismatch",value);
    if(wait_empty(q->trig,q->trig->wp32))return 1;
    state.ct_wp32=q->trig->wp32;
    q->trig->rp32=state.ct_wp32;
    state.completed=completed;
    if(completed==state.posted)break;
    if(now()>deadline)return failure("completion-timeout",value);
    usleep(10);
  }
  if(getenv("CXI_QUEUE_INVENTORY"))
    fprintf(stderr,"CXI_RETIRE_REFRESH gpu=%d ct=%u before=%llu posted=%llu completed=%llu reads=%u teardown_only=1\n",
      q->r->gpu,state.ct_id,(unsigned long long)old_completed,
      (unsigned long long)state.posted,(unsigned long long)state.completed,reads);
  return 0;
}
} // namespace


int cxi_channel_recycle(CxiChannel* q,const CxiGpuContext* state) {
  if(!q)return 0;
  if(q->pooled)return 1;
  // Without a device array, context construction failed before GPU use. A
  // channel acquired from the pool still has valid saved cursors/counters.
  if(!state && q->counted)state=&q->descriptor;
  // Partial setup, diagnostics, or unfinished work are never reusable. Keep
  // the existing checked teardown for these paths, including negative tests.
  if(!state || state->abi_version!=CXI_GIN_ABI_VERSION || state->lock ||
     state->pending_dst || state->tx_unpublished || cxi_channel_error(q))
    return cxi_channel_close(q,state);
  const auto& previous=q->descriptor;
  if(state->tx_queue!=previous.tx_queue || state->ct_queue!=previous.ct_queue ||
     state->ct_id!=previous.ct_id || state->ct_writeback!=previous.ct_writeback)
    return 1;
  CxiGpuContext retired=*state;
  if(retired.posted!=retired.completed && refresh_retired_completion(q,retired))return 1;
  state=&retired;
  q->descriptor=*state;
  // Signals belong to the destroyed device context. Queue/CT counters and
  // cursors remain monotonic and must not be reset while the hardware lives.
  q->descriptor.signals=nullptr;q->descriptor.counters=nullptr;
  q->descriptor.signal_window=nullptr;q->descriptor.signal_offset=0;
  q->descriptor.pending_local_addr=0;q->descriptor.pending_remote_offset=0;
  q->descriptor.pending_lac=0;q->descriptor.pending_peer=0;
  q->descriptor.nsignals=0;q->descriptor.ncounters=0;
  q->pooled=true;q->r->idle_channels.push_back(q);return 0;
}
void cxi_resources_report(CxiResources* r,const char* phase) {
  if(!r || !r->dev)return;
  cxi_rsrc_use use{};int rc=cxil_get_svc_rsrc_use(r->dev,r->svc,&use);
  fprintf(stderr,"CXI pool phase=%s gpu=%d created=%llu reused=%llu allocated=%u idle=%zu ct_in_use=%d usage_rc=%d\n",
    phase,r->gpu,(unsigned long long)r->created_channels,(unsigned long long)r->reused_channels,
    r->channels,r->idle_channels.size(),rc?-1:(int)use.in_use[CXI_RSRC_TYPE_CT],rc);
}
int cxi_memory_close(CxiMemory* m) {
  if(!m)return 0;auto* r=m->r;int before=r->errors;
  CLEAN_FIELD(r,m->pmap,cxil_unmap_pte(m->pmap));CLEAN_FIELD(r,m->pte,cxil_destroy_pte(m->pte));
  CLEAN_FIELD(r,m->md,cxil_unmap(m->md));
  if(m->fd>=0){int fd=m->fd;m->fd=-1;if(!cleanup_rc(r,close(fd),"close(dmabuf)"))return 1;}
  CLEAN_FIELD(r,m->domain,cxil_destroy_domain(m->domain));if(m->counted)r->memories--;
  delete m;return r->errors!=before;
}
int cxi_resources_errors(CxiResources* r) {
  if(!r)return 1;
  for(unsigned i=0;i<32 && r->eq;i++){const union c_event* e=cxi_eq_get_event(r->eq);if(!e)break;
    unsigned code=cxi_event_rc(e);fprintf(stderr,"CXI observed event type=%u rc=%u\n",e->hdr.event_type,code);
    if(code!=C_RC_OK)r->errors++;
  }
  if(r->eq)cxi_eq_ack_events(r->eq);return r->errors;
}
int cxi_resources_close(CxiResources* r) {
  if(!r)return 0;
  if(r->memories || r->channels!=r->idle_channels.size()){
    fprintf(stderr,"CXI resources still own %u MRs/%u channels (%zu idle)\n",r->memories,r->channels,r->idle_channels.size());return 1;
  }
  while(!r->idle_channels.empty()) {
    auto* q=r->idle_channels.back();
    if(cxi_channel_close(q,&q->descriptor))return 1;
    r->idle_channels.pop_back();
  }
  if(!r->mappings.empty()){fprintf(stderr,"CXI resources retain CUDA mappings\n");return 1;}
  CLEAN_FIELD(r,r->target,cxil_destroy_cmdq(r->target));CLEAN_FIELD(r,r->eq,cxil_destroy_evtq(r->eq));
  CLEAN_FIELD(r,r->eqmd,cxil_unmap(r->eqmd));free(r->eqbuf);r->eqbuf=nullptr;
  CLEAN_FIELD(r,r->trig_cp,cxil_destroy_cp(r->trig_cp));CLEAN_FIELD(r,r->cp,cxil_destroy_cp(r->cp));
  CLEAN_FIELD(r,r->lni,cxil_destroy_lni(r->lni));if(r->dev)cxil_close_device(r->dev);
  int rc=r->errors;delete r;return rc?1:0;
}

uint64_t cxi_channel_error(CxiChannel* q) {return q && q->diag?__atomic_load_n((uint64_t*)q->diag,__ATOMIC_ACQUIRE):0;}
