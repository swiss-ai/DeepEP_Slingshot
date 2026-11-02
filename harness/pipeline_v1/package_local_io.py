"""Isolate shared-filesystem launch skew without changing communication code."""
import argparse, copy, hashlib, json, shutil, subprocess
from pathlib import Path
from package import ROOT, REMOTE, replace

p=argparse.ArgumentParser();p.add_argument('output',type=Path)
out=p.parse_args().output.resolve()
parent=ROOT/'results/deepep_pipeline_20261030/source-first-call-debug-v1'
shutil.copytree(parent,out,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
shutil.copyfile(Path(__file__).with_name('result_spool.py'),out/'backend/tests/result_spool.py')
replace(out/'backend/tests/common.py',"def record(path, obj):\n    with path.open('a') as f:",
"""def record(path, obj):
    if os.getenv('CXI_LOCAL_RESULTS') == '1':
        import result_spool
        return result_spool.record(path, obj)
    with path.open('a') as f:""")
b=out/'backend/tests/ep_benchmark.py'
replace(b,'    diagnostic_watch.finish()',
"""    if os.getenv('CXI_LOCAL_RESULTS') == '1':
        import result_spool
        result_spool.finish()
    diagnostic_watch.finish()""")
replace(b,'                            raise\n                        gc.collect()',
"""                            if os.getenv('CXI_LOCAL_RESULTS') == '1':
                                import result_spool
                                result_spool.finish()
                            raise
                        gc.collect()""")
replace(b,"torch=torch.__version__,cuda=torch.version.cuda,job=os.getenv('SLURM_JOB_ID'),",
"""torch=torch.__version__,cuda=torch.version.cuda,job=os.getenv('SLURM_JOB_ID'),
        host_io=dict(local_jit=os.getenv('CXI_LOCAL_JIT','0'),
                     local_results=os.getenv('CXI_LOCAL_RESULTS','0')),""")
node=out/'runner/node.sh'
replace(node,'export EP_JIT_CACHE_DIR="$OUT/jit/node$SLURM_PROCID"',
'''export EP_JIT_CACHE_DIR="$OUT/jit/node$SLURM_PROCID"
if [ "${CXI_LOCAL_JIT:-0}" = 1 ]; then
  export CXI_LOCAL_JIT_DIR=$(mktemp -d "/dev/shm/deepep-jit-${SLURM_JOB_ID}-n${SLURM_PROCID}-XXXXXX")
  export EP_JIT_CACHE_DIR="$CXI_LOCAL_JIT_DIR"
fi''')
replace(node,'bash "$SNAPSHOT/backend/tools/direct_node.sh"',
'''if bash "$SNAPSHOT/backend/tools/direct_node.sh"; then test_rc=0; else test_rc=$?; fi
if [ "${CXI_LOCAL_JIT:-0}" = 1 ]; then
  mkdir -p "$OUT/jit/node$SLURM_PROCID"
  cp -a "$CXI_LOCAL_JIT_DIR/." "$OUT/jit/node$SLURM_PROCID/"
  rm -rf -- "$CXI_LOCAL_JIT_DIR"
  export EP_JIT_CACHE_DIR="$OUT/jit/node$SLURM_PROCID"
fi
if [ "$test_rc" != 0 ]; then exit "$test_rc"; fi''')
replace(out/'backend/tools/direct_node.sh',
'export EP_JIT_CACHE_DIR="$OUT/jit/node$SLURM_PROCID"',
'export EP_JIT_CACHE_DIR="${CXI_LOCAL_JIT_DIR:-$OUT/jit/node$SLURM_PROCID}"')
base=json.loads((ROOT/'results/deepep_pipeline_20261030/first-call-full-matrix-v1-sequence.json').read_text())[0]
seq=[]
for number,jit,results,watch in [(2600,1,0,1),(2601,1,1,1),(2602,1,1,0),(2603,1,1,0)]:
 s=copy.deepcopy(base)
 s.update(name='%d-local-io-jit%d-results%d-watch%d'%(number,jit,results,watch),
          snapshot=REMOTE+'/sources/'+out.name,timeout_seconds=1200)
 s['environment'].update(CXI_LOCAL_JIT=str(jit),CXI_LOCAL_RESULTS=str(results),
                         CXI_DIAGNOSTIC_WATCHDOG=str(watch))
 s['requires']=['1803-retire-refresh-tiny-stress']
 seq.append(s)
(out/'sequence.json').write_text(json.dumps(seq,indent=2)+'\n')
old=json.loads((parent/'manifest.json').read_text())
new={str(f.relative_to(out)):hashlib.sha256(f.read_bytes()).hexdigest() for f in sorted(out.rglob('*')) if f.is_file() and f.name!='manifest.json'}
changed={k for k in old['files'] if old['files'][k]!=new[k]}
assert changed=={'backend/tests/common.py','backend/tests/ep_benchmark.py','backend/tools/direct_node.sh','runner/node.sh','sequence.json'},changed
assert set(new)-set(old['files'])=={'backend/tests/result_spool.py'}
old.update(files=new,source_parent=str(parent),scope='Host JIT/result storage isolation only; GPU/host transport/native/runtime bytes unchanged; no network progress helper')
(out/'manifest.json').write_text(json.dumps(old,indent=2)+'\n')
for f in [out/'backend/tests/common.py',b,out/'backend/tests/result_spool.py']:compile(f.read_text(),str(f),'exec')
for f in [node,out/'backend/tools/direct_node.sh']:subprocess.check_call(['bash','-n',str(f)])
print('PASS host storage source delta and syntax; GPU validation pending')
