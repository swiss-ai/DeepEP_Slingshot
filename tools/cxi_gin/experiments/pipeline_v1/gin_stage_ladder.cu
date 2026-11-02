// Public-GIN transport intervention probe, not an additive decomposition of DeepEP.
// 64 CTAs x 4 producer warps, matching the current 256 dispatch channels.
#include <nccl.h>
#include <nccl_device.h>
#include <cstdio>
#include <cstdlib>
#include <vector>
#include <string>
#include <stdexcept>

constexpr int channels=256;
constexpr size_t row_bytes=4320;
constexpr uint64_t timeout_cycles=15000000000ULL;
struct Stamp {uint64_t ready,submitted,flushed,received;unsigned errors;};
__device__ uint64_t now_ns(){uint64_t value;asm volatile("mov.u64 %0, %%globaltimer;":"=l"(value));return value;}
__device__ uint64_t pattern(int rank,int iteration,size_t word){
  return (uint64_t(rank+1)<<56) ^ (uint64_t(iteration+1)<<32) ^ uint64_t(word+1);
}
__global__ void initialize(uint64_t* src,uint64_t* dst,size_t words,int rank,int iteration){
  for(size_t i=blockIdx.x*blockDim.x+threadIdx.x;i<words;i+=gridDim.x*blockDim.x){
    src[i]=pattern(rank,iteration,i);dst[i]=0;
  }
}
__global__ void transfer(ncclDevComm_t comm,ncclWindow_t sw,ncclWindow_t dw,
                         int contexts,int rows,int interval,bool coalesce,int iteration,Stamp* stamps){
  if(threadIdx.x%32)return;
  const int channel=blockIdx.x*4+threadIdx.x/32,peer=comm.rank^4;
  const int per_sm=(contexts-1)/64;
  const int context=1+blockIdx.x+(threadIdx.x/32%per_sm)*64;
  ncclGin gin(comm,context,NCCL_GIN_RESOURCE_SHARING_CTA);
  auto team=ncclTeamWorld(comm);auto& s=stamps[channel];
  const int first=channel*rows/channels,last=(channel+1)*rows/channels;
  const int count=last-first,updates=(interval?count/interval:0)+1;
  gin.signal(team,peer,ncclGin_SignalInc{unsigned(channel*2)});
  auto rc=gin.waitSignal(ncclCoopThread(),channel*2,iteration+1,64,cuda::memory_order_acquire,timeout_cycles);
  if(rc!=ncclSuccess){s.errors++;return;}
  s.ready=now_ns();
  const int step=coalesce?count:1;
  for(int row=first;row<last;row+=step){
    gin.put(team,peer,dw,size_t(row)*row_bytes,sw,size_t(row)*row_bytes,size_t(step)*row_bytes,
            ncclGin_None{},ncclGin_None{},ncclCoopThread{},ncclGin_None{},
            cuda::thread_scope_thread,cuda::thread_scope_device,ncclGinOptFlagsAggregateRequests);
    if(interval && (row-first+1)%interval==0)
      gin.signal(team,peer,ncclGin_SignalInc{unsigned(channel*2+1)});
  }
  s.submitted=now_ns();
  // Retain strong visibility before readiness, just as in the EP path.
  gin.signal(team,peer,ncclGin_SignalInc{unsigned(channel*2+1)});
  rc=gin.flush(ncclCoopThread(),cuda::memory_order_acquire,ncclGin_None{},timeout_cycles);
  if(rc!=ncclSuccess){s.errors++;return;}
  s.flushed=now_ns();
  rc=gin.waitSignal(ncclCoopThread(),channel*2+1,uint64_t(iteration+1)*updates,64,
                    cuda::memory_order_acquire,timeout_cycles);
  if(rc!=ncclSuccess){s.errors++;return;}
  s.received=now_ns();
}
__global__ void validate(const uint64_t* dst,size_t words,int peer,int iteration,unsigned* errors){
  for(size_t i=blockIdx.x*blockDim.x+threadIdx.x;i<words;i+=gridDim.x*blockDim.x)
    if(dst[i]!=pattern(peer,iteration,i))atomicAdd(errors,1u);
}
void ck(int rc,const char* op){if(rc)throw std::runtime_error(std::string(op)+" rc="+std::to_string(rc));}
#define CK(x) ck((x),#x)
int option(const char* key,int fallback){auto* value=getenv(key);return value?atoi(value):fallback;}

extern "C" int gin_stage_ladder(void* raw,const char* path,int contexts,int rounds){
  auto comm=(ncclComm_t)raw;FILE* f=fopen(path,"w");if(!f)return -1;
  uint64_t *src=nullptr,*dst=nullptr;Stamp* device=nullptr;unsigned* errors=nullptr;
  ncclWindow_t sw=nullptr,dw=nullptr;ncclDevComm_t dev{};bool created=false;
  cudaEvent_t begin=nullptr,end=nullptr;int verdict=1;
  try{
    const int rows=option("CXI_LADDER_ROWS",4096),interval=option("CXI_LADDER_SIGNAL_INTERVAL",0);
    const bool coalesce=option("CXI_LADDER_COALESCE",0);
    if((contexts!=65 && contexts!=129 && contexts!=257) || rows<256 || rows%256 || rounds<1 ||
       interval<0 || interval>64 || (coalesce && interval))throw std::runtime_error("invalid ladder dimensions");
    ncclCommProperties_t p=NCCL_COMM_PROPERTIES_INITIALIZER;CK(ncclCommQueryProperties(comm,&p));
    if(p.nRanks!=8)throw std::runtime_error("ladder requires EP8");
    const size_t bytes=size_t(rows)*row_bytes,words=bytes/8;
    CK(ncclMemAlloc((void**)&src,bytes));CK(ncclMemAlloc((void**)&dst,bytes));
    CK(ncclCommWindowRegister(comm,src,bytes,&sw,NCCL_WIN_COLL_SYMMETRIC));
    CK(ncclCommWindowRegister(comm,dst,bytes,&dw,NCCL_WIN_COLL_SYMMETRIC));
    ncclDevCommRequirements_t req=NCCL_DEV_COMM_REQUIREMENTS_INITIALIZER;
    req.ginType=(ncclGinType_t)6;req.ginContextCount=contexts;req.ginExclusiveContexts=true;
    req.ginQueueDepth=1024;req.ginSignalCount=channels*2;req.ginStrongSignalsRequired=true;
    req.ginConnectionType=NCCL_GIN_CONNECTION_RAIL;
    CK(ncclDevCommCreate(comm,&req,&dev));created=true;
    for(unsigned i=0;i<dev.ginConnectionCount;i++)if(dev.ginNetDeviceTypes[i]!=6)
      throw std::runtime_error("proxy fallback forbidden");
    CK(cudaMalloc(&device,channels*sizeof(Stamp)));CK(cudaMalloc(&errors,sizeof(unsigned)));
    CK(cudaEventCreate(&begin));CK(cudaEventCreate(&end));
    for(int iteration=0;iteration<rounds;iteration++){
      initialize<<<256,256>>>(src,dst,words,p.rank,iteration);CK(cudaGetLastError());
      CK(cudaMemset(device,0,channels*sizeof(Stamp)));CK(cudaMemset(errors,0,sizeof(unsigned)));
      // Host collective is outside timing and prevents reset racing a previous peer epoch.
      CK(ncclAllReduce(errors,errors,1,ncclUint32,ncclSum,comm,0));CK(cudaDeviceSynchronize());
      CK(cudaEventRecord(begin));
      transfer<<<64,128>>>(dev,sw,dw,contexts,rows,interval,coalesce,iteration,device);
      CK(cudaGetLastError());CK(cudaEventRecord(end));CK(cudaEventSynchronize(end));
      float elapsed=0;CK(cudaEventElapsedTime(&elapsed,begin,end));
      validate<<<256,256>>>(dst,words,p.rank^4,iteration,errors);CK(cudaGetLastError());
      std::vector<Stamp> host(channels);unsigned bad=0;
      CK(cudaMemcpy(host.data(),device,channels*sizeof(Stamp),cudaMemcpyDeviceToHost));
      CK(cudaMemcpy(&bad,errors,sizeof(unsigned),cudaMemcpyDeviceToHost));
      for(int channel=0;channel<channels;channel++){
        auto s=host[channel];bad+=s.errors;
        if(!s.ready || s.submitted<s.ready || s.flushed<s.submitted || s.received<s.flushed)bad++;
        fprintf(f,"{\"rank\":%d,\"iteration\":%d,\"channel\":%d,\"ready_ns\":%llu,\"submitted_ns\":%llu,\"flushed_ns\":%llu,\"received_ns\":%llu,\"errors\":%u}\n",
                p.rank,iteration,channel,(unsigned long long)s.ready,(unsigned long long)s.submitted,
                (unsigned long long)s.flushed,(unsigned long long)s.received,s.errors);
      }
      fprintf(f,"{\"rank\":%d,\"iteration\":%d,\"contexts\":%d,\"rows\":%d,\"row_bytes\":%zu,\"signal_interval\":%d,\"coalesce\":%s,\"cuda_ms\":%.6f,\"errors\":%u}\n",
              p.rank,iteration,contexts,rows,row_bytes,interval,coalesce?"true":"false",elapsed,bad);fflush(f);
      if(bad)throw std::runtime_error("ladder payload or timestamp failure");
    }
    verdict=0;
  }catch(const std::exception& e){fprintf(stderr,"stage ladder: %s\n",e.what());}
  if(created && ncclDevCommDestroy(comm,&dev)!=ncclSuccess)verdict=1;
  if(sw && ncclCommWindowDeregister(comm,sw)!=ncclSuccess)verdict=1;
  if(dw && ncclCommWindowDeregister(comm,dw)!=ncclSuccess)verdict=1;
  if(src && ncclMemFree(src)!=ncclSuccess)verdict=1;if(dst && ncclMemFree(dst)!=ncclSuccess)verdict=1;
  if(device && cudaFree(device)!=cudaSuccess)verdict=1;if(errors && cudaFree(errors)!=cudaSuccess)verdict=1;
  if(begin && cudaEventDestroy(begin)!=cudaSuccess)verdict=1;if(end && cudaEventDestroy(end)!=cudaSuccess)verdict=1;
  fprintf(f,"{\"complete\":true,\"contexts\":%d,\"rounds_requested\":%d,\"rc\":%d}\n",contexts,rounds,verdict);
  fclose(f);return verdict;
}
