#include <nccl.h>
#include <nccl_device.h>
#include <cstdio>
#include <cstdlib>
#include <vector>
#include <stdexcept>
#include <string>

constexpr size_t stride=(1u<<20)+4096;
constexpr uint64_t timeout_cycles=15000000000ULL;
struct Result {unsigned rounds,errors,stage;uint64_t bad,observed,expected;};
__device__ unsigned char pattern(unsigned rank,unsigned round,size_t i){return (rank*31+round*17+i*7+1)&255;}
__device__ bool wait_idx(ncclGin& gin,unsigned id,uint64_t value,Result* out) {
  auto rc=gin.waitSignal(ncclCoopCta(),id,value,64,cuda::memory_order_acquire,timeout_cycles);
  if(rc!=ncclSuccess){if(threadIdx.x==0){out->errors++;out->stage=10+id;}return false;}return true;
}
__global__ void smoke(ncclDevComm_t comm,ncclWindow_t sw,ncclWindow_t dw,unsigned char* src,unsigned char* dst,
                      unsigned rounds,Result* results) {
  unsigned ctx=blockIdx.x,rank=comm.rank;int peer=rank^4;size_t base=ctx*stride;
  ncclGin gin(comm,ctx);auto world=ncclTeamWorld(comm);auto* out=results+ctx;
  __shared__ ncclGinRequest_t request;
  const size_t sizes[]={0,1,8,64,4096,65536,1u<<20};
  for(unsigned round=0;round<rounds;round++) {
    size_t n=sizes[round%7],soff=base+17+round%3,doff=base+33+round%3;
    for(size_t i=threadIdx.x;i<n;i+=blockDim.x)src[soff+i]=pattern(rank,round,i);
    for(size_t i=threadIdx.x;i<n+64;i+=blockDim.x)dst[doff-32+i]=0x5a;
    __syncthreads();__threadfence_system();
    gin.signal(world,peer,ncclGin_SignalInc{0},ncclCoopCta());
    if(!wait_idx(gin,0,round+1,out))return;
    uint64_t tag=((uint64_t)rank<<32)|round;
    gin.putValue(world,peer,dw,base+stride-32,tag,ncclGin_None{},ncclCoopCta());
    gin.flushAsync(world,peer,&request,ncclCoopCta());
    auto request_rc=gin.wait(request,ncclCoopCta(),ncclGin_None{},cuda::memory_order_acquire,timeout_cycles);
    if(request_rc!=ncclSuccess){if(threadIdx.x==0){out->errors++;out->stage=19;}return;}
    if(round&1)gin.put(world,peer,dw,doff,sw,soff,n,ncclGin_VASignalAdd{dw,base+stride-16,1},ncclGin_WeakCounterInc{0},ncclCoopCta());
    else gin.put(world,peer,dw,doff,sw,soff,n,ncclGin_SignalInc{1},ncclGin_WeakCounterInc{0},ncclCoopCta());
    auto rc=gin.waitCounter(ncclCoopCta(),0,round+1,56,cuda::memory_order_acquire,timeout_cycles);
    if(rc!=ncclSuccess){if(threadIdx.x==0){out->errors++;out->stage=20;}return;}
    for(size_t i=threadIdx.x;i<n;i+=blockDim.x)src[soff+i]=0x3c;
    __syncthreads();
    if(round&1)rc=gin.waitSignal(ncclCoopCta(),dw,base+stride-16,(round+1)/2,64,cuda::memory_order_acquire,timeout_cycles);
    else rc=gin.waitSignal(ncclCoopCta(),1,round/2+1,64,cuda::memory_order_acquire,timeout_cycles);
    if(rc!=ncclSuccess){if(threadIdx.x==0){out->errors++;out->stage=21;}return;}
    for(size_t i=threadIdx.x;i<n+64;i+=blockDim.x) {
      unsigned char got=((volatile unsigned char*)dst)[doff-32+i];
      unsigned char expected=(i<32 || i>=n+32)?0x5a:pattern(peer,round,i-32);
      if(got!=expected){if(atomicAdd(&out->errors,1u)==0){out->bad=doff-32+i;out->observed=got;out->expected=expected;out->stage=22;}}
    }
    if(threadIdx.x==0) {
      uint64_t got=*(volatile uint64_t*)(dst+base+stride-32),expected=((uint64_t)peer<<32)|round;
      if(got!=expected){out->errors++;out->stage=23;out->observed=got;out->expected=expected;}
    }
    __syncthreads();if(out->errors)return;
    gin.signal(world,peer,ncclGin_SignalInc{2},ncclCoopCta());
    if(!wait_idx(gin,2,round+1,out))return;
    rc=gin.flush(ncclCoopCta(),cuda::memory_order_acquire,ncclGin_None{},timeout_cycles);
    if(rc!=ncclSuccess){if(threadIdx.x==0){out->errors++;out->stage=24;}return;}
    if(threadIdx.x==0)out->rounds++;
  }
}
__global__ void reset_smoke(ncclDevComm_t comm,ncclWindow_t dw) {
  ncclGin gin(comm,blockIdx.x);
  gin.resetSignal(0);gin.resetSignal(1);gin.resetSignal(2);gin.resetCounter(0);
  gin.resetSignal(dw,blockIdx.x*stride+stride-16);
}
__global__ void self_signal(ncclDevComm_t comm,int* results) {
  ncclGin gin(comm,blockIdx.x);
  auto target=gin.readSignal(0,64,cuda::memory_order_acquire)+1;
  gin.signal(ncclTeamWorld(comm),comm.rank,ncclGin_SignalInc{0});
  auto wait=gin.waitSignal(ncclCoopThread(),0,target,64,cuda::memory_order_acquire,timeout_cycles);
  auto flush=gin.flush(ncclCoopThread(),cuda::memory_order_acquire,ncclGin_None{},timeout_cycles);
  results[blockIdx.x]=(wait==ncclSuccess && flush==ncclSuccess)?0:1;
}
struct DelayedResult {int first,second,flush;};
__global__ void delayed_peer(ncclDevComm_t comm,DelayedResult* out) {
  ncclGin gin(comm,0);auto world=ncclTeamWorld(comm);int peer=comm.rank^4;
  if(comm.rank<4) {
    out->first=gin.waitSignal(ncclCoopThread(),3,1,64,cuda::memory_order_acquire,10000000ULL);
    out->second=gin.waitSignal(ncclCoopThread(),3,1,64,cuda::memory_order_acquire,timeout_cycles);
    gin.signal(world,peer,ncclGin_SignalInc{4});
  }else {
    auto start=clock64();while(clock64()-start<1000000000ULL)__nanosleep(256);
    gin.signal(world,peer,ncclGin_SignalInc{3});
    out->first=ncclSuccess;
    out->second=gin.waitSignal(ncclCoopThread(),4,1,64,cuda::memory_order_acquire,timeout_cycles);
  }
  out->flush=gin.flush(ncclCoopThread(),cuda::memory_order_acquire,ncclGin_None{},timeout_cycles);
}
// Receiver consumes and clears a PUT destination before sender flush.
// This is legal for self-describing notification data; the sender's source stays
// unchanged. A flush must not write the destination a second time.
struct MutationResult {unsigned rounds,errors,stage;uint32_t observed,expected;};
__global__ void mutation_probe(ncclDevComm_t comm,ncclWindow_t sw,ncclWindow_t dw,
    unsigned char* src,unsigned char* dst,unsigned rounds,bool expect_clobber,MutationResult* out) {
  ncclGin data(comm,0),hand(comm,1);auto world=ncclTeamWorld(comm);int peer=comm.rank^4;
  // Host barriers surround reset_smoke before launch. Never derive a baseline
  // from live peer-updated signals: a fast peer can advance them before we read.
  uint64_t ready=0,cleared=0,flushed=0;
  for(unsigned round=0;round<rounds;round++) {
    *(uint32_t*)src=0xffffffffu;*(uint32_t*)dst=0;__threadfence_system();
    hand.signal(world,peer,ncclGin_SignalInc{0});
    if(hand.waitSignal(ncclCoopThread(),0,++ready,64,cuda::memory_order_acquire,timeout_cycles)!=ncclSuccess){out->stage=1;out->errors++;return;}
    data.put(world,peer,dw,0,sw,0,4,ncclGin_None{},ncclGin_None{},ncclCoopThread());
    uint64_t start=clock64();uint32_t got;
    do {
      asm volatile("ld.acquire.sys.global.u32 %0, [%1];":"=r"(got):"l"(dst):"memory");
      if(clock64()-start>timeout_cycles){out->stage=2;out->errors++;out->observed=got;return;}
    }while(got!=0xffffffffu);
    asm volatile("st.release.sys.global.u32 [%0], %1;"::"l"(dst),"r"(0u):"memory");
    hand.signal(world,peer,ncclGin_SignalInc{1});
    if(hand.waitSignal(ncclCoopThread(),1,++cleared,64,cuda::memory_order_acquire,timeout_cycles)!=ncclSuccess){out->stage=3;out->errors++;return;}
    if(data.flush(ncclCoopThread(),cuda::memory_order_acquire,ncclGin_None{},timeout_cycles)!=ncclSuccess){out->stage=4;out->errors++;return;}
    hand.signal(world,peer,ncclGin_SignalInc{2});
    if(hand.waitSignal(ncclCoopThread(),2,++flushed,64,cuda::memory_order_acquire,timeout_cycles)!=ncclSuccess){out->stage=5;out->errors++;return;}
    asm volatile("ld.acquire.sys.global.u32 %0, [%1];":"=r"(got):"l"(dst):"memory");
    out->observed=got;out->expected=expect_clobber?0xff000000u:0u;
    if(got!=out->expected){out->stage=6;out->errors++;return;}
    hand.signal(world,peer,ncclGin_SignalInc{0});
    if(hand.waitSignal(ncclCoopThread(),0,++ready,64,cuda::memory_order_acquire,timeout_cycles)!=ncclSuccess){out->stage=7;out->errors++;return;}
    out->rounds++;
  }
  if(hand.flush(ncclCoopThread(),cuda::memory_order_acquire,ncclGin_None{},timeout_cycles)!=ncclSuccess){out->stage=8;out->errors++;}
}

static void ck(int rc,const char* op){if(rc)throw std::runtime_error(std::string(op)+" rc="+std::to_string(rc));}
#define CK(x) ck((x),#x)
// Hold one MR across repeated DevComm create/destroy cycles. This keeps the
// plugin LNI live and tests the channel pool rather than process/LNI restart.
struct HeldWindow {ncclComm_t comm;void* memory;ncclWindow_t window;};
extern "C" int gin_hold_window(void* raw,void** out) {
  auto* h=new HeldWindow{(ncclComm_t)raw,nullptr,nullptr};
  try {
    CK(ncclMemAlloc(&h->memory,65536));
    CK(ncclCommWindowRegister(h->comm,h->memory,65536,&h->window,NCCL_WIN_COLL_SYMMETRIC));
    *out=h;return 0;
  } catch(const std::exception& e) {
    fprintf(stderr,"gin_hold_window: %s\n",e.what());
    if(h->window)ncclCommWindowDeregister(h->comm,h->window);
    if(h->memory)ncclMemFree(h->memory);delete h;return 1;
  }
}
extern "C" int gin_release_window(void* raw) {
  auto* h=(HeldWindow*)raw;if(!h)return 0;
  if(ncclCommWindowDeregister(h->comm,h->window)!=ncclSuccess)return 1;
  if(ncclMemFree(h->memory)!=ncclSuccess)return 1;
  delete h;return 0;
}
extern "C" int gin_smoke(void* raw,const char* path,int contexts,int rounds) {
  auto comm=(ncclComm_t)raw;FILE* f=fopen(path,"w");if(!f)return -1;
  unsigned char *src=nullptr,*dst=nullptr;Result* dr=nullptr;ncclWindow_t sw=nullptr,dw=nullptr;
  ncclDevComm_t dev{};bool created=false;int result=1;DelayedResult* delayed=nullptr;int* self_results=nullptr;MutationResult* mutation=nullptr;
  try {
    if(contexts<1 || contexts>129 || rounds<1)throw std::runtime_error("invalid smoke parameters");
    ncclCommProperties_t p=NCCL_COMM_PROPERTIES_INITIALIZER;CK(ncclCommQueryProperties(comm,&p));
    if(p.nRanks!=8)throw std::runtime_error("smoke requires eight ranks");
    if(getenv("CXI_SMOKE_NEGATIVE")) {
      ncclDevCommRequirements_t invalid=NCCL_DEV_COMM_REQUIREMENTS_INITIALIZER;
      invalid.version=NCCL_VERSION_CODE+10000;
      ncclDevComm_t rejected{};auto rc=ncclDevCommCreate(comm,&invalid,&rejected);
      fprintf(f,"{\"negative_version\":true,\"rc\":%d,\"expected\":%d}\n",rc,ncclInvalidUsage);fflush(f);
      if(rc==ncclSuccess){ncclDevCommDestroy(comm,&rejected);throw std::runtime_error("invalid version accepted");}
      if(rc!=ncclInvalidUsage)throw std::runtime_error("unexpected version rejection");
    }
    size_t bytes=contexts*stride;CK(ncclMemAlloc((void**)&src,bytes));CK(ncclMemAlloc((void**)&dst,bytes));
    CK(cudaMemset(src,0,bytes));CK(cudaMemset(dst,0,bytes));CK(cudaDeviceSynchronize());
    CK(ncclCommWindowRegister(comm,src,bytes,&sw,NCCL_WIN_COLL_SYMMETRIC));
    CK(ncclCommWindowRegister(comm,dst,bytes,&dw,NCCL_WIN_COLL_SYMMETRIC));
    ncclDevCommRequirements_t req=NCCL_DEV_COMM_REQUIREMENTS_INITIALIZER;
    req.ginType=(ncclGinType_t)6;req.ginContextCount=contexts;req.ginExclusiveContexts=true;
    req.ginQueueDepth=1024;req.ginSignalCount=getenv("CXI_SMOKE_NEGATIVE")?5:3;req.ginCounterCount=1;req.ginStrongSignalsRequired=true;
    req.ginConnectionType=NCCL_GIN_CONNECTION_RAIL;
    CK(ncclDevCommCreate(comm,&req,&dev));created=true;
    for(unsigned i=0;i<dev.ginConnectionCount;i++)if(dev.ginNetDeviceTypes[i]!=6)throw std::runtime_error("unexpected backend: refusing proxy fallback");
    fprintf(f,"{\"rank\":%d,\"contexts\":%d,\"rounds_requested\":%d,\"backend\":6,\"stage\":\"kernel\"}\n",p.rank,contexts,rounds);fflush(f);
    CK(cudaMalloc(&dr,contexts*sizeof(Result)));CK(cudaMemset(dr,0,contexts*sizeof(Result)));
    smoke<<<contexts,128>>>(dev,sw,dw,src,dst,rounds,dr);CK(cudaGetLastError());CK(cudaDeviceSynchronize());
    std::vector<Result> all(contexts);CK(cudaMemcpy(all.data(),dr,contexts*sizeof(Result),cudaMemcpyDeviceToHost));
    result=0;
    for(int i=0;i<contexts;i++) {
      auto& r=all[i];if(r.errors || r.rounds!=(unsigned)rounds)result=1;
      fprintf(f,"{\"context\":%d,\"rounds\":%u,\"errors\":%u,\"stage\":%u,\"bad\":%llu,\"observed\":%llu,\"expected\":%llu}\n",
        i,r.rounds,r.errors,r.stage,(unsigned long long)r.bad,(unsigned long long)r.observed,(unsigned long long)r.expected);
    }
    if(getenv("CXI_SMOKE_RESET") && result==0) {
      // Host collectives establish application-guaranteed quiescence before
      // reset and before the next GPU-only transfer epoch. They are outside
      // the measured/proven NIC data-path kernel.
      CK(ncclAllReduce(dr,dr,1,ncclInt,ncclSum,comm,0));CK(cudaDeviceSynchronize());
      reset_smoke<<<contexts,1>>>(dev,dw);CK(cudaGetLastError());CK(cudaDeviceSynchronize());
      CK(ncclAllReduce(dr,dr,1,ncclInt,ncclSum,comm,0));CK(cudaDeviceSynchronize());
      CK(cudaMemset(dr,0,contexts*sizeof(Result)));
      smoke<<<contexts,128>>>(dev,sw,dw,src,dst,rounds,dr);CK(cudaGetLastError());CK(cudaDeviceSynchronize());
      CK(cudaMemcpy(all.data(),dr,contexts*sizeof(Result),cudaMemcpyDeviceToHost));
      for(int i=0;i<contexts;i++) {
        auto& r=all[i];if(r.errors || r.rounds!=(unsigned)rounds)result=1;
        fprintf(f,"{\"reset_epoch\":1,\"context\":%d,\"rounds\":%u,\"errors\":%u,\"stage\":%u}\n",i,r.rounds,r.errors,r.stage);
      }
    }
    if(getenv("CXI_SMOKE_NEGATIVE") && result==0) {
      CK(cudaMalloc(&delayed,sizeof(DelayedResult)));CK(cudaMemset(delayed,0,sizeof(DelayedResult)));
      CK(ncclAllReduce(dr,dr,1,ncclInt,ncclSum,comm,0));CK(cudaDeviceSynchronize());
      delayed_peer<<<1,1>>>(dev,delayed);CK(cudaGetLastError());CK(cudaDeviceSynchronize());
      DelayedResult r{};CK(cudaMemcpy(&r,delayed,sizeof(r),cudaMemcpyDeviceToHost));
      int expected=p.rank<4?ncclTimeout:ncclSuccess;
      if(r.first!=expected || r.second!=ncclSuccess || r.flush!=ncclSuccess)result=1;
      fprintf(f,"{\"delayed_peer\":true,\"rank\":%d,\"first\":%d,\"expected_first\":%d,\"recovered\":%d,\"flush\":%d}\n",p.rank,r.first,expected,r.second,r.flush);
    }
    if(getenv("CXI_SMOKE_SELF") && result==0) {
      CK(cudaMalloc(&self_results,contexts*sizeof(int)));CK(cudaMemset(self_results,0,contexts*sizeof(int)));
      self_signal<<<contexts,1>>>(dev,self_results);CK(cudaGetLastError());CK(cudaDeviceSynchronize());
      std::vector<int> status(contexts);CK(cudaMemcpy(status.data(),self_results,contexts*sizeof(int),cudaMemcpyDeviceToHost));
      for(int i=0;i<contexts;i++) {if(status[i])result=1;fprintf(f,"{\"self_signal\":true,\"context\":%d,\"rc\":%d}\n",i,status[i]);}
    }
    if(getenv("CXI_MUTATION_EXPECT") && result==0) {
      if(contexts<2)throw std::runtime_error("mutation probe needs separate data/handshake contexts");
      bool clobber=std::string(getenv("CXI_MUTATION_EXPECT"))=="clobber";
      if(!clobber && std::string(getenv("CXI_MUTATION_EXPECT"))!="preserve")throw std::runtime_error("invalid mutation expectation");
      CK(ncclAllReduce(dr,dr,1,ncclInt,ncclSum,comm,0));CK(cudaDeviceSynchronize());
      reset_smoke<<<contexts,1>>>(dev,dw);CK(cudaGetLastError());CK(cudaDeviceSynchronize());
      CK(ncclAllReduce(dr,dr,1,ncclInt,ncclSum,comm,0));CK(cudaDeviceSynchronize());
      CK(cudaMalloc(&mutation,sizeof(MutationResult)));CK(cudaMemset(mutation,0,sizeof(MutationResult)));
      mutation_probe<<<1,1>>>(dev,sw,dw,src,dst,100,clobber,mutation);CK(cudaGetLastError());CK(cudaDeviceSynchronize());
      MutationResult r{};CK(cudaMemcpy(&r,mutation,sizeof(r),cudaMemcpyDeviceToHost));
      if(r.errors || r.rounds!=100)result=1;
      fprintf(f,"{\"mutation_probe\":true,\"expect_clobber\":%s,\"rounds\":%u,\"errors\":%u,\"stage\":%u,\"observed\":%u,\"expected\":%u}\n",clobber?"true":"false",r.rounds,r.errors,r.stage,r.observed,r.expected);
    }
  }catch(const std::exception& e){fprintf(stderr,"GIN smoke: %s\n",e.what());fprintf(f,"{\"exception\":true}\n");result=1;}
  // Teardown is part of the verdict. An errored GPU context remains a failed run.
  if(created && ncclDevCommDestroy(comm,&dev)!=ncclSuccess)result=1;
  if(sw && ncclCommWindowDeregister(comm,sw)!=ncclSuccess)result=1;
  if(dw && ncclCommWindowDeregister(comm,dw)!=ncclSuccess)result=1;
  if(dr && cudaFree(dr)!=cudaSuccess)result=1;
  if(delayed && cudaFree(delayed)!=cudaSuccess)result=1;
  if(self_results && cudaFree(self_results)!=cudaSuccess)result=1;
  if(mutation && cudaFree(mutation)!=cudaSuccess)result=1;
  if(src && ncclMemFree(src)!=ncclSuccess)result=1;
  if(dst && ncclMemFree(dst)!=ncclSuccess)result=1;
  fprintf(f,"{\"complete\":true,\"rc\":%d}\n",result);fclose(f);return result;
}
