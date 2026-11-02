"""Reuse identical immutable parent inodes before a snapshot's first preflight.

No file contents or manifests change. Refuse snapshots with runtime/build inputs
already installed; this is staging preparation, not a running-job modification.
"""
import hashlib,json,os,sys
from pathlib import Path

campaign=Path(__file__).resolve().parent
name,parent_name=sys.argv[1:]
assert Path(name).name==name and Path(parent_name).name==parent_name and name!=parent_name
source=campaign/'sources'/name;parent=campaign/'sources'/parent_name
assert not (campaign/'preflight'/name).exists()
assert not (campaign/'runtime'/name).exists()
assert not any((campaign/'jobs').glob('*/builds/'+name))
old=json.loads((parent/'manifest.json').read_text())['files']
new=json.loads((source/'manifest.json').read_text())['files']
reused=[]
for relative,digest in new.items():
 target=source/relative
 assert hashlib.sha256(target.read_bytes()).hexdigest()==digest,(source,relative)
 if old.get(relative)!=digest:continue
 canonical=parent/relative
 assert hashlib.sha256(canonical.read_bytes()).hexdigest()==digest,(parent,relative)
 if not os.path.samefile(str(target),str(canonical)):
  temp=target.with_name(target.name+'.immutable-link-tmp')
  os.link(str(canonical),str(temp));temp.replace(target)
 assert os.path.samefile(str(target),str(canonical))
 reused.append(relative)
(campaign/(name+'-inode-reuse.json')).write_text(json.dumps(dict(status='PASS',
 source=name,parent=parent_name,reused_files=reused,contents_and_manifests_unchanged=True),indent=2)+'\n')
print('PASS reused %d immutable input files without content changes'%len(reused))
