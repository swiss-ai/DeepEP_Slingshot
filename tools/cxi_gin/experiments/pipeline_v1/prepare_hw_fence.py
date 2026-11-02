"""Queue a native CQ fence before strong signals instead of polling on the GPU.

Experimental: libfabric's CXI provider uses this command before FI_FENCE AMOs.
Payload delivery completion is retained (per PUT or via the existing DC marker).
Explicit flush/counter completion remains a closed, lock-held CT observation.
"""
from pathlib import Path
from package import replace


def prepare(snapshot):
    root = Path(snapshot)
    device = root / 'backend/device'
    (device / 'cxi_fence_command.h').write_text('''#pragma once
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
''')
    primitive = device / 'cxi_primitives.cuh'
    replace(primitive, '#include "cxi_queue_credit.h"', '''#include "cxi_queue_credit.h"
#include "cxi_fence_command.h"
#ifndef CXI_HW_SIGNAL_FENCE
#define CXI_HW_SIGNAL_FENCE 0
#endif''')
    replace(primitive, '__device__ __forceinline__ bool add_locked(', '''// Keep payload visibility before notification, but let the NIC enforce the
// dependency. No GPU CT writeback wait here; explicit flush/counters still wait.
// CQ_FENCE is not a transfer and does not increment the completion target.
__device__ __forceinline__ bool signal_fence_locked(CxiGpuContext& c,uint32_t* abort=nullptr) {
#if CXI_BATCH_DELIVERY
  if(!delivery_flush_locked(c,abort,default_timeout))return false;
#endif
  uint64_t words[8];cxi_build_fence_command(words);
  return emit(c,words,false,abort,default_timeout,true);
}
__device__ __forceinline__ bool add_locked(''')
    replace(primitive, '  if(!flush_locked(c,abort) || !state_locked(c,dst,peer,abort))return false;', '''#if CXI_HW_SIGNAL_FENCE
  if(!signal_fence_locked(c,abort) || !state_locked(c,dst,peer,abort))return false;
#else
  if(!flush_locked(c,abort) || !state_locked(c,dst,peer,abort))return false;
#endif''')
    installer = root / 'runner/install.py'
    replace(installer, "['cxi_primitives.cuh','cxi_queue_credit.h','gin_cxi.cuh']",
            "['cxi_primitives.cuh','cxi_queue_credit.h','gin_cxi.cuh','cxi_fence_command.h']")
    (root / 'runner/test_fence_descriptor.cc').write_text('''#include <cstring>
#include <libcxi/libcxi.h>
#include "cxi_fence_command.h"
#include <cstdio>
int main() {
  cxi_cmd32 storage[128]{};cxi_cq queue{};
  queue.cmds32=storage;queue.wp32=queue.hw_wp32=queue.rp32=8;queue.size32=128;
  if(cxi_cq_emit_cq_cmd(&queue,C_CMD_CQ_FENCE))return 1;
  uint64_t expected[8];cxi_build_fence_command(expected);
  if(queue.wp32!=10 || memcmp(expected,&storage[8],64))return 2;
  puts("PASS GPU CQ_FENCE descriptor builder matches installed libcxi helper; no NIC semantics tested");
}
''')
