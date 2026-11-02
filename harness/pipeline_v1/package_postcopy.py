"""Change only post-GPU artifact-copy metadata behavior in immutable snapshots."""
import argparse,hashlib,json,shutil,subprocess,tarfile
from pathlib import Path
from package import ROOT,REMOTE,replace

p=argparse.ArgumentParser();p.add_argument('parent');p.add_argument('name');p.add_argument('--gate-base',type=int,required=True)
a=p.parse_args();assert all(Path(x).name==x for x in [a.parent,a.name])
campaign=ROOT/'results/deepep_pipeline_20261030';parent=campaign/a.parent;out=campaign/a.name
shutil.copytree(parent,out,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
replace(out/'runner/node.sh','  cp -a "$CXI_LOCAL_JIT_DIR/." "$OUT/jit/node$SLURM_PROCID/"',
        '  cp -r --no-preserve=all "$CXI_LOCAL_JIT_DIR/." "$OUT/jit/node$SLURM_PROCID/"')
seq=json.loads((out/'sequence.json').read_text());names={g['name']:str(a.gate_base+i)+'-'+g['name'].split('-',1)[1] for i,g in enumerate(seq)}
for g in seq:
 g['name']=names[g['name']];g['snapshot']=REMOTE+'/sources/'+a.name
 g['requires']=[names.get(x,x) for x in g['requires']]
(out/'sequence.json').write_text(json.dumps(seq,indent=2)+'\n')
old=json.loads((parent/'manifest.json').read_text());new={str(p.relative_to(out)):hashlib.sha256(p.read_bytes()).hexdigest() for p in out.rglob('*') if p.is_file() and p.name!='manifest.json'}
assert set(old['files'])==set(new)
assert {k for k in new if old['files'][k]!=new[k]}=={'runner/node.sh','sequence.json'}
old.update(files=new,source_parent=str(parent),scope='Post-GPU artifact copy only: retain contents/reports, omit unnecessary metadata preservation; GPU/transport/timing/runtime unchanged')
(out/'manifest.json').write_text(json.dumps(old,indent=2)+'\n')
subprocess.check_call(['bash','-n',str(out/'runner/node.sh')])
with tarfile.open(campaign/(a.name+'-overlay.tar.gz'),'w:gz') as t:
 for name in ['runner/node.sh','sequence.json','manifest.json']:t.add(out/name,arcname=name)
print('PASS exact post-execution copy-only source delta',out)
