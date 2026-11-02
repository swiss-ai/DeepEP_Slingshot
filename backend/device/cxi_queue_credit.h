#pragma once
#include <stdint.h>

#if defined(__CUDACC__)
#define CXI_CREDIT_HD __host__ __device__
#else
#define CXI_CREDIT_HD
#endif

namespace cxi_gin {
// Diagnostic pacing limit, in padded 64-byte commands. This is NOT an RDMA
// outstanding-operation limit: NIC consumption does not imply completion.
CXI_CREDIT_HD inline uint32_t cq_pending_commands(uint32_t size32, uint32_t wp32, uint32_t rp32) {
  // Before the first hardware update, zero means the initial empty position.
  if (rp32 == 0) rp32 = 8;
  return (wp32 >= rp32 ? wp32 - rp32 : size32 - rp32 + wp32 - 8) / 2;
}
// This backend emits padded 64-byte commands (two 32-byte units). The first
// eight units hold status; leave one additional command empty to distinguish
// full from empty. Match installed libcxi __cxi_cq_free_slots_check.
CXI_CREDIT_HD inline bool cq_positions_valid(uint32_t size32, uint32_t wp32, uint32_t rp32) {
  return size32 >= 12 && !(size32 & 1) && wp32 >= 8 && wp32 < size32 &&
         !(wp32 & 1) && rp32 < size32 && !(rp32 & 1) && (rp32 == 0 || rp32 >= 8);
}
CXI_CREDIT_HD inline int cq_free_slots32(uint32_t size32, uint32_t wp32, uint32_t rp32) {
  if (!cq_positions_valid(size32, wp32, rp32)) return -1;
  // An initial zero read pointer can give a negative conservative credit count.
  return wp32 >= rp32 ? int(size32 - wp32) + int(rp32) - 10 : int(rp32 - wp32) - 2;
}
}
#undef CXI_CREDIT_HD
