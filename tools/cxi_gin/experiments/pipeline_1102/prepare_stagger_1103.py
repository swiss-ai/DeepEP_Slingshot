#!/usr/bin/env python3
"""Start stagger of the dispatch channels (2026-11-03 midday, diagnostic knob).

Finding so far: every channel's first PUT costs ~100 us in its first access to the command ring when the
128 contexts start together after the barrier (11_02 log §5.3-5.9), with the registered IO-memory ring
and with the ring addressed through the host page tables (ATS, 11_03 log §3) alike; a prior load of the
same word does not help. Two mechanisms remain: contention at a shared point (then spreading the first
accesses in time makes each of them cheap) or a per-context latency independent of concurrency (then a
staggered channel still pays ~90 us). The stagger also moves the earliest first emissions to ~0.11 ms,
which tells whether the receive end follows (convoy on the critical path) or not.

Knob CXI_EP_STAGGER_NS (compile-time, injected by the nvcc wrapper from the environment): each dispatch
scale-out sender warp sleeps channel_idx * CXI_EP_STAGGER_NS nanoseconds right after the entry barrier
(256 channels x 400 ns = 0..102 us, the length of today's convoy; 800 ns = 0..204 us). Forward warps,
receivers and the combine are untouched.
"""
import sys, tarfile, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'pipeline_v1'))
from package import replace  # noqa: E402

def prepare(snapshot, archives=('DeepEP.tar.gz', 'DeepEP-trace.tar.gz')):
    out = Path(snapshot)
    for archive in archives:
      with tempfile.TemporaryDirectory() as d:
        ep = Path(d)
        with tarfile.open(out / archive) as a: a.extractall(ep)
        f = ep / 'deep_ep/include/deep_ep/impls/hybrid_dispatch.cuh'
        replace(f, '''#ifndef CXI_EP_FIRST_INTERVAL
#define CXI_EP_FIRST_INTERVAL CXI_EP_UPDATE_INTERVAL
#endif
''', '''#ifndef CXI_EP_FIRST_INTERVAL
#define CXI_EP_FIRST_INTERVAL CXI_EP_UPDATE_INTERVAL
#endif
#ifndef CXI_EP_STAGGER_NS
#define CXI_EP_STAGGER_NS 0
#endif
static_assert(CXI_EP_STAGGER_NS >= 0 && CXI_EP_STAGGER_NS <= 4000, "stagger per channel in ns, at most ~1 ms over 256 channels");
''')
        replace(f, '''        const int channel_idx = sm_idx * kNumChannelsPerSM + scaleout_warp_idx;
''', '''        const int channel_idx = sm_idx * kNumChannelsPerSM + scaleout_warp_idx;
        // CXI_EP_STAGGER_NS (diagnostic): spread the channels' first ring access after the barrier by
        // channel_idx * ns, to separate a shared-path contention cost from a per-context first-touch latency.
        if constexpr (CXI_EP_STAGGER_NS > 0) {
            __nanosleep(static_cast<unsigned>(channel_idx) * CXI_EP_STAGGER_NS);
            __syncwarp();
        }
''')
        with tarfile.open(out / archive, 'w:gz') as a: a.add(ep, arcname='.')
    anchor = "    args=['-DCXI_EP_SKIP_COMBINE_FLUSH='+str(skip_flush),'-DCXI_EP_LOCAL_SELF_SIGNAL='+str(self_signal)]+args\n"
    replace(out / 'backend/tests/nvcc_wrapper.py', anchor, anchor +
            "    stagger=int(os.environ.get('CXI_EP_STAGGER_NS','0')); assert 0<=stagger<=4000\n"
            "    args=['-DCXI_EP_STAGGER_NS='+str(stagger)]+args\n")
    replace(out / 'backend/tests/ep_benchmark.py', "    case['local_self_signal']=int(os.environ.get('CXI_EP_LOCAL_SELF_SIGNAL','0'))\n",
            "    case['local_self_signal']=int(os.environ.get('CXI_EP_LOCAL_SELF_SIGNAL','0'))\n"
            "    case['stagger_ns']=int(os.environ.get('CXI_EP_STAGGER_NS','0'))\n")
    return out

if __name__ == '__main__':
    prepare(sys.argv[1]); print('prepared', sys.argv[1])
