"""Stage immutable identical files by hardlink; replace only overlay files.

Never write through a parent hardlink. Every overlay member is written to a new
inode and atomically renamed, then both parent and candidate hashes are checked.
"""
import hashlib,json,os,shutil,sys,tarfile
from pathlib import Path

campaign=Path(__file__).resolve().parent
parent=campaign/'sources/source-first-call-debug-v1'
dest=campaign/'sources/source-local-io-v2'
overlay=campaign/'local-io-v2-overlay.tar.gz'
before=json.loads((parent/'manifest.json').read_text())
assert not dest.exists()
shutil.copytree(str(parent),str(dest),copy_function=os.link,
                ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
with tarfile.open(str(overlay)) as archive:
 for member in archive:
  name=Path(member.name)
  assert member.isfile() and not name.is_absolute() and '..' not in name.parts
  target=dest/name;target.parent.mkdir(parents=True,exist_ok=True)
  temp=target.with_name(target.name+'.overlay-tmp')
  with temp.open('xb') as f:f.write(archive.extractfile(member).read())
  os.chmod(str(temp),member.mode)
  temp.replace(target)
after=json.loads((dest/'manifest.json').read_text())
shared=[]
for root,manifest in [(parent,before),(dest,after)]:
 for name,digest in manifest['files'].items():
  assert hashlib.sha256((root/name).read_bytes()).hexdigest()==digest,(root,name)
for name,digest in after['files'].items():
 if before['files'].get(name)==digest:
  assert os.path.samefile(str(parent/name),str(dest/name)),name
  shared.append(name)
record=campaign/'local-io-v2-staging.json'
record.write_text(json.dumps(dict(status='PASS',parent=str(parent),destination=str(dest),
 shared_immutable_files=shared,parent_hashes_unchanged=True,
 scope='Storage/inode reuse only; no GPU/transport code modification'),indent=2)+'\n')
print('PASS immutable parent preserved; reused %d identical files'%len(shared))
