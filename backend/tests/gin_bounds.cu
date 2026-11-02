#include <nccl.h>
#include <nccl_device.h>
#include <nccl_device/gin/cxi/cxi_primitives.cuh>
#include <cstdio>
#include <stdexcept>
#include <string>

struct BoundsResult {unsigned cases,errors;uint64_t diagnostic[3];};
__global__ void bounds(ncclDevComm_t comm,ncclWindow_t window,BoundsResult* result) {
  auto* w=(CxiWindow*)nccl::gin::internal::getGinWindow(window,comm.backendIndex,0);
  // Copy the real descriptor, but make accidental NIC submission impossible.
  // The same guard is called by the public API before it posts any command.
  auto scratch=((CxiGpuContext*)comm.ginHandles[0])[0];
  scratch.diagnostic=result->diagnostic;scratch.lock=0;
  scratch.tx_queue=nullptr;scratch.tx_doorbell=nullptr;
  scratch.ct_queue=nullptr;scratch.ct_doorbell=nullptr;scratch.ct_writeback=nullptr;
  const uint64_t offsets[]={w->bytes,w->bytes-4,UINT64_MAX-3,0,0};
  const uint64_t lengths[]={8,8,8,UINT64_MAX,8};
  for(unsigned i=0;i<5;i++) {
    int peer=i==4?(int)w->peers:comm.rank^4;
    result->diagnostic[0]=0;auto before=scratch.posted;
    bool accepted=cxi_gin::put_locked(scratch,w,offsets[i],w,0,lengths[i],peer);
    auto expected=i==4?10u:11u;
    if(accepted || result->diagnostic[0]!=expected || scratch.posted!=before)result->errors++;
    result->cases++;
  }
}
static void ck(int rc,const char* op){if(rc)throw std::runtime_error(std::string(op)+" rc="+std::to_string(rc));}
#define CK(x) ck((x),#x)
extern "C" int gin_bounds(void* raw,const char* path,int,int) {
  auto comm=(ncclComm_t)raw;FILE* f=fopen(path,"w");if(!f)return 1;
  void* pointer=nullptr;ncclWindow_t window=nullptr;ncclDevComm_t dev{};BoundsResult* result=nullptr;
  bool created=false;int verdict=1;
  try {
    CK(ncclMemAlloc(&pointer,65536));CK(cudaMemset(pointer,0,65536));CK(cudaDeviceSynchronize());
    CK(ncclCommWindowRegister(comm,pointer,65536,&window,NCCL_WIN_COLL_SYMMETRIC));
    ncclDevCommRequirements_t req=NCCL_DEV_COMM_REQUIREMENTS_INITIALIZER;
    req.ginType=(ncclGinType_t)6;req.ginContextCount=1;req.ginExclusiveContexts=true;
    req.ginSignalCount=1;
    req.ginConnectionType=NCCL_GIN_CONNECTION_RAIL;
    CK(ncclDevCommCreate(comm,&req,&dev));created=true;
    if(!dev.ginConnectionCount)throw std::runtime_error("missing GIN connection");
    for(unsigned i=0;i<dev.ginConnectionCount;i++)if(dev.ginNetDeviceTypes[i]!=6)throw std::runtime_error("proxy fallback forbidden");
    CK(cudaMalloc(&result,sizeof(BoundsResult)));CK(cudaMemset(result,0,sizeof(BoundsResult)));
    bounds<<<1,1>>>(dev,window,result);CK(cudaGetLastError());CK(cudaDeviceSynchronize());
    BoundsResult host{};CK(cudaMemcpy(&host,result,sizeof(host),cudaMemcpyDeviceToHost));
    verdict=host.cases==5 && host.errors==0?0:1;
    fprintf(f,"{\"cases\":%u,\"errors\":%u,\"scope\":\"actual registered descriptor, isolated guard state, no invalid NIC command submitted\"}\n",host.cases,host.errors);
  }catch(const std::exception& e){fprintf(stderr,"bounds probe: %s\n",e.what());verdict=1;}
  if(created && ncclDevCommDestroy(comm,&dev)!=ncclSuccess)verdict=1;
  if(window && ncclCommWindowDeregister(comm,window)!=ncclSuccess)verdict=1;
  if(result && cudaFree(result)!=cudaSuccess)verdict=1;
  if(pointer && ncclMemFree(pointer)!=ncclSuccess)verdict=1;
  fprintf(f,"{\"complete\":true,\"rc\":%d}\n",verdict);fclose(f);return verdict;
}
