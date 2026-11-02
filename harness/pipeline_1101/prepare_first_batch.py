"""Smaller first batches so the wire starts earlier: dispatch's first progress notification after
CXI_EP_FIRST_INTERVAL rows (then the regular interval), combine's first remote PUT after
CXI_EP_COMBINE_FIRST_BATCH reduced rows (then the regular batch). Both default to the regular values."""
import tarfile, tempfile, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'pipeline_v1'))
from package import replace  # noqa: E402

def prepare(snapshot):
    out = Path(snapshot)
    with tempfile.TemporaryDirectory() as tmp:
        ep = Path(tmp)
        with tarfile.open(out / 'DeepEP.tar.gz') as a: a.extractall(ep)
        hd = ep / 'deep_ep/include/deep_ep/impls/hybrid_dispatch.cuh'
        replace(hd, 'static_assert(CXI_EP_FORWARD_CHUNK >= 1 && CXI_EP_FORWARD_CHUNK <= 64);',
                '''static_assert(CXI_EP_FORWARD_CHUNK >= 1 && CXI_EP_FORWARD_CHUNK <= 64);
#ifndef CXI_EP_FIRST_INTERVAL
#define CXI_EP_FIRST_INTERVAL CXI_EP_UPDATE_INTERVAL
#endif
static_assert(CXI_EP_FIRST_INTERVAL >= 1 && CXI_EP_FIRST_INTERVAL <= CXI_EP_UPDATE_INTERVAL);''')
        replace(hd, '''                (stored_scaleout_tail >= stored_old_scaleout_tail + kScaleoutUpdateInterval or finish_flag)) {''',
                '''                (stored_scaleout_tail >= stored_old_scaleout_tail +
                     (stored_old_scaleout_tail == 0 ? CXI_EP_FIRST_INTERVAL : kScaleoutUpdateInterval) or finish_flag)) {''')
        hc = ep / 'deep_ep/include/deep_ep/impls/hybrid_combine.cuh'
        replace(hc, 'static_assert(CXI_EP_COMBINE_BATCH >= 1 && CXI_EP_COMBINE_BATCH <= 64);',
                '''static_assert(CXI_EP_COMBINE_BATCH >= 1 && CXI_EP_COMBINE_BATCH <= 64);
#ifndef CXI_EP_COMBINE_FIRST_BATCH
#define CXI_EP_COMBINE_FIRST_BATCH CXI_EP_COMBINE_BATCH
#endif
static_assert(CXI_EP_COMBINE_FIRST_BATCH >= 1 && CXI_EP_COMBINE_FIRST_BATCH <= CXI_EP_COMBINE_BATCH);''')
        replace(hc, '        int packed_first_j = -1, packed_last_j = -1, packed_peer = -1;',
                '        int packed_first_j = -1, packed_last_j = -1, packed_peer = -1;\n        bool packed_any_flushed = false;')
        replace(hc, '''                __syncwarp();
                packed_first_j = -1;
            }
        };''', '''                __syncwarp();
                if (packed_first_j >= 0)
                    packed_any_flushed = true;
                packed_first_j = -1;
            }
        };''')
        replace(hc, '                        if (packed_last_j - packed_first_j + 1 >= CXI_EP_COMBINE_BATCH)',
                '                        if (packed_last_j - packed_first_j + 1 >= (packed_any_flushed ? CXI_EP_COMBINE_BATCH : CXI_EP_COMBINE_FIRST_BATCH))')
        with tarfile.open(out / 'DeepEP.tar.gz', 'w:gz') as a: a.add(ep, arcname='.')
    replace(out / 'backend/tests/nvcc_wrapper.py', "    packc=int(os.environ.get('CXI_EP_PACK_COMBINE','0')); batch=int(os.environ.get('CXI_EP_COMBINE_BATCH','16'))",
            '''    packc=int(os.environ.get('CXI_EP_PACK_COMBINE','0')); batch=int(os.environ.get('CXI_EP_COMBINE_BATCH','16'))
    first_batch=int(os.environ.get('CXI_EP_COMBINE_FIRST_BATCH',str(batch))); first_interval=int(os.environ.get('CXI_EP_FIRST_INTERVAL',os.environ.get('CXI_EP_UPDATE_INTERVAL','3')))
    assert 1 <= first_batch <= batch and 1 <= first_interval <= 64
    args=['-DCXI_EP_COMBINE_FIRST_BATCH='+str(first_batch),'-DCXI_EP_FIRST_INTERVAL='+str(first_interval)]+args''')
    replace(out / 'backend/tests/ep_benchmark.py', "    case['packed_combine']=",
            "    case['combine_first_batch']=int(os.environ.get('CXI_EP_COMBINE_FIRST_BATCH',os.environ.get('CXI_EP_COMBINE_BATCH','16')))\n    case['first_interval']=int(os.environ.get('CXI_EP_FIRST_INTERVAL',os.environ.get('CXI_EP_UPDATE_INTERVAL','3')))\n    case['packed_combine']=")
