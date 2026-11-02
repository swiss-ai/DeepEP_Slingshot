"""Lean signal path for the direct-CXI GIN backend plus two kernel-side changes, all knob-guarded.

Transport (device header, selected per runtime variant through variants.json):
  CXI_LEAN_FENCE       emit the CQ fence before a signal only when a fenced-before-signal transfer
                       (payload PUT, delivery marker, inline value PUT) was posted since the last
                       fence or completed flush.
  CXI_LEAN_CSTATE      emit CSTATE only when its (index_ext, write_lac) pair changes on the context.
  CXI_LEAN_FOLD_MARKER close a delivery epoch by rewriting the still-unpublished pending payload PUT
                       (flush bit, CT_ACK) instead of appending a zero-byte marker command.
The bookkeeping lives in a new 32-bit field CxiGpuContext::lean_state inside the former trailing
padding (sizeof stays 192); the host initialises it to 'fence due' at channel open and recycle.

Kernels (DeepEP archive, selected per gate through the nvcc wrapper environment):
  CXI_EP_SKIP_COMBINE_FLUSH  drop the forward warp's gin.flush before the combine end signal.
  CXI_EP_LOCAL_SELF_SIGNAL   the GIN barrier neither signals nor waits on its own rank through the NIC.
"""
import json, tarfile, tempfile, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'pipeline_v1'))
from package import replace  # noqa: E402

def prepare(snapshot):
    out = Path(snapshot)
    # ---------------------------------------------------------------- DeepEP archive
    with tempfile.TemporaryDirectory() as tmp:
        ep = Path(tmp)
        with tarfile.open(out / 'DeepEP.tar.gz') as a: a.extractall(ep)
        comm = ep / 'deep_ep/include/deep_ep/common/comm.cuh'
        replace(comm, '''namespace deep_ep::elastic::comm {

static constexpr int64_t kNumOneSecCycles''', '''#ifndef CXI_EP_LOCAL_SELF_SIGNAL
#define CXI_EP_LOCAL_SELF_SIGNAL 0
#endif
static_assert(CXI_EP_LOCAL_SELF_SIGNAL == 0 || CXI_EP_LOCAL_SELF_SIGNAL == 1);

namespace deep_ep::elastic::comm {

static constexpr int64_t kNumOneSecCycles''')
        replace(comm, '''        for (int i = thread_idx; i < kNumRanks; i += kNumThreads)
            gin.signal(team, i, ncclGin_SignalInc{static_cast<ncclGinSignal_t>(rank_idx)});

        // NCCL 2.32.3 provides a bounded, backend-independent signal wait.
        for (int i = thread_idx; i < kNumRanks; i += kNumThreads) {
            const auto signal_idx = static_cast<ncclGinSignal_t>(i);''', '''        // CXI_EP_LOCAL_SELF_SIGNAL: this rank's own arrival needs no NIC round trip; skip both the
        // self-signal (a full fenced signal sequence on context 0) and the wait on its own slot.
        for (int i = thread_idx; i < kNumRanks; i += kNumThreads)
            if (not CXI_EP_LOCAL_SELF_SIGNAL or i != rank_idx)
                gin.signal(team, i, ncclGin_SignalInc{static_cast<ncclGinSignal_t>(rank_idx)});

        // NCCL 2.32.3 provides a bounded, backend-independent signal wait.
        for (int i = thread_idx; i < kNumRanks; i += kNumThreads) {
            if (CXI_EP_LOCAL_SELF_SIGNAL and i == rank_idx)
                continue;
            const auto signal_idx = static_cast<ncclGinSignal_t>(i);''')
        hc = ep / 'deep_ep/include/deep_ep/impls/hybrid_combine.cuh'
        replace(hc, 'static_assert(CXI_EP_COMBINE_FIRST_BATCH >= 1 && CXI_EP_COMBINE_FIRST_BATCH <= CXI_EP_COMBINE_BATCH);',
                '''static_assert(CXI_EP_COMBINE_FIRST_BATCH >= 1 && CXI_EP_COMBINE_FIRST_BATCH <= CXI_EP_COMBINE_BATCH);
#ifndef CXI_EP_SKIP_COMBINE_FLUSH
#define CXI_EP_SKIP_COMBINE_FLUSH 0
#endif
static_assert(CXI_EP_SKIP_COMBINE_FLUSH == 0 || CXI_EP_SKIP_COMBINE_FLUSH == 1);''')
        replace(hc, '''        const auto expected_signal = math::pack2<int, int64_t>(1, 0);
        gin.flush<ncclCoopWarp>();''', '''        const auto expected_signal = math::pack2<int, int64_t>(1, 0);
        // CXI_EP_SKIP_COMBINE_FLUSH: on the direct-CXI backend the end signal is ordered after this
        // context's PUTs by the NIC (delivery marker with flush bit, then CQ fence). The GPU-side
        // counting-event wait is redundant for ordering and holds the context lock against the
        // sibling channel for the whole drain.
        if constexpr (!CXI_EP_SKIP_COMBINE_FLUSH)
            gin.flush<ncclCoopWarp>();''')
        with tarfile.open(out / 'DeepEP.tar.gz', 'w:gz') as a: a.add(ep, arcname='.')
    # ---------------------------------------------------------------- nvcc wrapper / benchmark metadata
    replace(out / 'backend/tests/nvcc_wrapper.py', "    args=['-DCXI_EP_COMBINE_FIRST_BATCH='+str(first_batch),'-DCXI_EP_FIRST_INTERVAL='+str(first_interval)]+args",
            '''    args=['-DCXI_EP_COMBINE_FIRST_BATCH='+str(first_batch),'-DCXI_EP_FIRST_INTERVAL='+str(first_interval)]+args
    skip_flush=int(os.environ.get('CXI_EP_SKIP_COMBINE_FLUSH','0')); self_signal=int(os.environ.get('CXI_EP_LOCAL_SELF_SIGNAL','0'))
    assert skip_flush in (0,1) and self_signal in (0,1)
    args=['-DCXI_EP_SKIP_COMBINE_FLUSH='+str(skip_flush),'-DCXI_EP_LOCAL_SELF_SIGNAL='+str(self_signal)]+args''')
    replace(out / 'backend/tests/ep_benchmark.py', "    case['combine_first_batch']=",
            "    case['skip_combine_flush']=int(os.environ.get('CXI_EP_SKIP_COMBINE_FLUSH','0'))\n    case['local_self_signal']=int(os.environ.get('CXI_EP_LOCAL_SELF_SIGNAL','0'))\n    case['variant']=os.environ.get('CXI_VARIANT','')\n    case['combine_first_batch']=")
    # ---------------------------------------------------------------- ABI: lean_state in the former padding
    abi = out / 'backend/include/cxi_gin_abi.h'
    replace(abi, '  uint32_t tx_unpublished; // descriptors reserved/written but not yet doorbelled\n',
            '''  uint32_t tx_unpublished; // descriptors reserved/written but not yet doorbelled
  // Lean signal bookkeeping (device-owned; constants in cxi_primitives.cuh): bit 0 a transfer that
  // must precede the next signal was posted since the last CQ fence, bit 1 the newest ring entry is
  // the still-unpublished pending payload PUT, bits 8..16 cached CSTATE key. Host sets it to 1.
  uint32_t lean_state;
''')
    replace(abi, '  // Remains inside the previous trailing padding; sizeof stays 192 bytes.\n',
            '  // pending_* and lean_state live inside the previous trailing padding; sizeof stays 192 bytes.\n')
    # ---------------------------------------------------------------- host: initialise lean_state
    res = out / 'backend/host/cxi_resources.cc'
    replace(res, '    auto& d=q->descriptor;d.abi_version=CXI_GIN_ABI_VERSION;\n',
            '    auto& d=q->descriptor;d.abi_version=CXI_GIN_ABI_VERSION;d.lean_state=1; // fence due, no cached CSTATE\n')
    replace(res, '  q->descriptor.pending_lac=0;q->descriptor.pending_peer=0;\n',
            '  q->descriptor.pending_lac=0;q->descriptor.pending_peer=0;q->descriptor.lean_state=1;\n')
    # ---------------------------------------------------------------- device primitives
    prim = out / 'backend/device/cxi_primitives.cuh'
    replace(prim, '''namespace cxi_gin {
constexpr uint64_t default_timeout=10000000000ULL;
''', '''#ifndef CXI_LEAN_FENCE
#define CXI_LEAN_FENCE 0
#endif
#ifndef CXI_LEAN_CSTATE
#define CXI_LEAN_CSTATE 0
#endif
#ifndef CXI_LEAN_FOLD_MARKER
#define CXI_LEAN_FOLD_MARKER 0
#endif
static_assert(!CXI_LEAN_FOLD_MARKER || CXI_BATCH_DELIVERY, "the marker fold replaces the batched-delivery marker");
namespace cxi_gin {
constexpr uint64_t default_timeout=10000000000ULL;
// CxiGpuContext::lean_state bits (host initialises the field to lean_fence_due).
constexpr uint32_t lean_fence_due=1u;         // a fenced-before-signal transfer was posted since the last CQ fence
constexpr uint32_t lean_last_is_put=2u;       // newest ring entry is the pending payload PUT and is unpublished
constexpr uint32_t lean_cstate_mask=0x1FF00u; // bits 8..12 index_ext, 13..15 write_lac, 16 valid
__device__ __forceinline__ uint32_t lean_cstate_key(unsigned index_ext,unsigned write_lac) {
  return (1u<<16)|((index_ext&31u)<<8)|((write_lac&7u)<<13);
}
''')
    replace(prim, '''__device__ __forceinline__ void publish_locked(CxiGpuContext& c) {
  if(!c.tx_unpublished)return;
''', '''__device__ __forceinline__ void publish_locked(CxiGpuContext& c) {
  c.lean_state&=~lean_last_is_put; // a doorbelled entry can no longer be rewritten
  if(!c.tx_unpublished)return;
''')
    replace(prim, '''  uint64_t start=clock64();
  while(true) {
    uint32_t status=load32((uint32_t*)c.tx_queue);
''', '''  uint64_t start=clock64();
  c.lean_state&=~lean_last_is_put; // any new command supersedes the pending PUT as newest entry
  while(true) {
    uint32_t status=load32((uint32_t*)c.tx_queue);
''')
    replace(prim, '''  publish_locked(c);
  if(c.completed==c.posted)return true;
  uint64_t start=clock64();
  do {
''', '''  publish_locked(c);
  if(c.completed==c.posted){c.lean_state&=~lean_fence_due;return true;}
  uint64_t start=clock64();
  do {
''')
    replace(prim, '''  }while(c.completed<c.posted);
  __threadfence_system();return true;
}''', '''  }while(c.completed<c.posted);
  c.lean_state&=~lean_fence_due; // everything posted is delivered; no fence needed before the next signal
  __threadfence_system();return true;
}''')
    replace(prim, '''  const auto* w=c.pending_dst;
  if(!w)return true;
  int peer=c.pending_peer;
''', '''  const auto* w=c.pending_dst;
  if(!w)return true;
#if CXI_LEAN_FOLD_MARKER
  if(c.lean_state&lean_last_is_put) {
    // Close the epoch on the pending PUT itself: it is the newest ring entry and not yet
    // doorbelled, so its descriptor can still be rewritten. Delivery semantics equal the
    // zero-byte marker (flush bit, CT_ACK); the CT still counts one event for this command and
    // c.posted is unchanged, so flush accounting is identical.
    unsigned slot=c.tx_wp32==8?c.tx_size32-2:c.tx_wp32-2;
    auto* cmd=(c_full_dma_cmd*)(c.tx_queue+slot*4);
    cmd->event_ct_send=0;cmd->event_ct_ack=1;cmd->flush=1;
    __threadfence_system();
    c.lean_state&=~lean_last_is_put;c.pending_dst=nullptr;
    return true;
  }
#endif
  int peer=c.pending_peer;
''')
    replace(prim, '''  if(!emit(c,words,true,abort,timeout,true))return false;
  c.pending_dst=nullptr;
  return true;
}''', '''  if(!emit(c,words,true,abort,timeout,true))return false;
  c.pending_dst=nullptr;c.lean_state|=lean_fence_due;
  return true;
}''')
    replace(prim, '''    c.pending_remote_offset=dstoff+n-1;
#endif
    dstoff+=n;srcoff+=n;bytes-=n;
''', '''    c.pending_remote_offset=dstoff+n-1;
#if CXI_LEAN_FOLD_MARKER
    // The PUT just written is the newest ring entry; it stays rewritable until published.
    if(c.tx_unpublished)c.lean_state|=lean_last_is_put;
#endif
#endif
    c.lean_state|=lean_fence_due;
    dstoff+=n;srcoff+=n;bytes-=n;
''')
    replace(prim, '''__device__ __forceinline__ bool state_locked(CxiGpuContext& c,const CxiWindow* dst,int peer,uint32_t* abort=nullptr) {
  uint64_t words[8]{};auto* st=(c_cstate_cmd*)words;
''', '''__device__ __forceinline__ bool state_locked(CxiGpuContext& c,const CxiWindow* dst,int peer,uint32_t* abort=nullptr) {
#if CXI_LEAN_CSTATE
  // CSTATE is command-queue state consumed by later IDC commands; DMA commands carry their own
  // fields and leave it alone. Re-emit only when the (index_ext, write_lac) pair changes.
  const uint32_t key=lean_cstate_key(dst->peer[peer].index_ext,dst->local_lac);
  if((c.lean_state&lean_cstate_mask)==key)return true;
#endif
  uint64_t words[8]{};auto* st=(c_cstate_cmd*)words;
''')
    replace(prim, '''  st->write_lac=dst->local_lac;return emit(c,words,false,abort);
}''', '''  st->write_lac=dst->local_lac;
  if(!emit(c,words,false,abort))return false;
#if CXI_LEAN_CSTATE
  c.lean_state=(c.lean_state&~lean_cstate_mask)|key;
#endif
  return true;
}''')
    replace(prim, '''  uint64_t words[8];cxi_build_fence_command(words);
  return emit(c,words,false,abort,default_timeout,true);
}''', '''#if CXI_LEAN_FENCE
  // Nothing fence-worthy since the last fence or completed flush: that earlier fence already
  // orders this signal after every prior transfer on the context.
  if(!(c.lean_state&lean_fence_due))return true;
#endif
  uint64_t words[8];cxi_build_fence_command(words);
  if(!emit(c,words,false,abort,default_timeout,true))return false;
  c.lean_state&=~lean_fence_due;
  return true;
}''')
    replace(prim, '''  hdr->length=16+bytes;*(uint32_t*)&hdr->dfa=dst->peer[peer].dfa;hdr->remote_offset=off;words[2]=value;
  __threadfence_system();return emit(c,words,true,abort);
}''', '''  hdr->length=16+bytes;*(uint32_t*)&hdr->dfa=dst->peer[peer].dfa;hdr->remote_offset=off;words[2]=value;
  __threadfence_system();if(!emit(c,words,true,abort))return false;
  c.lean_state|=lean_fence_due;return true;
}''')
    # ---------------------------------------------------------------- variants and preflight
    variants = json.loads((out / 'variants.json').read_text())
    base = dict(variants['marker-zero'])
    variants['lean-a'] = dict(base, CXI_LEAN_FENCE=1, CXI_LEAN_CSTATE=1)
    variants['lean-b'] = dict(base, CXI_LEAN_FENCE=1, CXI_LEAN_CSTATE=1, CXI_LEAN_FOLD_MARKER=1)
    (out / 'variants.json').write_text(json.dumps(variants, indent=2) + '\n')
    pf = out / 'runner/preflight.sh'
    replace(pf, 'for variant in marker-zero; do', 'for variant in marker-zero lean-a lean-b; do')
    replace(pf, '''g++ -std=c++17 -Wall -Wextra -Werror -I"$src/backend/device"   "$src/runner/test_fence_descriptor.cc" -o "$out/fence-descriptor"''',
            '''"$sdk/bin/nvcc" -std=c++17 -arch=sm_90 -DCXI_LEAN_FENCE=1 -DCXI_LEAN_CSTATE=1 -DCXI_LEAN_FOLD_MARKER=1 -DCXI_ZERO_DELIVERY_MARKER=1 -DCXI_HW_SIGNAL_FENCE=1 -DCXI_TX_BATCH_LIMIT=8 -DCXI_BATCH_DELIVERY=1 -DCXI_CT_THRESHOLD_FLUSH=1 \\
  -I"$src/backend/include" -I"$src/backend/device" -c "$src/runner/burst_probe.cu" -o "$out/burst-lean.o"
g++ -std=c++17 -Wall -Wextra -Werror -I"$src/backend/device"   "$src/runner/test_fence_descriptor.cc" -o "$out/fence-descriptor"''')
