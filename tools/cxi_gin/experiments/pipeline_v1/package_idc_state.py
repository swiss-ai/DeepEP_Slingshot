"""Isolated IDC state reuse experiment, based on qualified native fencing."""
import argparse
import hashlib
import json
import shutil
from pathlib import Path
from package import ROOT, REMOTE, replace
from prepare_idc_state import prepare


def main():
    parser=argparse.ArgumentParser();parser.add_argument('output',type=Path)
    out=parser.parse_args().output.resolve()
    base=ROOT/'results/deepep_pipeline_20261030/source-hw-fence-v3'
    ladder=ROOT/'results/deepep_pipeline_20261030/source-delivery-ladder-v1'
    shutil.copytree(base,out,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    prepare(out)
    for name in ['backend/tests/gin_stage_ladder.cu','backend/tests/gin_smoke.py',
                 'backend/tools/direct_node.sh','runner/validate_gate.py']:
        shutil.copyfile(ladder/name,out/name)
    shutil.copyfile(Path(__file__).with_name('test_idc_state.cc'),out/'runner/test_idc_state.cc')
    variants={name:dict(CXI_CACHE_IDC_STATE=cache,CXI_HW_SIGNAL_FENCE=1,
        CXI_BATCH_DELIVERY=1,CXI_CT_THRESHOLD_FLUSH=1,CXI_TX_BATCH_LIMIT=8)
        for name,cache in [('state-control',0),('state-cached',1)]}
    (out/'variants.json').write_text(json.dumps(variants,indent=2)+'\n')
    preflight=out/'runner/preflight.sh'
    replace(preflight,'for variant in fence-control fence-dc fence-batched; do',
            'for variant in state-control state-cached; do')
    replace(preflight,'for name in gin_smoke gin_producer_stress device_compile_probe; do',
            'for name in gin_smoke gin_producer_stress device_compile_probe gin_stage_ladder; do')
    replace(preflight,'for limit in 0 1; do\nfor hw_fence in 0 1; do',
            'for limit in 1; do\nfor cache in 0 1; do')
    replace(preflight,'-DCXI_HW_SIGNAL_FENCE="$hw_fence"',
            '-DCXI_HW_SIGNAL_FENCE=1 -DCXI_CACHE_IDC_STATE="$cache"')
    replace(preflight,'"$out/burst-$limit-fence$hw_fence.o"','"$out/burst-$limit-state$cache.o"')
    replace(preflight,'date -Is > "$out/PASS"','''g++ -std=c++17 -O2 -Wall -Wextra -Werror -I"$src/backend/device" -I"$src/backend/include" \
  "$src/runner/test_idc_state.cc" -o "$out/idc-state-test"
"$out/idc-state-test"
date -Is > "$out/PASS"''')
    seq=[]
    common=dict(CXI_EP_SMS='64',CXI_EP_CONTEXTS='129',CXI_EP_DEBUG='0',CXI_TRANSPORT='direct',
                CXI_QUEUE_INVENTORY='1',CXI_EP_UPDATE_INTERVAL='3',CXI_DEVICE_TRACE='0')
    settings=dict(CXI_EP_MODELS='v4flash',CXI_EP_TOKENS='4096 16384',CXI_EP_DTYPES='fp8',
        CXI_EP_ROUTING='mixed',CXI_EP_SEEDS='1',CXI_EP_WARMUP='20',CXI_EP_ITERS='100',
        CXI_EP_NIC_ITERS='600',CXI_EP_PROFILE_STEPS='0')
    def add(label,variant,kind,qualification,extra,requires,duration=1500):
        name='%03d-%s'%(900+len(seq),label)
        env=dict(common,CXI_VARIANT=variant,CXI_TEST_KIND=kind,CXI_TEST_TIMEOUT=str(duration-60));env.update(extra)
        seq.append(dict(name=name,snapshot=REMOTE+'/sources/'+out.name,node_script='runner/node.sh',
            qualification=qualification,timeout_seconds=duration,environment=env,requires=requires))
        return name
    # Fresh-allocation parent baseline must pass before either ABI5 arm.
    parents=['03-fence-batched-ep-correctness','04-fence-batched-repeat1',
             '05-fence-batched-repeat2','06-fence-batched-repeat3']
    gates={}
    for variant in variants:
        gate=add(variant+'-gin',variant,'smoke','gin',dict(CXI_SMOKE_CONTEXTS='1,4,129',
            CXI_SMOKE_ROUNDS='28',CXI_SMOKE_RESET='1',CXI_SMOKE_SELF='1',CXI_SMOKE_NEGATIVE='1'),parents)
        gate=add(variant+'-wrap',variant,'burst','burst',{},[gate],420)
        gate=add(variant+'-producers',variant,'producer','gin',
            dict(CXI_PRODUCER_BLOCKS='1,2,8',CXI_PRODUCER_ROUNDS='256'),[gate],900)
        gate=add(variant+'-ep-correctness',variant,'ep','ep',dict(settings,
            CXI_EP_TOKENS='257 4096',CXI_EP_DTYPES='fp8 bf16',
            CXI_EP_ROUTING='mixed uniform hot_rank local remote',CXI_EP_ITERS='3',
            CXI_EP_WARMUP='2',CXI_EP_NIC_ITERS='0'),[gate])
        gates[variant]=add(variant+'-sustained-16k',variant,'ep','ep',dict(settings,
            CXI_EP_TOKENS='16384',CXI_EP_ITERS='100',CXI_EP_NIC_ITERS='600'),[gate])
    for tokens in [4096,16384]:
        for label,interval,coalesce in [('coalesced',0,1),('rows-final',0,0),('signals3',3,0)]:
            for variant in variants:
                add(variant+'-'+label+'-'+str(tokens),variant,'ladder','ladder',
                    dict(CXI_LADDER_ROWS=str(tokens),CXI_LADDER_SIGNAL_INTERVAL=str(interval),
                         CXI_LADDER_COALESCE=str(coalesce),CXI_LADDER_CONTEXTS='129',CXI_LADDER_ROUNDS='30'),
                    [gates[variant]],1200)
    names=list(variants)
    for repeat,order in enumerate([names,list(reversed(names)),names],1):
        for variant in order:
            add(variant+'-repeat'+str(repeat),variant,'ep','ep',settings,[gates[variant]])
    known=set(parents)
    for spec in seq:
        assert set(spec['requires']) <= known
        assert spec['name'] not in known
        known.add(spec['name'])
    (out/'sequence.json').write_text(json.dumps(seq,indent=2)+'\n')
    manifest=json.loads((base/'manifest.json').read_text())
    manifest.update(source_parent=str(base),scope='ABI5 IDC state reuse only; native fencing/delivery batching unchanged; no cached TX credits',
        files={str(p.relative_to(out)):hashlib.sha256(p.read_bytes()).hexdigest()
               for p in sorted(out.rglob('*')) if p.is_file() and p.name!='manifest.json'})
    (out/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print(out)


if __name__=='__main__':main()
