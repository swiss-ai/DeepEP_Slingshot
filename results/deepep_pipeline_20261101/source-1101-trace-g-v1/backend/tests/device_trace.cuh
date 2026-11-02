#ifndef EP_DEVICE_TRACE_V1_HEADER
#define EP_DEVICE_TRACE_V1_HEADER
#include <cuda_runtime.h>
#include <stdint.h>
#ifndef EP_TRACE_PTR
#define EP_TRACE_PTR 0ULL
#endif
namespace ep_trace {
constexpr unsigned slots=8192, capacity=4096, header_words=8+slots, words=8;
__device__ __forceinline__ uint64_t now(){uint64_t t;asm volatile("mov.u64 %0, %%globaltimer;":"=l"(t));return t;}
__device__ __forceinline__ uint64_t begin(bool select=true){return select && EP_TRACE_PTR && *reinterpret_cast<volatile uint64_t*>(EP_TRACE_PTR) ? now():0;}
__device__ __forceinline__ void finish(unsigned event,uint64_t start,uint64_t a=0,uint64_t b=0){
  if(!start)return;const auto end=now();
  auto* base=reinterpret_cast<unsigned long long*>(EP_TRACE_PTR);
  const unsigned slot=blockIdx.x*32+threadIdx.x/32;
  if(slot>=slots){atomicAdd(base+1,1ULL);return;}
  const auto i=atomicAdd(base+8+slot,1ULL);
  if(i>=capacity){atomicAdd(base+1,1ULL);return;}
  auto* p=base+header_words+(slot*capacity+i)*words;
  unsigned sm;asm volatile("mov.u32 %0, %%smid;":"=r"(sm));
  p[0]=start;p[1]=end;p[2]=event;p[3]=blockIdx.x;p[4]=threadIdx.x;p[5]=a;p[6]=b;p[7]=sm;
}
struct Scope {
  unsigned event;uint64_t start,a,b;
  __device__ __forceinline__ Scope(unsigned e,uint64_t x=0,uint64_t y=0,bool select=true):event(e),start(begin(select)),a(x),b(y){}
  __device__ __forceinline__ ~Scope(){finish(event,start,a,b);}
};
}
#endif
