"""Reuse unchanged IDC CSTATE, retaining current credit/completion semantics."""
from pathlib import Path
from package import replace


def prepare(snapshot):
    root = Path(snapshot) / 'backend'
    abi = root / 'include/cxi_gin_abi.h'
    replace(abi, '#define CXI_GIN_ABI_VERSION 3', '#define CXI_GIN_ABI_VERSION 5')
    replace(abi, '  uint32_t tx_unpublished; // descriptors reserved/written but not yet doorbelled',
            '''  uint32_t tx_unpublished; // descriptors reserved/written but not yet doorbelled
  uint32_t idc_state_key; // valid + complete variable CSTATE fields; context lock protects''')
    replace(abi, 'static_assert(sizeof(CxiGpuContext) == 192,',
            '''static_assert(offsetof(CxiGpuContext, idc_state_key) == 140, "IDC state uses existing padding");
static_assert(sizeof(CxiGpuContext) == 192,''')
    (root / 'device/cxi_idc_state.h').write_text('''#pragma once
#include <stdint.h>
#ifdef __CUDACC__
#define CXI_STATE_HD __host__ __device__
#else
#define CXI_STATE_HD
#endif
namespace cxi_gin {
// All remaining CSTATE fields are fixed in state_locked(): zero-initialized,
// restricted/flush/send-disable/success-disable/ct-ack set. Changing those
// constants or adding a variable field requires updating this key and ABI.
// DFA and remote offset belong to each IDC command, not to CSTATE.
CXI_STATE_HD inline bool idc_state_fields_valid(uint32_t index, uint32_t lac,
                                               uint32_t ct, uint32_t eq) {
  return index < 32 && lac < 8 && ct < 2048 && eq < 2048;
}
CXI_STATE_HD inline uint32_t idc_state_key(uint32_t index, uint32_t lac,
                                         uint32_t ct, uint32_t eq) {
  return (1u << 31) | index | (lac << 5) | (ct << 8) | (eq << 19);
}
}
#undef CXI_STATE_HD
''')
    primitive = root / 'device/cxi_primitives.cuh'
    replace(primitive, '#include "cxi_fence_command.h"', '''#include "cxi_fence_command.h"
#include "cxi_idc_state.h"
#ifndef CXI_CACHE_IDC_STATE
#define CXI_CACHE_IDC_STATE 0
#endif''')
    replace(primitive, '''  uint64_t words[8]{};auto* st=(c_cstate_cmd*)words;''', '''  const uint32_t index=dst->peer[peer].index_ext, lac=dst->local_lac;
  if(!idc_state_fields_valid(index,lac,c.ct_id,c.eq_id))return fail(c,48,index,lac);
  const uint32_t key=idc_state_key(index,lac,c.ct_id,c.eq_id);
  if(CXI_CACHE_IDC_STATE && c.idc_state_key==key)return true;
  uint64_t words[8]{};auto* st=(c_cstate_cmd*)words;''')
    replace(primitive, '  st->write_lac=dst->local_lac;return emit(c,words,false,abort);', '''  st->write_lac=dst->local_lac;
  if(!emit(c,words,false,abort))return false;
  // Queue order programs this state before subsequent IDC commands. No other
  // writer may touch this CQ outside the context lock. Healthy queue recycling
  // preserves the key and hardware state; fresh descriptor{} starts invalid.
  c.idc_state_key=key;
  return true;''')
    install = Path(snapshot) / 'runner/install.py'
    replace(install, "'cxi_fence_command.h']", "'cxi_fence_command.h','cxi_idc_state.h']")
