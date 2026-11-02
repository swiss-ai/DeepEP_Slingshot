#!/usr/bin/env python3
"""Cached TX-queue credits for the direct-CXI GIN backend (2026-11-02 evening).

Finding (job 3837687 traces, 4K dispatch): every channel's first PUT spends ~100 us in the transport,
half of the channels waiting for the context lock and the other half inside emit's credit check, i.e.
the NIC-written status read that `emit` performs for every command; 128 contexts read it at the same
instant after the entry barrier. The 12-row PUTs later in the kernel cost 25 us. The NIC drains the
submitted bytes at the 22.5 GB/s ceiling, so the late first emission (0.22-0.25 ms instead of 0.11-0.13)
is the dispatch's wire-phase loss.

Change (CXI_CREDIT_CACHE, selected per runtime variant): keep the last NIC read pointer in the context
(`tx_rp32_cache`) and read the status only when the cached, conservative free-slot count is below
2 + 2*CXI_CREDIT_MARGIN 32-byte units. The read pointer only advances, so a stale value under-counts
free slots and never over-counts them (the CPU ring model in runner/test_queue_credit.cc exercises
delayed consumption, delayed status write-back and wrapping). ABI version 4, context 256 bytes
(`tx_rp32_cache`, `tx_status_reads`, reserved); host sets the cache to CXI_RP32_UNKNOWN at open and
recycle, and the queue inventory reports the cumulative status reads. The earlier cached-credit
candidate of 10/30 (gate 521) stalled at 16K on the delivery-v3 base without attribution; the
sustained-16K gate is therefore part of the ladder again.

Variants added: `cache-a` = marker-zero + cache, `lean-c` = lean-b + cache.
"""
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'pipeline_v1'))
from package import replace  # noqa: E402

def prepare(snapshot):
    out = Path(snapshot)
    abi = out / 'backend/include/cxi_gin_abi.h'
    replace(abi, '#define CXI_GIN_ABI_VERSION 3\n', '#define CXI_GIN_ABI_VERSION 4\n#define CXI_RP32_UNKNOWN 0xffffffffu\n')
    replace(abi, '''  uint32_t pending_lac, pending_peer;
  // pending_* and lean_state live inside the previous trailing padding; sizeof stays 192 bytes.
};''', '''  uint32_t pending_lac, pending_peer;
  // ABI 4: cached NIC read pointer of the TX ring (32-byte units) and the count of fresh status
  // reads. The read pointer only advances, so a stale value under-counts free slots and never
  // over-counts them; CXI_RP32_UNKNOWN forces a fresh read. Host sets it at open and recycle.
  uint32_t tx_rp32_cache, tx_status_reads;
  uint64_t reserved_abi4[7];
};''')
    replace(abi, 'static_assert(sizeof(CxiGpuContext) == 192, "context host/device ABI size");',
                 'static_assert(sizeof(CxiGpuContext) == 256, "context host/device ABI size");')
    res = out / 'backend/host/cxi_resources.cc'
    replace(res, '    auto& d=q->descriptor;d.abi_version=CXI_GIN_ABI_VERSION;d.lean_state=1; // fence due, no cached CSTATE\n',
                 '    auto& d=q->descriptor;d.abi_version=CXI_GIN_ABI_VERSION;d.lean_state=1; // fence due, no cached CSTATE\n'
                 '    d.tx_rp32_cache=CXI_RP32_UNKNOWN;d.tx_status_reads=0;\n')
    replace(res, '  q->descriptor.pending_lac=0;q->descriptor.pending_peer=0;q->descriptor.lean_state=1;\n',
                 '  q->descriptor.pending_lac=0;q->descriptor.pending_peer=0;q->descriptor.lean_state=1;\n'
                 '  q->descriptor.tx_rp32_cache=CXI_RP32_UNKNOWN;q->descriptor.tx_status_reads=0;\n')
    plugin = out / 'backend/host/gin_plugin.cc'
    replace(plugin, '''    uint64_t commands=0,doorbells=0,pending=0;
    for(const auto& c:x->host){commands+=c.tx_commands;doorbells+=c.tx_doorbells;pending+=c.tx_unpublished;}
    fprintf(stderr,"CXI_TX_PUBLICATION rank=%d cumulative_commands=%llu cumulative_doorbells=%llu unpublished=%llu\\n",
      x->coll->rank,(unsigned long long)commands,(unsigned long long)doorbells,(unsigned long long)pending);''',
'''    uint64_t commands=0,doorbells=0,pending=0,reads=0;
    for(const auto& c:x->host){commands+=c.tx_commands;doorbells+=c.tx_doorbells;pending+=c.tx_unpublished;reads+=c.tx_status_reads;}
    fprintf(stderr,"CXI_TX_PUBLICATION rank=%d cumulative_commands=%llu cumulative_doorbells=%llu unpublished=%llu status_reads=%llu\\n",
      x->coll->rank,(unsigned long long)commands,(unsigned long long)doorbells,(unsigned long long)pending,(unsigned long long)reads);''')
    prim = out / 'backend/device/cxi_primitives.cuh'
    replace(prim, 'static_assert(!CXI_LEAN_FOLD_MARKER || CXI_BATCH_DELIVERY, "the marker fold replaces the batched-delivery marker");\n',
'''static_assert(!CXI_LEAN_FOLD_MARKER || CXI_BATCH_DELIVERY, "the marker fold replaces the batched-delivery marker");
#ifndef CXI_CREDIT_CACHE
#define CXI_CREDIT_CACHE 0
#endif
#ifndef CXI_CREDIT_MARGIN
#define CXI_CREDIT_MARGIN 8 // spare commands kept beyond the cached count before a fresh status read
#endif
''')
    old_loop = '''  while(true) {
    uint32_t status=load32((uint32_t*)c.tx_queue);
    if(status>>16)return fail(c,3,status);
    uint32_t rp32=(status&65535)*2;
    if(!cq_positions_valid(c.tx_size32,c.tx_wp32,rp32))return fail(c,46,status,c.tx_wp32);
    if(cq_free_slots32(c.tx_size32,c.tx_wp32,rp32)>=2 &&
       (!CXI_TX_PENDING_LIMIT || cq_pending_commands(c.tx_size32,c.tx_wp32,rp32)<CXI_TX_PENDING_LIMIT))break;
    // Never wait for NIC credits while unsubmitted descriptors occupy the ring.
    publish_locked(c);
    if(expired(start,timeout,abort))return fail(c,4,status,c.tx_wp32);
    __nanosleep(64);
  }
'''
    new_loop = '''#if CXI_CREDIT_CACHE
  // The NIC's read pointer only advances, so the cached value under-counts free slots and never
  // over-counts them: emitting against it cannot overwrite an unconsumed command. Read the
  // NIC-written status only when the cached count is short of CXI_CREDIT_MARGIN spare commands.
  {
    uint32_t rp32=c.tx_rp32_cache;bool cached=rp32!=CXI_RP32_UNKNOWN;uint32_t status=0;
    while(true) {
      if(cached && cq_positions_valid(c.tx_size32,c.tx_wp32,rp32) &&
         cq_free_slots32(c.tx_size32,c.tx_wp32,rp32)>=2+2*CXI_CREDIT_MARGIN &&
         (!CXI_TX_PENDING_LIMIT || cq_pending_commands(c.tx_size32,c.tx_wp32,rp32)<CXI_TX_PENDING_LIMIT))break;
      status=load32((uint32_t*)c.tx_queue);
      if(status>>16)return fail(c,3,status);
      rp32=(status&65535)*2;
      if(!cq_positions_valid(c.tx_size32,c.tx_wp32,rp32))return fail(c,46,status,c.tx_wp32);
      c.tx_rp32_cache=rp32;c.tx_status_reads++;cached=false;
      if(cq_free_slots32(c.tx_size32,c.tx_wp32,rp32)>=2 &&
         (!CXI_TX_PENDING_LIMIT || cq_pending_commands(c.tx_size32,c.tx_wp32,rp32)<CXI_TX_PENDING_LIMIT))break;
      // Never wait for NIC credits while unsubmitted descriptors occupy the ring.
      publish_locked(c);
      if(expired(start,timeout,abort))return fail(c,4,status,c.tx_wp32);
      __nanosleep(64);
    }
  }
#else
''' + old_loop + '#endif\n'
    replace(prim, old_loop, new_loop)
    # CPU ring model: cached refresh policy against delayed consumption and delayed status write-back.
    test = out / 'runner/test_queue_credit.cc'
    replace(test, '''  std::printf("PASS states=%llu writes=%llu backpressure=%llu wraps=%llu; CPU ring model only\\n",''',
'''  // Cached read pointer (CXI_CREDIT_CACHE): the producer refreshes the NIC status only when the
  // cached, conservative credit count is below the margin; the NIC consumes and writes its read
  // pointer back with independent delays. A stale pointer must never admit a write into an
  // unconsumed slot, and the policy must keep making progress through wraps.
  // Two regimes: a slow NIC (ring mostly full, every refresh is needed) and a fast NIC (ring mostly
  // empty, the cache must remove most status reads).
  uint64_t cached_writes[2]={0,0}, cached_refreshes[2]={0,0};
  for (unsigned fast : {0u, 1u})
  for (unsigned margin : {0u, 4u, 8u, 16u})
    for (unsigned size : {32u, 128u, 2048u}) {
      const unsigned capacity=(size-8)/2;
      std::vector<uint64_t> ring(capacity,0);
      uint64_t posted=0, consumed=0, reported=0; bool cached=false; unsigned rp=0;
      std::mt19937 rng(size*31+margin+7*fast);
      for(unsigned tick=0;tick<300000;++tick) {
        if(consumed<posted && (fast || rng()%3)) {
          assert(ring[consumed%capacity]==consumed+1);
          ring[consumed++%capacity]=0;
        }
        if(rng()%4==0)reported=consumed; // NIC status write-back lags consumption
        const unsigned wp=8+2*(posted%capacity);
        bool admit=false;
        if(cached && cxi_gin::cq_positions_valid(size,wp,rp) && cxi_gin::cq_free_slots32(size,wp,rp)>=int(2+2*margin)) admit=true;
        else {
          rp=reported?8+2*(reported%capacity):0; cached=true; ++cached_refreshes[fast];
          assert(cxi_gin::cq_positions_valid(size,wp,rp));
          admit=cxi_gin::cq_free_slots32(size,wp,rp)>=2;
        }
        if(admit) {
          assert(posted-consumed<capacity-1);
          assert(ring[posted%capacity]==0);
          ring[posted%capacity]=posted+1;++posted;++cached_writes[fast];
        }
      }
      assert(posted>capacity*20);
    }
  assert(cached_refreshes[1]*4<cached_writes[1]);
  std::printf("PASS cached-credit model: slow NIC writes=%llu refreshes=%llu, fast NIC writes=%llu refreshes=%llu\\n",
              (unsigned long long)cached_writes[0],(unsigned long long)cached_refreshes[0],(unsigned long long)cached_writes[1],(unsigned long long)cached_refreshes[1]);
  std::printf("PASS states=%llu writes=%llu backpressure=%llu wraps=%llu; CPU ring model only\\n",''')
    variants = json.loads((out / 'variants.json').read_text())
    variants['cache-a'] = dict(variants['marker-zero'], CXI_CREDIT_CACHE=1)
    variants['lean-c'] = dict(variants['lean-b'], CXI_CREDIT_CACHE=1)
    (out / 'variants.json').write_text(json.dumps(variants, indent=2) + '\n')
    pf = out / 'runner/preflight.sh'
    replace(pf, 'for variant in marker-zero lean-a lean-b; do', 'for variant in marker-zero lean-a lean-b cache-a lean-c; do')
    replace(pf, '''  -I"$src/backend/include" -I"$src/backend/device" -c "$src/runner/burst_probe.cu" -o "$out/burst-lean.o"
''', '''  -I"$src/backend/include" -I"$src/backend/device" -c "$src/runner/burst_probe.cu" -o "$out/burst-lean.o"
"$sdk/bin/nvcc" -std=c++17 -arch=sm_90 -DCXI_CREDIT_CACHE=1 -DCXI_LEAN_FENCE=1 -DCXI_LEAN_CSTATE=1 -DCXI_LEAN_FOLD_MARKER=1 -DCXI_ZERO_DELIVERY_MARKER=1 -DCXI_HW_SIGNAL_FENCE=1 -DCXI_TX_BATCH_LIMIT=8 -DCXI_BATCH_DELIVERY=1 -DCXI_CT_THRESHOLD_FLUSH=1 \\
  -I"$src/backend/include" -I"$src/backend/device" -c "$src/runner/burst_probe.cu" -o "$out/burst-credit.o"
''')
    (out / 'backend/tests/ep_benchmark.py').read_text()  # unchanged: the variant is a runtime choice
    return out

if __name__ == '__main__':
    prepare(sys.argv[1]); print('prepared', sys.argv[1])
