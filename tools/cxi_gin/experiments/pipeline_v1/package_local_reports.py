"""Persist reports directly from the live local JIT cache after GPU execution."""
import argparse,hashlib,json,shutil,subprocess,tarfile
from pathlib import Path
from package import ROOT,REMOTE,replace
p=argparse.ArgumentParser();p.add_argument('parent');p.add_argument('name');p.add_argument('--gate-base',type=int,required=True)
a=p.parse_args();assert all(Path(x).name==x for x in [a.parent,a.name])
campaign=ROOT/'results/deepep_pipeline_20261030';parent=campaign/a.parent;out=campaign/a.name
shutil.copytree(parent,out,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
node=out/'runner/node.sh'
old='''mkdir -p "$OUT/compiler-reports/node$SLURM_PROCID"
find "$EP_JIT_CACHE_DIR" -path '*/compiler-reports/*.txt' -exec cp {} "$OUT/compiler-reports/node$SLURM_PROCID/" \\;
'''
replace(node,old,'')
anchor='if bash "$SNAPSHOT/backend/tools/direct_node.sh"; then test_rc=0; else test_rc=$?; fi\n'
replace(node,anchor,anchor+'''if [ "$test_rc" = 0 ]; then
  mkdir -p "$OUT/compiler-reports/node$SLURM_PROCID"
  # EP_JIT_CACHE_DIR still points to tmpfs when local JIT is enabled. Avoid
  # rereading a newly written Lustre copy, and fail on a batched copy error.
  find "$EP_JIT_CACHE_DIR" -path '*/compiler-reports/*.txt' \
    -exec cp --no-preserve=all -t "$OUT/compiler-reports/node$SLURM_PROCID/" {} +
fi
''')
seq=json.loads((out/'sequence.json').read_text());names={g['name']:str(a.gate_base+i)+'-'+g['name'].split('-',1)[1] for i,g in enumerate(seq)}
for g in seq:
 g['name']=names[g['name']];g['snapshot']=REMOTE+'/sources/'+a.name;g['requires']=[names.get(x,x) for x in g['requires']]
(out/'sequence.json').write_text(json.dumps(seq,indent=2)+'\n')
old=json.loads((parent/'manifest.json').read_text());new={str(f.relative_to(out)):hashlib.sha256(f.read_bytes()).hexdigest() for f in out.rglob('*') if f.is_file() and f.name!='manifest.json'}
assert set(old['files'])==set(new)
assert {k for k in new if old['files'][k]!=new[k]}=={'runner/node.sh','sequence.json'}
old.update(files=new,source_parent=str(parent),scope='Post-GPU compiler report persistence only; read original local cache instead of fresh Lustre copy; GPU, transport, runtime, timing and compiled inputs unchanged')
(out/'manifest.json').write_text(json.dumps(old,indent=2)+'\n');subprocess.check_call(['bash','-n',str(node)])
with tarfile.open(campaign/(a.name+'-overlay.tar.gz'),'w:gz') as t:
 for name in ['runner/node.sh','sequence.json','manifest.json']:t.add(out/name,arcname=name)
print('PASS exact post-GPU report-copy source delta',out)
