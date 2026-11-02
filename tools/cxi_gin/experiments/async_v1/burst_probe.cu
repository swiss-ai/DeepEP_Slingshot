#include <cuda_runtime.h>
#include "cxi_resources.h"
#include "cxi_primitives.cuh"
#include <cstdio>
#include <cstdlib>
#include <fstream>
#include <string>
#include <stdexcept>
#include <unistd.h>
#include <chrono>

constexpr size_t max_bytes=16u<<20;
constexpr size_t signal_off=max_bytes+1024;
constexpr size_t alloc_bytes=max_bytes+65536;
struct Result {unsigned cases,errors;uint64_t bad_offset,observed,expected;};
__device__ unsigned char pattern(unsigned rank,unsigned round,size_t i){return (rank*31+round*17+i*7+1)&255;}
__device__ bool wait_signal(CxiGpuContext& c,uint64_t* p,uint64_t value){
  uint64_t start=clock64();while(cxi_gin::load64(p)<value){if(clock64()-start>cxi_gin::default_timeout)return cxi_gin::fail(c,30,value,cxi_gin::load64(p));}return true;
}
// Capacity/wrap test: no per-payload flush or signal; 4096 commands per epoch.
__global__ void dynamic_test(CxiGpuContext* context,CxiWindow* srcw,CxiWindow* dstw,unsigned char* src,unsigned char* dst,unsigned rank,Result* out) {
  CxiGpuContext& c=*context; int peer=rank^4; constexpr unsigned count=4096, epochs=4;
  for(unsigned epoch=0;epoch<epochs;epoch++) {
    for(unsigned i=0;i<count;i++) {
      ((uint64_t*)src)[i]=((uint64_t)rank<<48)|((uint64_t)epoch<<32)|(i+1);
      ((uint64_t*)dst)[i]=0;
    }
    __threadfence_system();
    if(!cxi_gin::acquire(c))return;
    bool ok=cxi_gin::add_locked(c,dstw,signal_off,1,peer);
    cxi_gin::release(c);
    if(!ok || !wait_signal(c,(uint64_t*)(dst+signal_off),epoch+1))return;
    for(unsigned i=0;i<count;i++) {
      if(!cxi_gin::acquire(c))return;
      ok=cxi_gin::put_locked(c,dstw,i*8,srcw,i*8,8,peer);
      cxi_gin::release(c);if(!ok)return;
    }
    if(!cxi_gin::flush(c))return;
    // Reuse source only after completion. Receiver must retain original values.
    for(unsigned i=0;i<count;i++)((uint64_t*)src)[i]=0xdeadbeef;
    __threadfence_system();
    if(!cxi_gin::acquire(c))return;
    ok=cxi_gin::add_locked(c,dstw,signal_off+8,1,peer);
    cxi_gin::release(c);
    if(!ok || !wait_signal(c,(uint64_t*)(dst+signal_off+8),epoch+1))return;
    for(unsigned i=0;i<count;i++) {
      uint64_t got=((volatile uint64_t*)dst)[i];
      uint64_t want=((uint64_t)peer<<48)|((uint64_t)epoch<<32)|(i+1);
      if(got!=want){out->errors++;out->bad_offset=i*8;out->observed=got;out->expected=want;return;}
    }
    if(!cxi_gin::acquire(c))return;
    ok=cxi_gin::add_locked(c,dstw,signal_off+16,1,peer);
    cxi_gin::release(c);
    if(!ok || !wait_signal(c,(uint64_t*)(dst+signal_off+16),epoch+1) || !cxi_gin::flush(c))return;
    out->cases++;
  }
}
static void ck(int rc,const char* s){if(rc)throw std::runtime_error(std::string(s)+" rc="+std::to_string(rc));}
#define CK(x) ck((x),#x)
static double secs(){return std::chrono::duration<double>(std::chrono::steady_clock::now().time_since_epoch()).count();}
static CxiPeerAddress exchange(const std::string& dir,unsigned rank,const CxiPeerAddress& mine,const char* label) {
  auto own=dir+"/"+label+"-"+std::to_string(rank);auto tmp=own+".tmp";
  {std::ofstream f(tmp,std::ios::binary);f.write((const char*)&mine,sizeof(mine));if(!f)throw std::runtime_error("peer write");}
  if(rename(tmp.c_str(),own.c_str()))throw std::runtime_error("peer publish");
  auto peer=dir+"/"+label+"-"+std::to_string(rank<4?rank+4:rank-4);double deadline=secs()+25;
  do {CxiPeerAddress p{};std::ifstream f(peer,std::ios::binary);if(f.read((char*)&p,sizeof(p)))return p;usleep(10000);}while(secs()<deadline);
  throw std::runtime_error("peer descriptor timeout");
}
int main(int argc,char** argv) {
  if(argc!=4)return 2;int gpu=atoi(argv[1]);unsigned rank=atoi(argv[2])*4+gpu;
  std::string dir=argv[3];CxiResources* r=nullptr;CxiMemory *sm=nullptr,*dm=nullptr;CxiChannel* channel=nullptr;
  unsigned char *src=nullptr,*dst=nullptr;CxiWindow *sw=nullptr,*dw=nullptr;CxiGpuContext* dc=nullptr;Result* result=nullptr;
  CxiGpuContext final{};bool copied=false;int rc=1;
  try {
    CK(cudaSetDevice(gpu));r=cxi_resources_open(gpu,gpu);
    CK(cudaMalloc(&src,alloc_bytes));CK(cudaMalloc(&dst,alloc_bytes));
    CK(cudaMemset(src,0,alloc_bytes));CK(cudaMemset(dst,0,alloc_bytes));CK(cudaDeviceSynchronize());
    sm=cxi_memory_register(r,src,alloc_bytes,true);dm=cxi_memory_register(r,dst,alloc_bytes,true);
    CxiWindow hs{},hd{};cxi_memory_local(sm,&hs);cxi_memory_local(dm,&hd);hs.peers=hd.peers=8;
    hd.peer[rank]=cxi_memory_peer(dm);hd.peer[rank<4?rank+4:rank-4]=exchange(dir,rank,hd.peer[rank],"destination");
    CK(cudaMalloc(&sw,sizeof(hs)));CK(cudaMalloc(&dw,sizeof(hd)));
    CK(cudaMemcpy(sw,&hs,sizeof(hs),cudaMemcpyHostToDevice));CK(cudaMemcpy(dw,&hd,sizeof(hd),cudaMemcpyHostToDevice));
    channel=cxi_channel_open(r,64);auto descriptor=cxi_channel_descriptor(channel);
    CK(cudaMalloc(&dc,sizeof(descriptor)));CK(cudaMemcpy(dc,&descriptor,sizeof(descriptor),cudaMemcpyHostToDevice));
    CK(cudaMallocManaged(&result,sizeof(Result)));*result={};
    dynamic_test<<<1,1>>>(dc,sw,dw,src,dst,rank,result);CK(cudaGetLastError());CK(cudaDeviceSynchronize());
    CK(cudaMemcpy(&final,dc,sizeof(final),cudaMemcpyDeviceToHost));copied=true;
    uint64_t diagnostic[3]{};CK(cudaMemcpy(diagnostic,final.diagnostic,sizeof(diagnostic),cudaMemcpyDeviceToHost));
    printf("{\"rank\":%u,\"stage\":\"dynamic_result\",\"cases\":%u,\"errors\":%u,\"posted\":%llu,\"completed\":%llu,\"diagnostic\":%llu,\"bad_offset\":%llu,\"observed\":%llu,\"expected\":%llu}\n",rank,result->cases,result->errors,(unsigned long long)final.posted,(unsigned long long)final.completed,(unsigned long long)diagnostic[0],(unsigned long long)result->bad_offset,(unsigned long long)result->observed,(unsigned long long)result->expected);
    if(result->cases!=4 || result->errors || diagnostic[0] || final.posted!=final.completed)throw std::runtime_error("dynamic kernel failed");
    exchange(dir,rank,hd.peer[rank],"finished");rc=0;
  } catch(const std::exception& e){fprintf(stderr,"rank %u: %s\n",rank,e.what());}
  if(r && cxi_resources_errors(r))rc=1;
  if(channel && cxi_channel_close(channel,copied?&final:nullptr))rc=1;
  if(dm && cxi_memory_close(dm))rc=1;if(sm && cxi_memory_close(sm))rc=1;
  for(void* p:{(void*)dc,(void*)sw,(void*)dw,(void*)result,(void*)src,(void*)dst})if(p && cudaFree(p))rc=1;
  if(r && cxi_resources_close(r))rc=1;
  printf("{\"rank\":%u,\"stage\":\"process_result\",\"rc\":%d,\"is_nccl_gin\":false}\n",rank,rc);return rc;
}
