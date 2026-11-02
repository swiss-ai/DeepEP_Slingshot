"""Private ABI-v2 bounded doorbell batching, with batch-1 control and GPU gates."""
import argparse
import hashlib
import json
import shutil
from pathlib import Path
from package import ROOT, REMOTE, replace
from prepare_aggregation import prepare


def main():
    parser=argparse.ArgumentParser();parser.add_argument('output',type=Path)
    out=parser.parse_args().output.resolve()
    base=ROOT/'results/deepep_pipeline_20261030/source-v1'
    shutil.copytree(base,out,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    prepare(out)
    variants={'batch'+str(n):dict(CXI_CT_THRESHOLD_FLUSH=1,CXI_TX_BATCH_LIMIT=n) for n in [1,8,32]}
    (out/'variants.json').write_text(json.dumps(variants,indent=2)+'\n')
    installer=out/'runner/install.py'
    replace(installer,"for base in ['baseline','async','cap4','threshold']:variants[base+'-trace']=dict(variants[base])",'')
    replace(installer,"for name in ['cxi_primitives.cuh','cxi_queue_credit.h']:shutil.copyfile(snapshot/'backend/device'/name,d/name)",
            "for name in ['cxi_primitives.cuh','cxi_queue_credit.h','gin_cxi.cuh']:shutil.copyfile(snapshot/'backend/device'/name,d/name)\n        shutil.copyfile(snapshot/'backend/include/cxi_gin_abi.h',d/'cxi_gin_abi.h')")
    preflight=out/'runner/preflight.sh'
    replace(preflight,'for variant in threshold threshold-trace; do','for variant in batch1 batch8 batch32; do')
    replace(preflight,'for limit in 0 1 2 4 8; do','for limit in 1 8 32; do')
    replace(preflight,'-DCXI_TX_PENDING_LIMIT="$limit"','-DCXI_TX_BATCH_LIMIT="$limit"')
    source=REMOTE+'/sources/'+out.name
    seq=[]
    common=dict(CXI_EP_SMS='64',CXI_EP_CONTEXTS='129',CXI_EP_DEBUG='0',CXI_TRANSPORT='direct',
                CXI_QUEUE_INVENTORY='1',CXI_EP_UPDATE_INTERVAL='3',CXI_DEVICE_TRACE='0')
    settings=dict(CXI_EP_MODELS='v4flash',CXI_EP_TOKENS='4096 16384',CXI_EP_DTYPES='fp8',
                  CXI_EP_ROUTING='mixed',CXI_EP_SEEDS='1',CXI_EP_WARMUP='20',CXI_EP_ITERS='100',
                  CXI_EP_NIC_ITERS='600',CXI_EP_PROFILE_STEPS='0')
    def add(label,variant,kind,qualification,extra,requires=(),snapshot=source,duration=1200):
        name='%02d-%s'%(31+len(seq),label)
        env=dict(common,CXI_VARIANT=variant,CXI_TEST_KIND=kind,CXI_TEST_TIMEOUT=str(duration-60))
        env.update(extra)
        seq.append(dict(name=name,snapshot=snapshot,node_script='runner/node.sh',qualification=qualification,
                        timeout_seconds=duration,environment=env,requires=list(requires)))
        return name
    gates={}
    for variant in variants:
        gate=add(variant+'-gin',variant,'smoke','gin',dict(CXI_SMOKE_CONTEXTS='1,4,129',
                 CXI_SMOKE_RESET='1',CXI_SMOKE_SELF='1',CXI_SMOKE_NEGATIVE='1'),duration=1500)
        gate=add(variant+'-aggregate-wrap',variant,'burst','burst',{},[gate],duration=420)
        gate=add(variant+'-producer',variant,'producer','gin',
                 dict(CXI_PRODUCER_BLOCKS='1,2,8',CXI_PRODUCER_ROUNDS='128'),[gate],duration=600)
        gates[variant]=add(variant+'-ep-correctness',variant,'ep','ep',
            dict(settings,CXI_EP_TOKENS='257 4096',CXI_EP_ROUTING='mixed uniform hot_rank local remote',
                 CXI_EP_ITERS='3',CXI_EP_WARMUP='2',CXI_EP_NIC_ITERS='0'),[gate],duration=1500)
    gates['threshold']='01-threshold-gin'
    orders=[['threshold','batch1','batch8','batch32'],['batch32','batch8','batch1','threshold'],
            ['batch8','threshold','batch32','batch1']]
    for repeat,order in enumerate(orders,1):
        for variant in order:
            snap=REMOTE+'/sources/source-v1' if variant=='threshold' else source
            add(variant+'-aggregate-repeat'+str(repeat),variant,'ep','ep',settings,[gates[variant]],snapshot=snap)
    (out/'sequence.json').write_text(json.dumps(seq,indent=2)+'\n')
    manifest=json.loads((base/'manifest.json').read_text())
    manifest.update(scope='ABI v2 bounded AggregateRequests doorbells; per-PUT DC, locks, fences and completion preserved',
                    files={str(p.relative_to(out)):hashlib.sha256(p.read_bytes()).hexdigest()
                           for p in sorted(out.rglob('*')) if p.is_file() and p.name!='manifest.json'})
    (out/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n');print(out)


if __name__=='__main__':main()
