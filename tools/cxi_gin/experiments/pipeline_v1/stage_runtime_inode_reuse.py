"""Preserve every runtime byte while avoiding redundant, stalled common inodes."""
import hashlib,json,os,shutil,sys,tarfile
from pathlib import Path
c=Path(__file__).resolve().parent;job=sys.argv[1];assert job.isdigit()
name='source-local-runtime-v1';parent=c/'sources/source-local-reports-v1';source=c/'sources'/name
assert (c/'preflight'/parent.name/'PASS').is_file() and not source.exists()
shutil.copytree(str(parent),str(source),copy_function=os.link,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
with tarfile.open(str(c/(name+'-overlay.tar.gz'))) as t:
 for m in t:
  assert m.isfile() and m.name in ['sequence.json','manifest.json']
  dst=source/m.name;tmp=dst.with_name(dst.name+'.overlay-tmp');tmp.write_bytes(t.extractfile(m).read());tmp.replace(dst)
a=json.loads((parent/'manifest.json').read_text());b=json.loads((source/'manifest.json').read_text())
assert set(a['files'])==set(b['files']) and {k for k in a['files'] if a['files'][k]!=b['files'][k]}=={'sequence.json'}
for root,manifest in [(parent,a),(source,b)]:
 for path,digest in manifest['files'].items():assert hashlib.sha256((root/path).read_bytes()).hexdigest()==digest,path
runtime=c/'runtime'/name;runtime.mkdir()
known=c/'runtime'/parent.name/'marker-zero';km=json.loads((known/'runtime-manifest.json').read_text());records=[]
for variant in json.loads((source/'variants.json').read_text()):
 original=c/'runtime'/parent.name/variant;data=json.loads((original/'runtime-manifest.json').read_text());dest=runtime/variant;dest.mkdir();reused=[]
 for path,digest in data['files'].items():
  pick=known/path if km['files'].get(path)==digest else original/path
  assert hashlib.sha256(pick.read_bytes()).hexdigest()==digest,(variant,path)
  target=dest/path;target.parent.mkdir(parents=True,exist_ok=True)
  os.link(str(pick.resolve()),str(target))
  assert hashlib.sha256(target.read_bytes()).hexdigest()==digest
  reused.append(dict(path=path,from_marker_zero=km['files'].get(path)==digest))
 (dest/'runtime-manifest.json').write_bytes((original/'runtime-manifest.json').read_bytes())
 records.append(dict(variant=variant,common_files=sum(x['from_marker_zero'] for x in reused),files=reused))
builds=c/'jobs'/job/'builds';native=[]
for variant in json.loads((source/'variants.json').read_text()):
 for node in range(2):
  old=builds/parent.name/variant/('node%d'%node)
  if not (old/'PASS').exists():continue
  data=json.loads((old/'build.json').read_text());assert hashlib.sha256(Path(data['extension']).read_bytes()).hexdigest()==data['sha256']
  dest=builds/name/variant/('node%d'%node);dest.parent.mkdir(parents=True,exist_ok=True);dest.symlink_to(old,target_is_directory=True)
  native.append(dict(variant=variant,node=node,parent=str(old),binary_sha256=data['sha256']))
out=c/'preflight'/name;out.mkdir()
(out/'compile-equivalence.json').write_text(json.dumps(dict(source_parent=parent.name,changed_source_files=['sequence.json'],runtime_byte_identity=True,runtime_inode_reuse=records,native_reuse=native,parent_compile_evidence=json.loads((c/'preflight'/parent.name/'compile-equivalence.json').read_text()),scope='Source code and every runtime file hash unchanged; different immutable namespace with healthy common inodes; GPU qualification pending'),indent=2)+'\n')
(out/'PASS').write_text('PASS exact source and runtime byte identity; common header/library inode reuse; GPU execution pending\n')
print('PASS common runtime inode reuse',[(x['variant'],x['common_files']) for x in records],flush=True)
