"""Prepare final geometry, scaling and SGLang checks for a measured candidate.

Does not submit or select a winner. Requires three qualified ordinary repeats
for the exact snapshot/variant/context/progress configuration. Keep geometry
correctness matrices in separate processes to bound CT resource lifetime.
"""
import argparse
import hashlib
import json
import re
from pathlib import Path


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('job',type=Path)
    parser.add_argument('snapshot',type=Path)
    parser.add_argument('variant')
    parser.add_argument('output',type=Path)
    parser.add_argument('--prefix',default='70')
    parser.add_argument('--contexts',type=int,default=129)
    parser.add_argument('--interval',type=int,default=3)
    parser.add_argument('--experiment',help='Exact experiment family when one variant has multiple matched arms')
    args=parser.parse_args()
    assert re.fullmatch('[0-9a-z]+',args.prefix)
    assert not args.output.exists(),'Use a new immutable request directory'
    manifest=json.loads((args.snapshot/'manifest.json').read_text())
    for name,digest in manifest['files'].items():
        assert hashlib.sha256((args.snapshot/name).read_bytes()).hexdigest()==digest,name
    assert args.variant in json.loads((args.snapshot/'variants.json').read_text())
    gates={};selected_settings=None;families=set()
    for finished in (args.job/'results/results').glob('*/FINISHED.json'):
        record=json.loads(finished.read_text());spec=record['spec'];env=spec['environment']
        repeat=re.search(r'-repeat([123])$',spec['name'])
        if not repeat or Path(spec['snapshot']).name!=args.snapshot.name or env.get('CXI_VARIANT')!=args.variant:continue
        family=re.sub(r'^[0-9][0-9a-z]*-', '', re.sub(r'-repeat[123]$', '', spec['name']))
        if args.experiment is not None and family!=args.experiment:continue
        if int(env.get('CXI_EP_CONTEXTS','0'))!=args.contexts or int(env.get('CXI_EP_UPDATE_INTERVAL','3'))!=args.interval:continue
        assert spec['qualification']=='ep' and env.get('CXI_TRANSPORT')=='direct'
        assert env.get('CXI_DEVICE_TRACE','0')=='0'
        assert record.get('returncode')==0 and record.get('qualification',{}).get('status')=='PASS',finished
        families.add(family)
        assert len(families)==1,'Multiple experiment arms; select one with --experiment'
        assert int(repeat[1]) not in gates,'Duplicate repeat within selected experiment'
        settings={k:env[k] for k in ('CXI_EP_SMS','CXI_EP_PACK_ROWS','CXI_EP_MERGE_FINAL_TAIL','CXI_TX_CQ_POLICY','CXI_EP_FORWARD_CHUNK',
                                    'CXI_LOCAL_JIT','CXI_LOCAL_RESULTS','CXI_LOCAL_LOGS',
                                    'CXI_DIAGNOSTIC_WATCHDOG') if k in env}
        assert env.get('CXI_DIAGNOSTIC_WATCHDOG','0')=='0','Diagnostic observer cannot qualify ordinary release repeats'
        assert int(env.get('CXI_EP_DROP_EVERY','0'))==0,'Dropped-token diagnostics cannot qualify ordinary serving'
        if selected_settings is None:selected_settings=settings
        assert settings==selected_settings,'Candidate settings differ across repeats'
        reports=list((finished.parent/'compiler-reports').rglob('*.txt'))
        assert reports and all('-DCXI_EP_UPDATE_INTERVAL=%d '%args.interval in p.read_text() for p in reports)
        gates[int(repeat[1])]=spec['name']
    assert set(gates)=={1,2,3},'Three qualified ordinary repeats required'
    source='/iopsstor/scratch/cscs/zyu/deepep-pipeline-20261030/sources/'+args.snapshot.name
    common=dict(CXI_VARIANT=args.variant,CXI_TRANSPORT='direct',CXI_EP_SMS='64',
                CXI_EP_CONTEXTS=str(args.contexts),CXI_EP_UPDATE_INTERVAL=str(args.interval),
                CXI_EP_DEBUG='0',CXI_DEVICE_TRACE='0',CXI_QUEUE_INVENTORY='1',CXI_EP_DROP_EVERY='0')
    common.update(selected_settings)
    settings=dict(CXI_EP_MODELS='v4flash',CXI_EP_DTYPES='fp8',CXI_EP_TOKENS='4096 16384',
                  CXI_EP_ROUTING='mixed',CXI_EP_SEEDS='1',CXI_EP_WARMUP='20',CXI_EP_ITERS='100',
                  CXI_EP_NIC_ITERS='600',CXI_EP_PROFILE_STEPS='0')
    requests=[]
    def add(label,kind,env,requires,duration=1500):
        name='%s%02d-%s-%s'%(args.prefix,len(requests),args.variant,label)
        environment=dict(common,CXI_TEST_KIND=kind,CXI_TEST_TIMEOUT=str(duration-60));environment.update(env)
        requests.append(dict(name=name,snapshot=source,node_script='runner/node.sh',qualification=kind,
                             timeout_seconds=duration,environment=environment,requires=requires))
        return name
    correctness={}
    for model in ['v4flash','qwen3','minimax']:
        correctness[model]=[]
        for dtype in ['fp8','bf16']:
            gate=add(model+'-'+dtype+'-correctness','ep',dict(settings,CXI_EP_MODELS=model,
                CXI_EP_DTYPES=dtype,CXI_EP_TOKENS='257 4096 16384',
                CXI_EP_ROUTING='mixed uniform hot_rank local remote',CXI_EP_SEEDS='17',
                CXI_EP_WARMUP='2',CXI_EP_ITERS='3',CXI_EP_NIC_ITERS='0'),list(gates.values()))
            correctness[model].append(gate)
    models=['v4flash','qwen3','minimax']
    for repeat,order in enumerate([models,list(reversed(models)),models[1:]+models[:1]],1):
        for model in order:
            add(model+'-geometry-repeat'+str(repeat),'ep',dict(settings,CXI_EP_MODELS=model),correctness[model])
    size_orders = [list(range(2048,16385,2048)),list(range(16384,2047,-2048)),
                   [8192,2048,14336,6144,16384,4096,12288,10240]]
    for repeat, order in enumerate(size_orders,1):
        add('v4flash-size-sweep-repeat'+str(repeat),'ep',dict(settings,
            CXI_EP_TOKENS=' '.join(map(str,order)),CXI_EP_NIC_ITERS='0'),
            correctness['v4flash'],1800)
    for model in models:
        env=dict(CXI_SGLANG_MODEL=model,CXI_SGLANG_DTYPES='bf16,fp8',CXI_SGLANG_TOKENS='32,4096',
                 CXI_SGLANG_ROUNDS='3',CXI_SGLANG_WARMUP='1',CXI_SGLANG_EXACT_REFERENCE='1',
                 CXI_SGLANG_IMPORT_AFTER_INIT='1',CXI_SGLANG_PERMUTE='1',CXI_SGLANG_GEMM='0')
        gate=add(model+'-sglang-scatter-gather','sglang',env,correctness[model],1800)
        add(model+'-sglang-expert-smoke','sglang',dict(env,CXI_SGLANG_GEMM='1'),[gate],1800)
    args.output.mkdir(parents=True)
    for spec in requests:
        (args.output/(spec['name']+'.json')).write_text(json.dumps(spec,indent=2)+'\n')
    inventory=dict(snapshot=args.snapshot.name,variant=args.variant,experiment=next(iter(families)),
                   preserved_settings=selected_settings,prerequisite_repeats=gates,
                   scope='Prepared only; exact payload/routing tests, ordinary geometry/size repeats, actual SGLang adapter/expert smoke. Reduced expert FFN width is not full serving qualification.',
                   requests=requests)
    (args.output/'inventory.json').write_text(json.dumps(inventory,indent=2)+'\n')
    print('Prepared %d gates; not submitted: %s'%(len(requests),args.output))


if __name__=='__main__':main()
