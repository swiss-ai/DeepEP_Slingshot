"""Stage unchanged packed source with previously verified delivery runtimes."""
import hashlib,json,os,shutil,sys,tarfile
from pathlib import Path
name,parent_name,runtime_parent_name=sys.argv[1:]
assert all(Path(x).name==x for x in [name,parent_name,runtime_parent_name])
campaign=Path(__file__).resolve().parent;parent=campaign/'sources'/parent_name;source=campaign/'sources'/name
assert not source.exists()
shutil.copytree(str(parent),str(source),copy_function=os.link,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
with tarfile.open(str(campaign/(name+'-overlay.tar.gz'))) as archive:
 for m in archive:
  assert m.isfile() and m.name in ['variants.json','sequence.json','manifest.json']
  dest=source/m.name;temp=dest.with_name(dest.name+'.overlay-tmp')
  temp.write_bytes(archive.extractfile(m).read());temp.replace(dest)
before=json.loads((parent/'manifest.json').read_text());after=json.loads((source/'manifest.json').read_text())
assert set(before['files'])==set(after['files'])
assert {k for k in before['files'] if before['files'][k]!=after['files'][k]}=={'variants.json','sequence.json'}
for root,manifest in [(parent,before),(source,after)]:
 for name,digest in manifest['files'].items():assert hashlib.sha256((root/name).read_bytes()).hexdigest()==digest,(root,name)
runtime=campaign/'runtime'/source.name;runtime.mkdir()
variants=json.loads((source/'variants.json').read_text())
for variant,defines in variants.items():
 old=campaign/'runtime'/runtime_parent_name/variant
 manifest=json.loads((old/'runtime-manifest.json').read_text());assert manifest['defines']==defines
 for name,digest in manifest['files'].items():assert hashlib.sha256((old/name).read_bytes()).hexdigest()==digest,(old,name)
 for name in ['cxi_primitives.cuh','gin_cxi.cuh','cxi_queue_credit.h','cxi_fence_command.h']:
  actual=(old/'include/nccl_device/gin/cxi'/name).read_bytes()
  expected=(source/'backend/device'/name).read_bytes()
  if name=='cxi_primitives.cuh':expected=''.join('#define %s %d\n'%x for x in sorted(defines.items())).encode()+expected
  assert actual==expected,name
 assert hashlib.sha256((old/'lib/libnccl.so.2.32.3').read_bytes()).hexdigest()==after['baseline_library_sha256']
 (runtime/variant).symlink_to(old,target_is_directory=True)
out=campaign/'preflight'/source.name;out.mkdir()
(out/'staged.json').write_text(json.dumps(dict(parent=parent_name,runtime_parent=runtime_parent_name,
 scope='Same packed executable inputs; existing verified delivery-policy runtimes; new actual-template compilation and GPU checks pending'),indent=2)+'\n')
print('STAGED packed delivery comparison; no GPU qualification',source.name)
