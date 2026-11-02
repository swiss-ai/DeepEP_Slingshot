"""Merge a final full-batch tail with the existing mandatory finish update.

Only the uniform last loop iteration skips its ordinary notification. The
unconditional finish call remains, including for empty/local-only channels.
"""
import tarfile,tempfile
from pathlib import Path
from package import replace


def prepare(snapshot):
    root=Path(snapshot)
    with tempfile.TemporaryDirectory() as directory:
        ep=Path(directory)
        with tarfile.open(root/'DeepEP.tar.gz') as archive:archive.extractall(ep)
        header=ep/'deep_ep/include/deep_ep/impls/hybrid_dispatch.cuh'
        replace(header,'#pragma once','''#pragma once
#ifndef CXI_EP_MERGE_FINAL_TAIL
#define CXI_EP_MERGE_FINAL_TAIL 0
#endif
static_assert(CXI_EP_MERGE_FINAL_TAIL == 0 || CXI_EP_MERGE_FINAL_TAIL == 1);''')
        replace(header,'''            // Issue scale-out tail update
            update_scaleout_tail();''','''            // The unconditional finish below can publish the last batch and
            // finish bit together, just as it already does for partial batches.
            // Keep intermediate progress and empty-channel finish unchanged.
            if (!CXI_EP_MERGE_FINAL_TAIL || token_idx + kNumChannels < num_tokens)
                update_scaleout_tail();''')
        assert header.read_text().count('        update_scaleout_tail(true);')==1
        with tarfile.open(root/'DeepEP.tar.gz','w:gz') as archive:archive.add(ep,arcname='.')
    replace(root/'backend/tests/nvcc_wrapper.py',"    packed=int(os.environ.get('CXI_EP_PACK_ROWS','0'))",'''    merge_final=int(os.environ.get('CXI_EP_MERGE_FINAL_TAIL','0'))
    assert merge_final in (0,1)
    args=['-DCXI_EP_MERGE_FINAL_TAIL='+str(merge_final)]+args
    packed=int(os.environ.get('CXI_EP_PACK_ROWS','0'))''')
    replace(root/'backend/tests/ep_benchmark.py',"    case['packed_remote_rows']=",
        "    case['merged_final_tail']=bool(int(os.environ.get('CXI_EP_MERGE_FINAL_TAIL','0')))\n    case['packed_remote_rows']=")
    validator=root/'runner/validate_gate.py'
    replace(validator,"        packed = env.get('CXI_EP_PACK_ROWS')",'''        merged_final=env.get('CXI_EP_MERGE_FINAL_TAIL')
        if merged_final is not None:
            require(merged_final in ('0','1'), 'invalid final-tail mode')
            reports=list((Path(destination)/'compiler-reports').rglob('*.txt'))
            require(reports and all('-DCXI_EP_MERGE_FINAL_TAIL='+merged_final+' ' in p.read_text() for p in reports),
                    'final-tail compiler evidence missing or mismatched')
        packed = env.get('CXI_EP_PACK_ROWS')''')
    replace(validator,"            if packed is not None:",'''            if merged_final is not None:
                require(all(r.get('merged_final_tail') is bool(int(merged_final)) for r in rows),
                        'final-tail rank evidence missing or mismatched')
            if packed is not None:''')
