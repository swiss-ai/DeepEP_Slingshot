import argparse,hashlib,json,shutil,subprocess,tarfile,tempfile
from pathlib import Path
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[3]
REMOTE='/iopsstor/scratch/cscs/zyu/deepep-async-20261029'
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    parser=argparse.ArgumentParser();parser.add_argument('output',type=Path);a=parser.parse_args()
    out=a.output.resolve();out.mkdir(parents=True,exist_ok=False)
    shutil.copytree(HERE,out/'runner',ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    backend=ROOT/'tools/cxi_gin/backend'
    shutil.copytree(backend,out/'backend',ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    for name in ['allocation_time.py','validate_gate.py','analyze_lifecycle.py']:
        shutil.copyfile(backend/'tools'/name,out/'runner'/name)
    # Isolate JIT products by attempt; never use the old campaign's cache.
    node=out/'backend/tools/direct_node.sh'; s=node.read_text()
    old='export EP_JIT_CACHE_DIR="$root/tenhour/jit-direct-$SLURM_JOB_ID/node$SLURM_PROCID"'
    assert old in s
    node.write_text(s.replace(old,'export EP_JIT_CACHE_DIR="${EP_JIT_CACHE_DIR:-$OUT/jit/node$SLURM_PROCID}"'))
    shutil.copyfile(ROOT/'results/deepep_async_20261029/baseline-cxi_primitives.cuh',out/'baseline-cxi_primitives.cuh')
    repo=ROOT/'tools/cxi_gin/DeepEP-cxi-dev'
    head=subprocess.check_output(['git','-C',str(repo),'rev-parse','HEAD'],text=True).strip()
    assert head.startswith('bd1e1669')
    with tempfile.TemporaryDirectory() as tmp:
        ep=Path(tmp)/'ep'
        shutil.copytree(repo,ep,ignore=shutil.ignore_patterns('.git','build','__pycache__','*.pyc','*.so'))
        shutil.copytree(ROOT/'DeepEP/third-party/fmt',ep/'third-party/fmt',dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns('.git','build','__pycache__'))
        assert (ep/'third-party/fmt/include/fmt/format.h').is_file()
        with tarfile.open(out/'DeepEP.tar.gz','w:gz') as t:t.add(ep,arcname='.')
    source=REMOTE+'/sources/'+out.name; sequence=[]
    common={'CXI_EP_SMS':'64','CXI_EP_CONTEXTS':'129','CXI_EP_DEBUG':'0','CXI_TRANSPORT':'direct'}
    def add(name,variant,kind,qualification,timeout=600,**extra):
        env=dict(common,CXI_VARIANT=variant,CXI_TEST_KIND=kind,CXI_TEST_TIMEOUT=str(timeout-60))
        env.update(extra)
        sequence.append(dict(name=name,snapshot=source,node_script='runner/node.sh',qualification=qualification,
                             timeout_seconds=timeout,environment=env,requires=[sequence[-1]['name']] if sequence else []))
    add('01-baseline-public-gin','baseline','smoke','gin',1500,CXI_SMOKE_CONTEXTS='1,4,129',CXI_SMOKE_RESET='1',CXI_SMOKE_SELF='1')
    add('02-async-burst-wrap','async','burst','burst',420)
    add('03-async-public-gin','async','smoke','gin',1500,CXI_SMOKE_CONTEXTS='1,4,129',CXI_SMOKE_RESET='1',CXI_SMOKE_SELF='1',CXI_SMOKE_NEGATIVE='1')
    add('04-async-bounds','async','bounds','gin',420)
    add('05-async-producers','async','producer','gin',900,CXI_PRODUCER_BLOCKS='1,2,8',CXI_PRODUCER_ROUNDS='512')
    ep=dict(CXI_EP_MODELS='v4flash',CXI_EP_TOKENS='128 512',CXI_EP_DTYPES='bf16 fp8',CXI_EP_ROUTING='mixed',
            CXI_EP_SEEDS='1',CXI_EP_WARMUP='5',CXI_EP_ITERS='30',CXI_EP_NIC_ITERS='0',CXI_EP_PROFILE_STEPS='0')
    add('06-async-ep-small','async','ep','ep',900,**ep)
    ep.update(CXI_EP_TOKENS='4096',CXI_EP_DTYPES='fp8')
    for trial in range(3):
        for variant in (['baseline','async'] if trial%2==0 else ['async','baseline']):
            add('%02d-%s-v4flash-trial%d'%(len(sequence)+1,variant,trial),variant,'ep','ep',900,**ep)
    ep.update(CXI_EP_MODELS='v4flash qwen3 minimax',CXI_EP_DTYPES='bf16 fp8')
    for variant in ['baseline','async']:
        add('%02d-%s-three-geometries'%(len(sequence)+1,variant),variant,'ep','ep',1500,**ep)
    ep.update(CXI_EP_MODELS='v4flash',CXI_EP_TOKENS='512',CXI_EP_ROUTING='hot_rank',CXI_EP_ITERS='5')
    add('15-async-empty-receivers','async','ep','ep',900,**ep)
    add('16-async-sglang-dispatcher','async','sglang','sglang',1500,CXI_SGLANG_MODEL='v4flash',
        CXI_SGLANG_DTYPES='fp8',CXI_SGLANG_TOKENS='32,4096',CXI_SGLANG_ROUNDS='3',CXI_SGLANG_WARMUP='1',
        CXI_SGLANG_EXACT_REFERENCE='1',CXI_SGLANG_PERMUTE='1')
    (out/'sequence.json').write_text(json.dumps(sequence,indent=2)+'\n')
    m=dict(deepep_commit=head,scope='unqualified bounded asynchronous TX; unchanged signal/completion semantics',
           baseline_library_sha256='43126080b901ff199c20dce664aec5d39eda36c8785aac629c45de4a3b95f295',
           files={str(p.relative_to(out)):sha(p) for p in sorted(out.rglob('*')) if p.is_file()})
    (out/'manifest.json').write_text(json.dumps(m,indent=2)+'\n');print(out)
if __name__=='__main__':main()
