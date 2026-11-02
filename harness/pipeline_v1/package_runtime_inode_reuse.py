"""New immutable source namespace; all executable source bytes unchanged."""
import hashlib,json,shutil,tarfile
from pathlib import Path
from package import ROOT,REMOTE
p=ROOT/'results/deepep_pipeline_20261030';parent=p/'source-local-reports-v1';out=p/'source-local-runtime-v1'
shutil.copytree(parent,out,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
seq=json.loads((out/'sequence.json').read_text());names={g['name']:str(3500+i)+'-'+g['name'].split('-',1)[1] for i,g in enumerate(seq)}
for g in seq:
 g['name']=names[g['name']];g['snapshot']=REMOTE+'/sources/'+out.name;g['requires']=[names.get(x,x) for x in g['requires']]
(out/'sequence.json').write_text(json.dumps(seq,indent=2)+'\n')
old=json.loads((parent/'manifest.json').read_text());new={str(f.relative_to(out)):hashlib.sha256(f.read_bytes()).hexdigest() for f in out.rglob('*') if f.is_file() and f.name!='manifest.json'}
assert set(old['files'])==set(new)
assert {k for k in new if old['files'][k]!=new[k]}=={'sequence.json'}
old.update(files=new,source_parent=str(parent),scope='Byte-identical executable sources; new immutable runtime namespace reuses proven marker-zero inodes only for exactly matching runtime files')
(out/'manifest.json').write_text(json.dumps(old,indent=2)+'\n')
with tarfile.open(p/(out.name+'-overlay.tar.gz'),'w:gz') as t:
 for name in ['sequence.json','manifest.json']:t.add(out/name,arcname=name)
print('PASS executable source identity',out)
