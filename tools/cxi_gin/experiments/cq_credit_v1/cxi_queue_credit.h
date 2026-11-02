#pragma once
#include <stdint.h>

#if defined(__CUDACC__)
#define CXI_CREDIT_HD __host__ __device__
#else
#define CXI_CREDIT_HD
#endif

namespace cxi_gin {
// Cassini stores status in the first four 64-byte entries. Retain one further
// empty entry so wrapped producer/consumer pointers cannot alias a full queue.
// Match the installed libcxi 1.7.0 __cxi_cq_free_slots_check contract, in
// 32-byte units. A zero status read pointer before its first writeback reserves
// extra space conservatively; it does not grant additional credits.
CXI_CREDIT_HD inline int cq_free_slots32(uint32_t size32, uint32_t wp32, uint32_t rp32) {
  if (size32 < 12 || (size32 & 1) || wp32 < 8 || wp32 >= size32 || (wp32 & 1) ||
      rp32 >= size32 || (rp32 & 1) || (rp32 != 0 && rp32 < 8)) return -1;
  return wp32 >= rp32 ? int(size32 - wp32) + int(rp32) - 10 : int(rp32 - wp32) - 2;
}
}

#undef CXI_CREDIT_HD
