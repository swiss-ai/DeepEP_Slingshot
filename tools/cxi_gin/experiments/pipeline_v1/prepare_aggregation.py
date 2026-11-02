"""Bounded GIN AggregateRequests publication; retain per-descriptor system fences.

Apply only to a new private snapshot. ABI version 2 uses one previously padded
field; installed host/plugin/device headers must all come from that snapshot.
"""
from pathlib import Path
from package import replace


def prepare(snapshot):
    root = Path(snapshot) / 'backend'
    abi = root / 'include/cxi_gin_abi.h'
    replace(abi, '#define CXI_GIN_ABI_VERSION 1', '#define CXI_GIN_ABI_VERSION 2')
    replace(abi, '  uint64_t* diagnostic;  // mapped host memory; GPU writes, host only observes',
            '''  uint64_t* diagnostic;  // mapped host memory; GPU writes, host only observes
  uint32_t tx_unpublished; // descriptors reserved/written but not yet doorbelled
  uint64_t tx_doorbells, tx_commands; // cumulative diagnostics, updated under lock
  // Remains inside the previous trailing padding; sizeof stays 192 bytes.''')
    p = root / 'device/cxi_primitives.cuh'
    replace(p, '\nnamespace cxi_gin {', '''
#ifndef CXI_TX_BATCH_LIMIT
#define CXI_TX_BATCH_LIMIT 1
#endif
static_assert(CXI_TX_BATCH_LIMIT >= 1 && CXI_TX_BATCH_LIMIT <= 64, "bounded TX publication");

namespace cxi_gin {''')
    replace(p, '// Caller owns the context lock. Wait for capacity, not for every command to be',
            '''// Caller owns the context lock. Each producer has already system-fenced its
// descriptor writes before releasing the lock. Preserve that guarantee even when
// another producer becomes the publisher; this variant only amortizes doorbells.
__device__ __forceinline__ void publish_locked(CxiGpuContext& c) {
  if(!c.tx_unpublished)return;
  __threadfence_system();
  store64(c.tx_doorbell,c.tx_wp32/2);
  c.tx_doorbells++;
  c.tx_unpublished=0;
}

// Caller owns the context lock. Wait for capacity, not for every command to be''')
    replace(p, '// One doorbell per command is retained for this first asynchronous variant.',
            '// AggregateRequests may defer a bounded number of doorbells. Flush/signals force publication.')
    replace(p, '                                   uint32_t* abort=nullptr,uint64_t timeout=default_timeout) {',
            '                                   uint32_t* abort=nullptr,uint64_t timeout=default_timeout,bool aggregate=false) {')
    replace(p, '    if(expired(start,timeout,abort))return fail(c,4,status,c.tx_wp32);',
            '''    // Never wait for NIC credits while unsubmitted descriptors occupy the ring.
    publish_locked(c);
    if(expired(start,timeout,abort))return fail(c,4,status,c.tx_wp32);''')
    replace(p, '''  store64(c.tx_doorbell,next/2);c.tx_wp32=next;
  if(transfer)c.posted++;return true;''', '''  c.tx_wp32=next;c.tx_unpublished++;c.tx_commands++;
  if(transfer)c.posted++;
  if(!aggregate || c.tx_unpublished>=CXI_TX_BATCH_LIMIT)publish_locked(c);
  return true;''')
    replace(p, '  if(c.completed==c.posted)return true;',
            '  publish_locked(c);\n  if(c.completed==c.posted)return true;')
    replace(p, '    const CxiWindow* src,uint64_t srcoff,uint64_t bytes,int peer,uint32_t* abort=nullptr) {',
            '    const CxiWindow* src,uint64_t srcoff,uint64_t bytes,int peer,uint32_t* abort=nullptr,bool aggregate=false) {')
    replace(p, '    if(!emit(c,words,true,abort))return false;',
            '    if(!emit(c,words,true,abort,default_timeout,aggregate))return false;')
    replace(p, '''    dstoff+=n;srcoff+=n;bytes-=n;
  }
  return true;''', '''    dstoff+=n;srcoff+=n;bytes-=n;
  }
  if(!aggregate)publish_locked(c); // includes zero-byte nonaggregated operations
  return true;''')
    gin = root / 'device/gin_cxi.cuh'
    replace(gin, '      bool hasCounter,ncclGinCounter_t counter,bool,ncclGinDescriptorSmem*,cuda::thread_scope,cuda::thread_scope,uint32_t) {',
            '      bool hasCounter,ncclGinCounter_t counter,bool,ncclGinDescriptorSmem*,cuda::thread_scope,cuda::thread_scope,uint32_t optFlags) {')
    replace(gin, 'cxi_gin::put_locked(c,(CxiWindow*)dst,dstoff,(CxiWindow*)src,srcoff,bytes,peer);',
            'cxi_gin::put_locked(c,(CxiWindow*)dst,dstoff,(CxiWindow*)src,srcoff,bytes,peer,nullptr,\n          bool(optFlags & ncclGinOptFlagsAggregateRequests));')
    # Recycle only fully published, quiescent contexts; preserves monotonic state.
    host = root / 'host/cxi_resources.cc'
    replace(host, '     state->posted!=state->completed || cxi_channel_error(q))',
            '     state->tx_unpublished || state->posted!=state->completed || cxi_channel_error(q))')
    plugin = root / 'host/gin_plugin.cc'
    replace(plugin, '  for(size_t i=0;i<x->channels.size();i++)TD(cxi_channel_recycle', '''  if(x->device && getenv("CXI_QUEUE_INVENTORY")) {
    uint64_t commands=0,doorbells=0,pending=0;
    for(const auto& c:x->host){commands+=c.tx_commands;doorbells+=c.tx_doorbells;pending+=c.tx_unpublished;}
    fprintf(stderr,"CXI_TX_PUBLICATION rank=%d cumulative_commands=%llu cumulative_doorbells=%llu unpublished=%llu\\n",
      x->coll->rank,(unsigned long long)commands,(unsigned long long)doorbells,(unsigned long long)pending);
  }
  for(size_t i=0;i<x->channels.size();i++)TD(cxi_channel_recycle''')
    # Existing source-reuse/wrap probe now exercises the deferred path explicitly.
    burst = Path(snapshot) / 'runner/burst_probe.cu'
    replace(burst, 'ok=cxi_gin::put_locked(c,dstw,i*8,srcw,i*8,8,peer);',
            'ok=cxi_gin::put_locked(c,dstw,i*8,srcw,i*8,8,peer,nullptr,true);')
