"""Conservative TX read-pointer caching, following installed libcxi policy.

This changes submission bookkeeping, not completion or delivery semantics.
Every access is under the existing context lock. A stale read pointer can only
underestimate free slots; refresh before it can stop forward progress. Explicit
flush checks fresh queue status even when no completion is pending.
"""
from pathlib import Path
from package import replace


def prepare(snapshot):
    root = Path(snapshot) / 'backend'
    abi = root / 'include/cxi_gin_abi.h'
    replace(abi, '#define CXI_GIN_ABI_VERSION 3', '#define CXI_GIN_ABI_VERSION 4')
    replace(abi, '  uint32_t tx_unpublished; // descriptors reserved/written but not yet doorbelled',
            '''  uint32_t tx_unpublished; // descriptors reserved/written but not yet doorbelled
  uint32_t tx_cached_rp32; // conservative NIC consumer cursor, protected by lock''')
    replace(abi, 'static_assert(sizeof(CxiGpuContext) == 192,',
            '''static_assert(offsetof(CxiGpuContext, tx_cached_rp32) == 140, "cached cursor uses existing padding");
static_assert(sizeof(CxiGpuContext) == 192,''')
    host = root / 'host/cxi_resources.cc'
    replace(host, '    d.ct_id=q->ct->ctn;d.eq_id=r->eq->eqn;',
            '''    d.tx_cached_rp32=q->tx->rp32;
    d.ct_id=q->ct->ctn;d.eq_id=r->eq->eqn;''')
    credit = root / 'device/cxi_queue_credit.h'
    replace(credit, '\n}\n#undef CXI_CREDIT_HD', '''
// Same low-water mark as installed libcxi __cxi_cq_free_slots(). A pending
// diagnostic limit also refreshes the cursor before declaring backpressure.
CXI_CREDIT_HD inline bool cq_refresh_required(uint32_t size32, uint32_t wp32,
                                             uint32_t rp32, uint32_t pending_limit) {
  return cq_free_slots32(size32, wp32, rp32) < 16 ||
         (pending_limit && cq_pending_commands(size32, wp32, rp32) >= pending_limit);
}
}
#undef CXI_CREDIT_HD''')
    primitive = root / 'device/cxi_primitives.cuh'
    replace(primitive, '\nnamespace cxi_gin {', '''
#ifndef CXI_CACHE_TX_CREDITS
#define CXI_CACHE_TX_CREDITS 0
#endif

namespace cxi_gin {''')
    replace(primitive, '// Caller owns the context lock. Each producer has already system-fenced its',
            '''// Fresh status checks also run at explicit completion boundaries, so cached
// credits cannot hide an error indefinitely on a lightly used queue.
__device__ __forceinline__ bool refresh_tx_status_locked(CxiGpuContext& c) {
  uint32_t status=load32((uint32_t*)c.tx_queue);
  if(status>>16)return fail(c,3,status);
  uint32_t rp32=(status&65535)*2;
  if(!cq_positions_valid(c.tx_size32,c.tx_wp32,rp32))return fail(c,46,status,c.tx_wp32);
  c.tx_cached_rp32=rp32;
  return true;
}

// Caller owns the context lock. Each producer has already system-fenced its''')
    replace(primitive, '''    uint32_t status=load32((uint32_t*)c.tx_queue);
    if(status>>16)return fail(c,3,status);
    uint32_t rp32=(status&65535)*2;
    if(!cq_positions_valid(c.tx_size32,c.tx_wp32,rp32))return fail(c,46,status,c.tx_wp32);''',
            '''    if(!cq_positions_valid(c.tx_size32,c.tx_wp32,c.tx_cached_rp32))
      return fail(c,46,c.tx_cached_rp32,c.tx_wp32);
    if(!CXI_CACHE_TX_CREDITS || cq_refresh_required(c.tx_size32,c.tx_wp32,c.tx_cached_rp32,CXI_TX_PENDING_LIMIT))
      if(!refresh_tx_status_locked(c))return false;
    uint32_t rp32=c.tx_cached_rp32;''')
    replace(primitive, 'return fail(c,4,status,c.tx_wp32);', 'return fail(c,4,rp32,c.tx_wp32);')
    replace(primitive, '  if(c.completed==c.posted)return true;',
            '  if(!refresh_tx_status_locked(c))return false;\n  if(c.completed==c.posted)return true;')
    replace(primitive, '  __threadfence_system();return true;\n}\n__device__ __forceinline__ bool region(',
            '  __threadfence_system();return refresh_tx_status_locked(c);\n}\n__device__ __forceinline__ bool region(')
