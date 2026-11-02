"""Matched three-repeat size sweep; reuse qualified transport, change harness only."""
import argparse,hashlib,json,shutil
from pathlib import Path
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[3]
REMOTE='/iopsstor/scratch/cscs/zyu/deepep-size-sweep-20261030'
ORDERS=[list(range(2048,16385,2048)),list(range(16384,2047,-2048)),[8192,2048,14336,6144,16384,4096,12288,10240]]
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
 ap=argparse.ArgumentParser();ap.add_argument('output',type=Path);a=ap.parse_args();out=a.output.resolve()
 base=ROOT/'results/deepep_async_20261030/source-v6'
 shutil.copytree(base,out,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
 (out/'DeepEP-trace.tar.gz').unlink()
 # Transport sources and DeepEP ordinary archive are byte-identical to qualified v6.
 p=out/'backend/tests/ep_benchmark.py';s=p.read_text()
 s=s.replace("        if ep==8 and seed==args.seeds[0] and n==4096 and args.nic_iters:","        if ep==8 and seed==args.seeds[0] and args.nic_iters:")
 s=s.replace('    owners=idx//(e//ep)', '''    # Match TokenLayout: independent 32-byte alignment of hidden, scale and
    # metadata components, excluding mbarrier (not transferred via GIN put).
    align32=lambda z:((z+31)//32)*32
    sf_bytes=raw[1].shape[1]*raw[1].element_size() if isinstance(raw,tuple) else 0
    hidden_bytes=h*(raw[0].element_size() if isinstance(raw,tuple) else raw.element_size())
    case['dispatch_row_bytes']=align32(hidden_bytes)+align32(sf_bytes)+align32(8*k+4*(1+k))
    case['combine_row_bytes']=align32(h*2)+align32(8*k)
    case['repeat']=int(os.environ['CXI_SWEEP_REPEAT'])
    case['nic_all_token_sizes']=True
    owners=idx//(e//ep)''')
 s=s.replace("            nic_window(fn,args,out,case|dict(operation=op))", """            # Choose one shared iteration count for all ranks, targeting >=2.5s
            # so NIC telemetry's coarse update period has multiple observations.
            cost=torch.tensor(float(np.median(samples['cuda_event_us'])),device='cuda')
            dist.all_reduce(cost,op=dist.ReduceOp.MAX)
            nic_args=argparse.Namespace(**vars(args))
            nic_args.nic_iters=max(args.nic_iters,int(np.ceil(2500000/max(cost.item(),1))))
            nic_window(fn,nic_args,out,case|dict(operation=op))""")
 p.write_text(s)
 p=out/'backend/tests/summarize.py';s=p.read_text().replace("if ep==8 and args['nic_iters'] and 4096 in args['tokens']:","if ep==8 and args['nic_iters']:")
 s=s.replace("len(args['routing'])*4","len(args['routing'])*len(args['tokens'])*4");p.write_text(s)
 p=out/'runner/monitor.py';p.write_text(p.read_text().replace('deepep-async-20261030','deepep-size-sweep-20261030'))
 p=out/'runner/run.sbatch';s=p.read_text().replace('deepep-async-20261030','deepep-size-sweep-20261030').replace('--time=04:00:00','--time=02:00:00').replace('deepep-cxi-waits-v2','deepep-fp8-size-sweep');p.write_text(s)
 # Auto-exit after success; retain allocation on failure for bounded debugging.
 p=out/'runner/controller.py';s=p.read_text();needle="        if not requests:\n            status('IDLE_FOR_DEBUG',remaining_seconds=remaining)"
 assert needle in s
 s=s.replace(needle,"""        if not requests:
            if (snapshot/'SWEEP_CAMPAIGN').exists():
                status('SWEEP_COMPLETE')
                break
            status('IDLE_FOR_DEBUG',remaining_seconds=remaining)""")
 p.write_text(s)
 (out/'SWEEP_CAMPAIGN').write_text('Release after all three complete sweeps; keep failure window for debugging.\n')
 for name in ['analyze.py','postprocess.py']:
  shutil.copyfile(HERE/name,out/'runner'/('sweep_'+name))
 # Retained monitor invokes analysis after successful completion using local Python.
 p=out/'runner/monitor.py';s=p.read_text().replace('import argparse,datetime,json,subprocess,time','import argparse,datetime,json,subprocess,time,sys')
 s=s.replace('        if terminal: break',"""        if terminal:
            subprocess.run([sys.executable,str(Path(__file__).with_name('sweep_postprocess.py')),str(a.output)],check=True,timeout=180)
            break""")
 p.write_text(s)
 common=dict(CXI_EP_SMS='64',CXI_EP_CONTEXTS='129',CXI_EP_DEBUG='0',CXI_TRANSPORT='direct',CXI_QUEUE_INVENTORY='1',CXI_VARIANT='threshold')
 seq=[]
 def add(name,kind,qual,duration,env,requires):
  seq.append(dict(name=name,snapshot=REMOTE+'/sources/'+out.name,node_script='runner/node.sh',qualification=qual,timeout_seconds=duration,environment=dict(common,CXI_TEST_KIND=kind,CXI_TEST_TIMEOUT=str(duration-60),**env),requires=requires))
 add('01-threshold-gin','smoke','gin',1200,dict(CXI_SMOKE_CONTEXTS='1,4,129',CXI_SMOKE_RESET='1',CXI_SMOKE_SELF='1',CXI_SMOKE_NEGATIVE='1'),[])
 for trial,order in enumerate(ORDERS,1):
  env=dict(CXI_EP_MODELS='v4flash',CXI_EP_TOKENS=' '.join(map(str,order)),CXI_EP_DTYPES='fp8',CXI_EP_ROUTING='mixed',CXI_EP_SEEDS='1',CXI_EP_WARMUP='20',CXI_EP_ITERS='100',CXI_EP_NIC_ITERS='600',CXI_EP_PROFILE_STEPS='0',CXI_DEVICE_TRACE='0',CXI_SWEEP_REPEAT=str(trial))
  add('%02d-size-sweep-repeat%d'%(trial+1,trial),'ep','ep',1500,env,['01-threshold-gin'])
 (out/'sequence.json').write_text(json.dumps(seq,indent=2)+'\n')
 (out/'variants.json').write_text(json.dumps({'threshold':{'CXI_CT_THRESHOLD_FLUSH':1}},indent=2)+'\n')
 m=dict(deepep_commit=json.loads((base/'manifest.json').read_text())['deepep_commit'],scope='V4 Flash EP8 FP8 size sweep, three repeats; unchanged threshold transport',source_baseline=str(base),source_baseline_manifest_sha256=sha(base/'manifest.json'),files={str(p.relative_to(out)):sha(p) for p in sorted(out.rglob('*')) if p.is_file() and p.name!='manifest.json'})
 (out/'manifest.json').write_text(json.dumps(m,indent=2)+'\n');print(out)
if __name__=='__main__':main()
