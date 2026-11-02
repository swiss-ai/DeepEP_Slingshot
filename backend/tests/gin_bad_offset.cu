#include <nccl.h>
#include <nccl_device.h>
#include <cstdio>
#include <cstdlib>
#include <dlfcn.h>
#include <stdexcept>
#include <string>

__global__ void invalid_offset(ncclDevComm_t comm,ncclWindow_t window) {
  ncclGin gin(comm,0);
  // Reject an offset beyond both the logical window and NCCL's potentially
  // rounded physical registration. No CXI command may be emitted.
  gin.put(ncclTeamWorld(comm),comm.rank^4,window,size_t(1)<<56,window,0,8);
}
static void ck(int rc,const char* op){if(rc)throw std::runtime_error(std::string(op)+" rc="+std::to_string(rc));}
#define CK(x) ck((x),#x)
extern "C" int gin_bad_offset(void* raw,const char* path,int,int) {
  auto comm=(ncclComm_t)raw;FILE* f=fopen(path,"w");if(!f)return 1;
  void* pointer=nullptr;ncclWindow_t window=nullptr;ncclDevComm_t dev{};
  try {
    ncclCommProperties_t p=NCCL_COMM_PROPERTIES_INITIALIZER;CK(ncclCommQueryProperties(comm,&p));
    if(p.nRanks!=8)throw std::runtime_error("requires EP8");
    void* plugin=dlopen(getenv("NCCL_GIN_PLUGIN"),RTLD_NOW|RTLD_LOCAL);
    auto diagnostic=reinterpret_cast<uint64_t(*)()>(plugin?dlsym(plugin,"cxiGinLastDiagnostic"):nullptr);
    if(!diagnostic)throw std::runtime_error("diagnostic accessor unavailable");
    CK(ncclMemAlloc(&pointer,65536));CK(cudaMemset(pointer,0,65536));CK(cudaDeviceSynchronize());
    CK(ncclCommWindowRegister(comm,pointer,65536,&window,NCCL_WIN_COLL_SYMMETRIC));
    ncclDevCommRequirements_t req=NCCL_DEV_COMM_REQUIREMENTS_INITIALIZER;
    req.ginType=(ncclGinType_t)6;req.ginContextCount=1;req.ginExclusiveContexts=true;
    req.ginSignalCount=1;
    req.ginConnectionType=NCCL_GIN_CONNECTION_RAIL;
    CK(ncclDevCommCreate(comm,&req,&dev));
    if(!dev.ginConnectionCount)throw std::runtime_error("missing GIN connection");
    for(unsigned i=0;i<dev.ginConnectionCount;i++)if(dev.ginNetDeviceTypes[i]!=6)throw std::runtime_error("proxy fallback forbidden");
    CK(ncclAllReduce(pointer,pointer,1,ncclInt,ncclSum,comm,0));CK(cudaDeviceSynchronize());
    invalid_offset<<<1,1>>>(dev,window);CK(cudaGetLastError());
    auto cuda_rc=cudaDeviceSynchronize();auto code=diagnostic();
    bool expected=cuda_rc!=cudaSuccess && code==11;
    fprintf(f,"{\"rank\":%d,\"expected_negative\":%s,\"cuda_rc\":%d,\"diagnostic\":%llu,\"termination\":\"process group restart required\"}\n",
      p.rank,expected?"true":"false",(int)cuda_rc,(unsigned long long)code);
    fflush(f);fclose(f);fflush(stderr);
    // Fatal CUDA errors require process termination. Positive lifecycle tests
    // independently require successful explicit teardown, with no skipped frees.
    std::_Exit(expected?86:87);
  }catch(const std::exception& e) {
    fprintf(f,"{\"setup_failure\":true}\n");fflush(f);
    fprintf(stderr,"negative offset setup failed: %s\n",e.what());fflush(stderr);
    std::_Exit(87);
  }
}
