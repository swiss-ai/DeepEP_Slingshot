#include <nccl.h>
#include <nccl_device.h>
#include <cstdio>
#include <vector>
#include <stdexcept>
#include <string>

constexpr uint64_t timeout_cycles=15000000000ULL;
struct StressResult {unsigned rounds,errors;};
__global__ void producers(ncclDevComm_t comm,ncclWindow_t window,uint64_t* data,unsigned rounds,StressResult* result) {
  const int peer=comm.rank^4,slot=blockIdx.x*32+threadIdx.x;
  ncclGin gin(comm,0,NCCL_GIN_RESOURCE_SHARING_GPU);auto world=ncclTeamWorld(comm);
  unsigned ready=blockIdx.x*2,ack=ready+1;
  for(unsigned round=0;round<rounds;round++) {
    uint64_t value=((uint64_t)comm.rank<<48)|((uint64_t)round<<32)|(slot+1);
    // All lanes submit to one context. This deliberately tests divergent
    // contention within a warp as well as contention between CTAs.
    gin.putValue(world,peer,window,slot*8,value,ncclGin_SignalInc{ready});
    gin.flush(ncclCoopCta());
    auto rc=gin.waitSignal(ncclCoopCta(),ready,(round+1)*32,64,cuda::memory_order_acquire,timeout_cycles);
    if(rc!=ncclSuccess){if(threadIdx.x==0)result[blockIdx.x].errors++;return;}
    uint64_t got=*(volatile uint64_t*)(data+slot);
    uint64_t expected=((uint64_t)peer<<48)|((uint64_t)round<<32)|(slot+1);
    if(got!=expected)atomicAdd(&result[blockIdx.x].errors,1u);
    __syncthreads();if(result[blockIdx.x].errors)return;
    gin.signal(world,peer,ncclGin_SignalInc{ack},ncclCoopCta());
    rc=gin.waitSignal(ncclCoopCta(),ack,round+1,64,cuda::memory_order_acquire,timeout_cycles);
    if(rc!=ncclSuccess){if(threadIdx.x==0)result[blockIdx.x].errors++;return;}
    if(threadIdx.x==0)result[blockIdx.x].rounds++;
  }
  gin.flush(ncclCoopCta());
}
void ck(int rc,const char* op){if(rc)throw std::runtime_error(std::string(op)+" rc="+std::to_string(rc));}
#define CK(x) ck((x),#x)
extern "C" int gin_producer_stress(void* raw,const char* path,int blocks,int rounds) {
  auto comm=(ncclComm_t)raw;FILE* f=fopen(path,"w");if(!f)return -1;
  uint64_t* data=nullptr;StressResult* results=nullptr;ncclWindow_t window=nullptr;ncclDevComm_t dev{};
  bool created=false;int verdict=1;
  try {
    if(blocks<1 || blocks>8 || rounds<1)throw std::runtime_error("invalid stress dimensions");
    CK(ncclMemAlloc((void**)&data,65536));CK(cudaMemset(data,0,65536));CK(cudaDeviceSynchronize());
    CK(ncclCommWindowRegister(comm,data,65536,&window,NCCL_WIN_COLL_SYMMETRIC));
    ncclDevCommRequirements_t req=NCCL_DEV_COMM_REQUIREMENTS_INITIALIZER;
    req.ginType=(ncclGinType_t)6;req.ginContextCount=1;req.ginExclusiveContexts=true;
    req.ginSignalCount=blocks*2;req.ginQueueDepth=1024;req.ginConnectionType=NCCL_GIN_CONNECTION_RAIL;
    req.ginStrongSignalsRequired=true;CK(ncclDevCommCreate(comm,&req,&dev));created=true;
    for(unsigned i=0;i<dev.ginConnectionCount;i++)if(dev.ginNetDeviceTypes[i]!=6)throw std::runtime_error("proxy fallback forbidden");
    CK(cudaMalloc(&results,blocks*sizeof(StressResult)));CK(cudaMemset(results,0,blocks*sizeof(StressResult)));
    producers<<<blocks,32>>>(dev,window,data,rounds,results);CK(cudaGetLastError());CK(cudaDeviceSynchronize());
    std::vector<StressResult> host(blocks);CK(cudaMemcpy(host.data(),results,blocks*sizeof(StressResult),cudaMemcpyDeviceToHost));
    verdict=0;
    for(int i=0;i<blocks;i++) {
      fprintf(f,"{\"block\":%d,\"rounds\":%u,\"errors\":%u}\n",i,host[i].rounds,host[i].errors);
      if(host[i].errors || host[i].rounds!=(unsigned)rounds)verdict=1;
    }
  }catch(const std::exception& e){fprintf(stderr,"producer stress: %s\n",e.what());verdict=1;}
  if(created && ncclDevCommDestroy(comm,&dev)!=ncclSuccess)verdict=1;
  if(window && ncclCommWindowDeregister(comm,window)!=ncclSuccess)verdict=1;
  if(results && cudaFree(results)!=cudaSuccess)verdict=1;
  if(data && ncclMemFree(data)!=ncclSuccess)verdict=1;
  fprintf(f,"{\"complete\":true,\"blocks\":%d,\"rounds_requested\":%d,\"rc\":%d}\n",blocks,rounds,verdict);
  fclose(f);return verdict;
}
