// Raw PUT offset/length probe on the private CXI device primitives (same transport the GIN
// backend uses). Derived from runner/burst_probe.cu (setup, rail-peer exchange, locked PUTs).
//
// Question: does the NIC transfer rate depend on where packed PUT boundaries fall relative to
// the DeepEP row size? For each case, both rail peers (rank r and r^4) simultaneously issue
// kPuts PUTs of len_rows rows, PUT i covering rows [off_rows + 16 i, off_rows + 16 i + len_rows)
// of a 48 MB window (source and destination offsets identical, as in the packed dispatch), then
// flush (CT completion of every PUT) and record the globaltimer span. Cases are repeated kReps
// times; each case starts and ends with a signal handshake so the peers' traffic overlaps the
// same way for every case. One thread, one channel: the single-queue picture.
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

constexpr size_t max_bytes=48u<<20;
constexpr size_t signal_off=max_bytes+1024;
constexpr size_t alloc_bytes=max_bytes+65536;
constexpr unsigned kPuts=256, kReps=3, kMaxCases=48;
struct Case {unsigned row,len_rows,off_rows;};
struct Out {unsigned cases,errors;uint64_t ns[kMaxCases*kReps];};

__device__ uint64_t gtimer(){uint64_t t;asm volatile("mov.u64 %0, %%globaltimer;":"=l"(t));return t;}
__device__ bool wait_signal(CxiGpuContext& c,uint64_t* p,uint64_t value){
  uint64_t start=clock64();while(cxi_gin::load64(p)<value){if(clock64()-start>cxi_gin::default_timeout)return cxi_gin::fail(c,30,value,cxi_gin::load64(p));}return true;
}
__global__ void offset_test(CxiGpuContext* context,CxiWindow* srcw,CxiWindow* dstw,unsigned char* dst,unsigned rank,const Case* cases,unsigned ncases,Out* out) {
  CxiGpuContext& c=*context;int peer=rank^4;unsigned iter=0;
  uint64_t* start_sig=(uint64_t*)(dst+signal_off);uint64_t* done_sig=(uint64_t*)(dst+signal_off+8);
  for(unsigned ci=0;ci<ncases;ci++)for(unsigned rep=0;rep<kReps;rep++) {
    iter++;const Case k=cases[ci];
    const uint64_t row=k.row,len=uint64_t(k.len_rows)*row,off0=uint64_t(k.off_rows)*row,stride=16*row;
    if(off0+uint64_t(kPuts-1)*stride+len>max_bytes){out->errors++;return;}
    // Aligned start: tell the peer we are ready, wait for the peer.
    if(!cxi_gin::acquire(c))return;bool ok=cxi_gin::add_locked(c,dstw,signal_off,1,peer);cxi_gin::release(c);
    if(!ok || !wait_signal(c,start_sig,iter))return;
    const uint64_t t0=gtimer();
    for(unsigned i=0;i<kPuts;i++) {
      const uint64_t off=off0+uint64_t(i)*stride;
      if(!cxi_gin::acquire(c))return;
      ok=cxi_gin::put_locked(c,dstw,off,srcw,off,len,peer,nullptr,true);
      cxi_gin::release(c);if(!ok)return;
    }
    if(!cxi_gin::flush(c))return;
    out->ns[ci*kReps+rep]=gtimer()-t0;
    // Aligned end: the peer's traffic for this case has finished too before the next case.
    if(!cxi_gin::acquire(c))return;ok=cxi_gin::add_locked(c,dstw,signal_off+8,1,peer);cxi_gin::release(c);
    if(!ok || !wait_signal(c,done_sig,iter))return;
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
  auto peer=dir+"/"+label+"-"+std::to_string(rank<4?rank+4:rank-4);double deadline=secs()+120;
  do {CxiPeerAddress p{};std::ifstream f(peer,std::ios::binary);if(f.read((char*)&p,sizeof(p)))return p;usleep(10000);}while(secs()<deadline);
  throw std::runtime_error("peer descriptor timeout");
}
static unsigned build_cases(Case* cases) {
  unsigned n=0;
  for(unsigned row:{4320u,8256u}) {
    for(unsigned off:{0u,1u,2u,3u,4u,5u,6u,8u})cases[n++]={row,16,off};      // phase of 16-row PUT boundaries
    for(unsigned len:{15u,14u,13u,12u})cases[n++]={row,len,0};                 // length alone, boundaries at phase 0
    for(unsigned k:{1u,2u,3u,4u})cases[n++]={row,16-k,k};                      // DeepEP's final PUTs: phase k, length 16-k
  }
  return n;
}
int main(int argc,char** argv) {
  if(argc!=4)return 2;int gpu=atoi(argv[1]);unsigned rank=atoi(argv[2])*4+gpu;
  std::string dir=argv[3];CxiResources* r=nullptr;CxiMemory *sm=nullptr,*dm=nullptr;CxiChannel* channel=nullptr;
  unsigned char *src=nullptr,*dst=nullptr;CxiWindow *sw=nullptr,*dw=nullptr;CxiGpuContext* dc=nullptr;Out* result=nullptr;Case* dcases=nullptr;
  CxiGpuContext final{};bool copied=false;int rc=1;double setup_start=secs();
  Case cases[kMaxCases];const unsigned ncases=build_cases(cases);
  try {
    CK(cudaSetDevice(gpu));r=cxi_resources_open(gpu,gpu);
    CK(cudaMalloc(&src,alloc_bytes));CK(cudaMalloc(&dst,alloc_bytes));
    CK(cudaMemset(src,0x5a,alloc_bytes));CK(cudaMemset(dst,0,alloc_bytes));CK(cudaDeviceSynchronize());
    sm=cxi_memory_register(r,src,alloc_bytes,true);dm=cxi_memory_register(r,dst,alloc_bytes,true);
    CxiWindow hs{},hd{};cxi_memory_local(sm,&hs);cxi_memory_local(dm,&hd);hs.peers=hd.peers=8;
    hd.peer[rank]=cxi_memory_peer(dm);hd.peer[rank<4?rank+4:rank-4]=exchange(dir,rank,hd.peer[rank],"destination");
    CK(cudaMalloc(&sw,sizeof(hs)));CK(cudaMalloc(&dw,sizeof(hd)));
    CK(cudaMemcpy(sw,&hs,sizeof(hs),cudaMemcpyHostToDevice));CK(cudaMemcpy(dw,&hd,sizeof(hd),cudaMemcpyHostToDevice));
    channel=cxi_channel_open(r,64);auto descriptor=cxi_channel_descriptor(channel);
    CK(cudaMalloc(&dc,sizeof(descriptor)));CK(cudaMemcpy(dc,&descriptor,sizeof(descriptor),cudaMemcpyHostToDevice));
    CK(cudaMalloc(&dcases,sizeof(cases)));CK(cudaMemcpy(dcases,cases,sizeof(cases),cudaMemcpyHostToDevice));
    CK(cudaMallocManaged(&result,sizeof(Out)));*result={};
    cudaFuncAttributes attributes{};
    CK(cudaFuncGetAttributes(&attributes,offset_test));
    CK(cudaDeviceSynchronize());
    fprintf(stderr,"RAW_SETUP rank=%u phase=kernel_ready elapsed_s=%.6f\n",rank,secs()-setup_start);
    exchange(dir,rank,hd.peer[rank],"kernel-ready");
    fprintf(stderr,"RAW_SETUP rank=%u phase=peer_ready elapsed_s=%.6f\n",rank,secs()-setup_start);
    offset_test<<<1,1>>>(dc,sw,dw,dst,rank,dcases,ncases,result);CK(cudaGetLastError());CK(cudaDeviceSynchronize());
    CK(cudaMemcpy(&final,dc,sizeof(final),cudaMemcpyDeviceToHost));copied=true;
    uint64_t diagnostic[3]{};CK(cudaMemcpy(diagnostic,final.diagnostic,sizeof(diagnostic),cudaMemcpyDeviceToHost));
    for(unsigned ci=0;ci<ncases;ci++)for(unsigned rep=0;rep<kReps;rep++) {
      const Case k=cases[ci];const uint64_t bytes=uint64_t(kPuts)*k.len_rows*k.row;const uint64_t ns=result->ns[ci*kReps+rep];
      printf("{\"rank\":%u,\"stage\":\"offset_case\",\"row\":%u,\"len_rows\":%u,\"off_rows\":%u,\"phase\":%u,\"rep\":%u,\"puts\":%u,\"bytes\":%llu,\"ns\":%llu,\"gbps\":%.3f}\n",
             rank,k.row,k.len_rows,k.off_rows,k.off_rows%4,rep,kPuts,(unsigned long long)bytes,(unsigned long long)ns,ns?double(bytes)/double(ns):0.0);
    }
    printf("{\"rank\":%u,\"stage\":\"offset_result\",\"cases\":%u,\"expected\":%u,\"errors\":%u,\"posted\":%llu,\"completed\":%llu,\"diagnostic\":%llu,\"diag1\":%llu,\"diag2\":%llu}\n",
           rank,result->cases,ncases*kReps,result->errors,(unsigned long long)final.posted,(unsigned long long)final.completed,(unsigned long long)diagnostic[0],(unsigned long long)diagnostic[1],(unsigned long long)diagnostic[2]);
    if(result->cases!=ncases*kReps || result->errors || diagnostic[0] || final.posted!=final.completed)throw std::runtime_error("offset kernel failed");
    exchange(dir,rank,hd.peer[rank],"finished");rc=0;
  } catch(const std::exception& e){fprintf(stderr,"rank %u: %s\n",rank,e.what());}
  if(r && cxi_resources_errors(r))rc=1;
  if(channel && cxi_channel_close(channel,copied?&final:nullptr))rc=1;
  if(dm && cxi_memory_close(dm))rc=1;if(sm && cxi_memory_close(sm))rc=1;
  for(void* p:{(void*)dc,(void*)sw,(void*)dw,(void*)result,(void*)dcases,(void*)src,(void*)dst})if(p && cudaFree(p))rc=1;
  if(r && cxi_resources_close(r))rc=1;
  printf("{\"rank\":%u,\"stage\":\"process_result\",\"rc\":%d,\"is_nccl_gin\":false}\n",rank,rc);return rc;
}
