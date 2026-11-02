"""Double-buffered TMA staging for the combine scale-up warps (plan item 2.4b), knob CXI_EP_COMBINE_DOUBLE_TMA.

Today each scale-up warp owns one shared-memory token buffer: load (or reduce) into it, wait for the
load, TMA-store it to the NVLink peer, and the next token's load must first wait for that store to
drain (`cp.async.bulk.wait_group 0`). With the knob on, each scale-up warp gets a second staging
buffer (placed after all first-stage buffers; the launcher already passes the maximum dynamic shared
memory), tokens alternate between the two, and the wait before refilling a buffer allows the most
recent store group to stay in flight (`wait_group 1`), so token n's NVLink store overlaps token n+1's
load/reduction. Tail publication (`update_tails`) still drains all stores first. Applied on top of
prepare_lean_1102 (the snapshot's DeepEP archive must already carry the lean edits).
"""
import tarfile, tempfile, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'pipeline_v1'))
from package import replace  # noqa: E402

def prepare(snapshot):
    out = Path(snapshot)
    with tempfile.TemporaryDirectory() as tmp:
        ep = Path(tmp)
        with tarfile.open(out / 'DeepEP.tar.gz') as a: a.extractall(ep)
        hc = ep / 'deep_ep/include/deep_ep/impls/hybrid_combine.cuh'
        replace(hc, 'static_assert(CXI_EP_SKIP_COMBINE_FLUSH == 0 || CXI_EP_SKIP_COMBINE_FLUSH == 1);',
                '''static_assert(CXI_EP_SKIP_COMBINE_FLUSH == 0 || CXI_EP_SKIP_COMBINE_FLUSH == 1);
#ifndef CXI_EP_COMBINE_DOUBLE_TMA
#define CXI_EP_COMBINE_DOUBLE_TMA 0
#endif
static_assert(CXI_EP_COMBINE_DOUBLE_TMA == 0 || CXI_EP_COMBINE_DOUBLE_TMA == 1);''')
        replace(hc, '''    const auto tma_buffer = layout::BufferLayout<true>(
        token_layout, kNumWarps, 1, smem).get_rank_buffer(warp_idx).get_token_buffer(0);
''', '''    const auto tma_buffers = layout::BufferLayout<true>(token_layout, kNumWarps, 1, smem);
    const auto tma_buffer = tma_buffers.get_rank_buffer(warp_idx).get_token_buffer(0);
#if CXI_EP_COMBINE_DOUBLE_TMA
    // CXI_EP_COMBINE_DOUBLE_TMA: a second staging buffer per scale-up warp, placed after all first-stage
    // buffers, so a token's NVLink store overlaps the next token's load or reduction. The launcher
    // always passes the device's maximum dynamic shared memory; this bound keeps us inside it.
    static_assert((kNumWarps + kNumScaleupWarps) * (kNumHiddenBytes + 1024) <= 220 * 1024,
                  "double-buffered staging must fit in shared memory");
    const auto tma_buffer_alt = layout::BufferLayout<true>(token_layout, kNumScaleupWarps, 1, tma_buffers.get_buffer_end_ptr())
        .get_rank_buffer(warp_idx < kNumScaleupWarps ? warp_idx : 0).get_token_buffer(0);
#endif
''')
        replace(hc, '''    ptx::arrival_phase phase = 0;
    const auto mbarrier_ptr = tma_buffer.get_mbarrier_ptr();
    if (ptx::elect_one_sync())
        ptx::mbarrier_init_with_fence(mbarrier_ptr, 1);
    __syncwarp();
''', '''    ptx::arrival_phase phase = 0;
    const auto mbarrier_ptr = tma_buffer.get_mbarrier_ptr();
    if (ptx::elect_one_sync())
        ptx::mbarrier_init_with_fence(mbarrier_ptr, 1);
    __syncwarp();
#if CXI_EP_COMBINE_DOUBLE_TMA
    ptx::arrival_phase phase_alt = 0;
    const auto mbarrier_alt_ptr = tma_buffer_alt.get_mbarrier_ptr();
    if (warp_idx < kNumScaleupWarps and ptx::elect_one_sync())
        ptx::mbarrier_init_with_fence(mbarrier_alt_ptr, 1);
    __syncwarp();
#endif
''')
        replace(hc, '        int dst_scaleup_rank_idx = channel_idx;\n',
                '        int dst_scaleup_rank_idx = channel_idx;\n        [[maybe_unused]] int scaleup_token_counter = 0;\n')
        replace(hc, '''                token_idx = ptx::exchange(token_idx, dst_scaleup_rank_idx % 32);

                // Get source metadata and decide the destination buffer
''', '''                token_idx = ptx::exchange(token_idx, dst_scaleup_rank_idx % 32);

                // Staging buffer for this token (alternates when double-buffered)
#if CXI_EP_COMBINE_DOUBLE_TMA
                const bool use_alt = (scaleup_token_counter ++) & 1;
                const auto stage = use_alt ? tma_buffer_alt : tma_buffer;
                const auto stage_mbarrier = use_alt ? mbarrier_alt_ptr : mbarrier_ptr;
                auto& stage_phase = use_alt ? phase_alt : phase;
#else
                const auto& stage = tma_buffer;
                const auto stage_mbarrier = mbarrier_ptr;
                auto& stage_phase = phase;
#endif

                // Get source metadata and decide the destination buffer
''')
        replace(hc, '''                        ptx::tma_store_wait();
                        ptx::tma_load_1d(tma_buffer.get_base_ptr(), load_ptr, mbarrier_ptr, kNumHiddenBytes);
                    }
                    __syncwarp();
                } else if constexpr (kAllowMultipleReduction) {''', '''                        // Double-buffered: only the store that used this buffer (two tokens ago) must be done
                        ptx::tma_store_wait<CXI_EP_COMBINE_DOUBLE_TMA>();
                        ptx::tma_load_1d(stage.get_base_ptr(), load_ptr, stage_mbarrier, kNumHiddenBytes);
                    }
                    __syncwarp();
                } else if constexpr (kAllowMultipleReduction) {''')
        replace(hc, '''                        lane_idx, topk_slot_idx, static_cast<combine_vec_t*>(tma_buffer.get_base_ptr()),
                        /* Get source base */ [=](const int& slot_idx) {
                            return math::advance_ptr<combine_vec_t>(
                                x, slot_idx * static_cast<int64_t>(kNumHiddenBytes));
                        },
                        /* Wait buffer release */ [=]() {
                            ptx::tma_store_wait();''', '''                        lane_idx, topk_slot_idx, static_cast<combine_vec_t*>(stage.get_base_ptr()),
                        /* Get source base */ [=](const int& slot_idx) {
                            return math::advance_ptr<combine_vec_t>(
                                x, slot_idx * static_cast<int64_t>(kNumHiddenBytes));
                        },
                        /* Wait buffer release */ [=]() {
                            ptx::tma_store_wait<CXI_EP_COMBINE_DOUBLE_TMA>();''')
        replace(hc, '                    tma_buffer.get_topk_weights_ptr()[lane_idx] = value;\n',
                '                    stage.get_topk_weights_ptr()[lane_idx] = value;\n')
        replace(hc, '''                    if (no_local_reduce) {
                        ptx::mbarrier_arrive_and_set_tx(mbarrier_ptr, kNumHiddenBytes);
                        ptx::mbarrier_wait_and_flip_phase(mbarrier_ptr, phase);
                    }

                    // Issue stores
                    ptx::tma_store_1d(
                        token_buffer.get_base_ptr(), tma_buffer.get_base_ptr(),
                        token_layout.get_num_bytes<false>());
                    ptx::tma_store_commit();''', '''                    if (no_local_reduce) {
                        ptx::mbarrier_arrive_and_set_tx(stage_mbarrier, kNumHiddenBytes);
                        ptx::mbarrier_wait_and_flip_phase(stage_mbarrier, stage_phase);
                    }

                    // Issue stores
                    ptx::tma_store_1d(
                        token_buffer.get_base_ptr(), stage.get_base_ptr(),
                        token_layout.get_num_bytes<false>());
                    ptx::tma_store_commit();''')
        with tarfile.open(out / 'DeepEP.tar.gz', 'w:gz') as a: a.add(ep, arcname='.')
    replace(out / 'backend/tests/nvcc_wrapper.py', "    args=['-DCXI_EP_SKIP_COMBINE_FLUSH='+str(skip_flush),'-DCXI_EP_LOCAL_SELF_SIGNAL='+str(self_signal)]+args",
            '''    args=['-DCXI_EP_SKIP_COMBINE_FLUSH='+str(skip_flush),'-DCXI_EP_LOCAL_SELF_SIGNAL='+str(self_signal)]+args
    double_tma=int(os.environ.get('CXI_EP_COMBINE_DOUBLE_TMA','0')); assert double_tma in (0,1)
    args=['-DCXI_EP_COMBINE_DOUBLE_TMA='+str(double_tma)]+args''')
    replace(out / 'backend/tests/ep_benchmark.py', "    case['skip_combine_flush']=",
            "    case['combine_double_tma']=int(os.environ.get('CXI_EP_COMBINE_DOUBLE_TMA','0'))\n    case['skip_combine_flush']=")
