import argparse,hashlib,json,shutil,subprocess,tarfile,tempfile
from pathlib import Path
from prepare_trace import prepare_ep
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[3]
REMOTE='/iopsstor/scratch/cscs/zyu/deepep-async-20261030'
VARIANTS={'baseline':{},'async':{},'cap1':{'CXI_TX_PENDING_LIMIT':1},'cap2':{'CXI_TX_PENDING_LIMIT':2},'cap4':{'CXI_TX_PENDING_LIMIT':4},'cap8':{'CXI_TX_PENDING_LIMIT':8},'threshold':{'CXI_CT_THRESHOLD_FLUSH':1},'threshold-cap4':{'CXI_CT_THRESHOLD_FLUSH':1,'CXI_TX_PENDING_LIMIT':4}}
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    ap=argparse.ArgumentParser();ap.add_argument('output',type=Path);a=ap.parse_args();out=a.output.resolve();out.mkdir(parents=True,exist_ok=False)
    shutil.copytree(HERE,out/'runner',ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    shutil.copytree(ROOT/'tools/cxi_gin/backend',out/'backend',ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    for name in ['allocation_time.py','validate_gate.py','analyze_lifecycle.py']:
        shutil.copyfile(out/'backend/tools'/name,out/'runner'/name)
    for name in ['trace_capture.py','trace_format.py','device_trace.cuh','nvcc_wrapper.py','stamp.cu']:
        shutil.copyfile(HERE/name,out/'backend/tests'/name)
    (out/'backend/tests/nvcc_wrapper.py').chmod(0o755)
    for filename in ['direct_node.sh']:
        p=out/'backend/tools'/filename;t=p.read_text();old='export EP_JIT_CACHE_DIR="$root/tenhour/jit-direct-$SLURM_JOB_ID/node$SLURM_PROCID"';assert old in t
        # runtime_cxi.sh sources runtime.sh, which unconditionally overwrites
        # EP_JIT_CACHE_DIR. Set the attempt-private path AFTER that source.
        t=t.replace(old,'export EP_JIT_CACHE_DIR="$OUT/jit/node$SLURM_PROCID"')
        t=t.replace('export CASE_OUT=', '''export EP_JIT_NVCC_COMPILER="$helpers/nvcc_wrapper.py"
if [ "${CXI_DEVICE_TRACE:-0}" = 1 ]; then
  nvcc -std=c++17 -shared -Xcompiler=-fPIC -arch=sm_90 "$helpers/stamp.cu" -o "$base/stamp.so"
  export EP_TRACE_STAMP_SO="$base/stamp.so"
fi
export CASE_OUT=''')
        p.write_text(t)
    p=out/'backend/tests/ep_benchmark.py';t=p.read_text()
    t=t.replace('    # Cycle uses constant expert outputs:', '    combine_expected=expected.clone()\n    # Cycle uses constant expert outputs:')
    t=t.replace('    if args.profile_steps and seed==args.seeds[0]', '''    if os.getenv('CXI_DEVICE_TRACE')=='1':
        from trace_capture import capture as capture_device
        capture_device(b,funcs,args,out,case,ref,combine_expected,w)
    if args.profile_steps and seed==args.seeds[0]''')
    t=t.replace('    source=os.environ[\'UCCL_WORK\']', '''    if os.getenv('CXI_DEVICE_TRACE')=='1':
        from trace_capture import initialize
        initialize()
    source=os.environ['UCCL_WORK']''')
    p.write_text(t)
    shutil.copyfile(ROOT/'results/deepep_async_20261029/baseline-cxi_primitives.cuh',out/'baseline-cxi_primitives.cuh')
    repo=ROOT/'tools/cxi_gin/DeepEP-cxi-dev';head=subprocess.check_output(['git','-C',str(repo),'rev-parse','HEAD'],text=True).strip();assert head.startswith('bd1e1669')
    with tempfile.TemporaryDirectory() as tmp:
        ep=Path(tmp)/'ep';shutil.copytree(repo,ep,ignore=shutil.ignore_patterns('.git','build','__pycache__','*.pyc','*.so'))
        shutil.copytree(ROOT/'DeepEP/third-party/fmt',ep/'third-party/fmt',dirs_exist_ok=True,ignore=shutil.ignore_patterns('.git','build','__pycache__'))
        with tarfile.open(out/'DeepEP.tar.gz','w:gz') as f:f.add(ep,arcname='.')
        prepare_ep(ep)
        with tarfile.open(out/'DeepEP-trace.tar.gz','w:gz') as f:f.add(ep,arcname='.')
    (out/'variants.json').write_text(json.dumps(VARIANTS,indent=2)+'\n')
    source=REMOTE+'/sources/'+out.name;sequence=[]
    common=dict(CXI_EP_SMS='64',CXI_EP_CONTEXTS='129',CXI_EP_DEBUG='0',CXI_TRANSPORT='direct',CXI_QUEUE_INVENTORY='1')
    def add(label,variant,kind,qual,timeout=900,requires=None,**extra):
        name='%02d-%s'%(len(sequence)+1,label);env=dict(common,CXI_VARIANT=variant,CXI_TEST_KIND=kind,CXI_TEST_TIMEOUT=str(timeout-60));env.update(extra)
        sequence.append(dict(name=name,snapshot=source,node_script='runner/node.sh',qualification=qual,timeout_seconds=timeout,environment=env,requires=requires or []));return name
    smoke={};epg={}
    for variant in VARIANTS:
        gate=add(variant+'-gin',variant,'smoke','gin',1500,CXI_SMOKE_CONTEXTS='1,4,129',CXI_SMOKE_RESET='1',CXI_SMOKE_SELF='1',CXI_SMOKE_NEGATIVE='1')
        if variant!='baseline':
            gate=add(variant+'-burst',variant,'burst','burst',420,requires=[gate])
        if variant.startswith('threshold'):
            gate=add(variant+'-producers',variant,'producer','gin',600,requires=[gate],CXI_PRODUCER_BLOCKS='1,2,8',CXI_PRODUCER_ROUNDS='512')
        smoke[variant]=gate
    settings=dict(CXI_EP_MODELS='v4flash',CXI_EP_TOKENS='4096',CXI_EP_DTYPES='fp8',CXI_EP_ROUTING='mixed',CXI_EP_SEEDS='1',CXI_EP_WARMUP='10',CXI_EP_ITERS='50',CXI_EP_NIC_ITERS='600',CXI_EP_PROFILE_STEPS='0')
    for trial in range(2):
        variants=list(VARIANTS) if trial==0 else list(reversed(VARIANTS))
        for v in variants:
            epg[v]=add(v+'-v4-trial'+str(trial),v,'ep','ep',1200,requires=[smoke[v]],**settings)
    # Trace the baseline, prior candidate, bounded candidate and threshold change.
    for v in ['baseline','async','cap4','threshold']:
        gate=add(v+'-trace',v+'-trace','ep','ep_trace',1800,requires=[epg[v]],**dict(settings,CXI_DEVICE_TRACE='1',CXI_TRACE_CAPTURES='3',CXI_EP_NIC_ITERS='0',CXI_EP_ITERS='30',CXI_EP_PROFILE_STEPS='2'))
    for v in ['baseline','cap4','threshold','threshold-cap4']:
        add(v+'-geometries',v,'ep','ep',1500,requires=[epg[v]],**dict(settings,CXI_EP_MODELS='v4flash qwen3 minimax',CXI_EP_DTYPES='bf16 fp8',CXI_EP_NIC_ITERS='0',CXI_EP_ITERS='30'))
    (out/'sequence.json').write_text(json.dumps(sequence,indent=2)+'\n')
    m=dict(deepep_commit=head,scope='bounded command pacing and blocking CT threshold writeback; diagnostic traces separate',
      baseline_library_sha256='43126080b901ff199c20dce664aec5d39eda36c8785aac629c45de4a3b95f295',
      files={str(p.relative_to(out)):sha(p) for p in sorted(out.rglob('*')) if p.is_file()})
    (out/'manifest.json').write_text(json.dumps(m,indent=2)+'\n');print(out)
if __name__=='__main__':main()
