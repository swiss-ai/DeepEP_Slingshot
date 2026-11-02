#!/usr/bin/env python3
"""Context prewarm during the entry barrier (2026-11-02 late evening).

Finding (jobs 3837687/3837809/3838245 traces): every channel's first PUT of a dispatch spends ~100 us in
the transport. Without cached credits the time is in the NIC status read (a load from the host-mapped
command ring); with cached credits the load is gone and the same time appears in the ring store plus
system fence instead. Whatever touches a context's ring first in the kernel pays ~80 us when 128 contexts
start together after the barrier; later accesses cost 1-3 us. The receivers are idle meanwhile and the
NIC drains at the ceiling once fed, so the first emission (0.21 ms instead of ~0.12) is the dispatch loss.

Change (CXI_EP_PREWARM_CONTEXTS, compile-time knob injected by the nvcc wrapper): in the GIN barrier,
before the signalling SM starts, every thread of the grid touches one context's ring (a load of the
NIC-written status word, no lock, read-only) so that the first access per context overlaps the barrier's
own wait instead of the first PUT. Backend: `nccl::gin::cxi::prewarm(ctx)` in gin_cxi.cuh. The DeepEP
side reaches the backend context through the public NCCL handle (`ncclGin::_makeCtx()`).
"""
import sys, tarfile, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'pipeline_v1'))
from package import replace  # noqa: E402

def prepare(snapshot, archives=('DeepEP.tar.gz',)):
    out = Path(snapshot)
    gin = out / 'backend/device/gin_cxi.cuh'
    replace(gin, '''NCCL_DEVICE_INLINE void require(bool ok){if(!ok)asm volatile("trap;");}
''', '''NCCL_DEVICE_INLINE void require(bool ok){if(!ok)asm volatile("trap;");}
// Touch a context's command ring once (a load of the NIC-written status word, no lock, read-only) so
// that the first emission on it later in the kernel does not pay the first access to the host-mapped
// page; measured 80-100 us per channel when 128 contexts start together after the entry barrier.
NCCL_DEVICE_INLINE void prewarm(ncclGinCtx ctx){auto& c=context(ctx);(void)cxi_gin::load32((uint32_t*)c.tx_queue);}
''')
    for archive in archives:
      with tempfile.TemporaryDirectory() as d:
        ep = Path(d)
        with tarfile.open(out / archive) as a: a.extractall(ep)
        comm = ep / 'deep_ep/include/deep_ep/common/comm.cuh'
        replace(comm, '''#ifndef CXI_EP_LOCAL_SELF_SIGNAL
#define CXI_EP_LOCAL_SELF_SIGNAL 0
#endif
''', '''#ifndef CXI_EP_LOCAL_SELF_SIGNAL
#define CXI_EP_LOCAL_SELF_SIGNAL 0
#endif
#ifndef CXI_EP_PREWARM_CONTEXTS
#define CXI_EP_PREWARM_CONTEXTS 0
#endif
''')
        replace(comm, '''    if (sm_idx == 0) {
        // Use QP 0 to do barrier
''', '''    // CXI_EP_PREWARM_CONTEXTS: touch every GIN context's command ring once while the barrier is pending,
    // so the first PUT of each channel does not pay the first access to the host-mapped ring (measured
    // 80-100 us per channel when 128 contexts start together). One context per thread, grid-wide.
    if constexpr (CXI_EP_PREWARM_CONTEXTS) {
        for (int i = global_warp_idx * 32 + (thread_idx % 32); i < num_qps; i += kNumSMs * kNumWarps * 32)
            nccl::gin::cxi::prewarm(ncclGin(nccl_dev_comm, i, NCCL_GIN_RESOURCE_SHARING_CTA)._makeCtx());
    }

    if (sm_idx == 0) {
        // Use QP 0 to do barrier
''')
        with tarfile.open(out / archive, 'w:gz') as a: a.add(ep, arcname='.')
    anchor = "    args=['-DCXI_EP_SKIP_COMBINE_FLUSH='+str(skip_flush),'-DCXI_EP_LOCAL_SELF_SIGNAL='+str(self_signal)]+args\n"
    replace(out / 'backend/tests/nvcc_wrapper.py', anchor, anchor +
            "    prewarm=int(os.environ.get('CXI_EP_PREWARM_CONTEXTS','0')); assert prewarm in (0,1)\n"
            "    args=['-DCXI_EP_PREWARM_CONTEXTS='+str(prewarm)]+args\n")
    replace(out / 'backend/tests/ep_benchmark.py', "    case['local_self_signal']=int(os.environ.get('CXI_EP_LOCAL_SELF_SIGNAL','0'))\n",
            "    case['local_self_signal']=int(os.environ.get('CXI_EP_LOCAL_SELF_SIGNAL','0'))\n"
            "    case['prewarm_contexts']=int(os.environ.get('CXI_EP_PREWARM_CONTEXTS','0'))\n")
    return out

if __name__ == '__main__':
    prepare(sys.argv[1]); print('prepared', sys.argv[1])
