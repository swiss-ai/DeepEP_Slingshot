#pragma once
#include <stdint.h>
#include "cassini_user_defs.h"
#ifdef __CUDACC__
#define CXI_FENCE_INLINE __host__ __device__ __forceinline__
#else
#define CXI_FENCE_INLINE inline
#endif
// Identical 64-byte command format to installed cxi_cq_emit_cq_cmd(CQ_FENCE).
CXI_FENCE_INLINE void cxi_build_fence_command(uint64_t* words) {
  for(unsigned i=0;i<8;i++)words[i]=0;
  auto* command=reinterpret_cast<c_cq_cmd*>(words);
  command->command.cmd_type=C_CMD_TYPE_CQ;
  command->command.cmd_size=C_CMD_SIZE_64B;
  command->command.opcode=C_CMD_CQ_FENCE;
}
#undef CXI_FENCE_INLINE
