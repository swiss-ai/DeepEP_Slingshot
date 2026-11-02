#include <cuda_runtime.h>
#include <stdint.h>
__global__ void stamp_kernel(uint64_t* p) {
  uint64_t t;asm volatile("mov.u64 %0, %%globaltimer;":"=l"(t));*p=t;
}
extern "C" int trace_stamp(uint64_t* p,void* stream) {
  stamp_kernel<<<1,1,0,(cudaStream_t)stream>>>(p);
  return int(cudaGetLastError());
}
