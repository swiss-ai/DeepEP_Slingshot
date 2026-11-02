"""Keep runtime stderr/stdout off Lustre without changing any transport code."""
import argparse,hashlib,json,shutil,subprocess,tarfile
from pathlib import Path
from package import ROOT,REMOTE,replace

p=argparse.ArgumentParser();p.add_argument('parent');p.add_argument('name');p.add_argument('--gate-base',type=int,required=True)
a=p.parse_args();assert all(Path(x).name==x for x in [a.parent,a.name])
campaign=ROOT/'results/deepep_pipeline_20261030';parent=campaign/a.parent;out=campaign/a.name
shutil.copytree(parent,out,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
script=out/'backend/tools/direct_node.sh'
replace(script,'timeout --signal=TERM --kill-after=10s "${CXI_TEST_TIMEOUT:-180}s" python -m torch.distributed.run',
'''runtime_log="$base/smoke.log"
if [ "${CXI_LOCAL_LOGS:-0}" = 1 ]; then
  runtime_log=$(mktemp "/dev/shm/deepep-log-${SLURM_JOB_ID}-n${SLURM_PROCID}-XXXXXX")
  printf '%s\\n' "$runtime_log" > "$base/local-log-path.txt"
fi
if timeout --signal=TERM --kill-after=10s "${CXI_TEST_TIMEOUT:-180}s" python -m torch.distributed.run''')
replace(script,'  > "$base/smoke.log" 2>&1\ndate -u +%FT%TZ > "$base/PASS"',
'''  > "$runtime_log" 2>&1; then test_rc=0; else test_rc=$?; fi
if [ "${CXI_LOCAL_LOGS:-0}" = 1 ]; then
  # GPU work is over before persistence; a failed copy preserves the local log.
  cp --no-preserve=all "$runtime_log" "$base/smoke.log"
  rm -- "$runtime_log"
fi
if [ "$test_rc" != 0 ]; then exit "$test_rc"; fi
date -u +%FT%TZ > "$base/PASS"''')
replace(out/'backend/tests/ep_benchmark.py',"host_io=dict(local_jit=os.getenv('CXI_LOCAL_JIT','0'),",
        "host_io=dict(local_logs=os.getenv('CXI_LOCAL_LOGS','0'),local_jit=os.getenv('CXI_LOCAL_JIT','0'),")
seq=json.loads((out/'sequence.json').read_text());names={g['name']:str(a.gate_base+i)+'-'+g['name'].split('-',1)[1] for i,g in enumerate(seq)}
for g in seq:
 g['name']=names[g['name']];g['snapshot']=REMOTE+'/sources/'+a.name
 g['requires']=[names.get(x,x) for x in g['requires']]
 g['environment']['CXI_LOCAL_LOGS']='1'
(out/'sequence.json').write_text(json.dumps(seq,indent=2)+'\n')
old=json.loads((parent/'manifest.json').read_text());new={str(p.relative_to(out)):hashlib.sha256(p.read_bytes()).hexdigest() for p in out.rglob('*') if p.is_file() and p.name!='manifest.json'}
assert set(old['files'])==set(new)
changed={'backend/tools/direct_node.sh','backend/tests/ep_benchmark.py','sequence.json'}
assert {k for k in new if old['files'][k]!=new[k]}==changed
old.update(files=new,source_parent=str(parent),scope='Runtime stdout/stderr goes to node-local tmpfs, persisted after GPU process exits; all GPU/transport/runtime/native inputs unchanged')
(out/'manifest.json').write_text(json.dumps(old,indent=2)+'\n')
subprocess.check_call(['bash','-n',str(script)])
compile((out/'backend/tests/ep_benchmark.py').read_text(),'ep_benchmark.py','exec')
with tarfile.open(campaign/(a.name+'-overlay.tar.gz'),'w:gz') as t:
 for name in sorted(changed|{'manifest.json'}):t.add(out/name,arcname=name)
print('PASS exact local-logging-only source delta',out)
