"""Install/audit a local-runtime-log patch, reusing compiled inputs."""
import hashlib,json,os,shutil,sys,tarfile
from pathlib import Path

name,parent_name,job=sys.argv[1:];assert job.isdigit()
assert all(Path(x).name==x for x in [name,parent_name])
campaign=Path(__file__).resolve().parent;parent=campaign/'sources'/parent_name;source=campaign/'sources'/name
before=json.loads((parent/'manifest.json').read_text());assert not source.exists()
shutil.copytree(str(parent),str(source),copy_function=os.link,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
with tarfile.open(str(campaign/(name+'-overlay.tar.gz'))) as archive:
 for m in archive:
  assert m.isfile() and m.name in ['backend/tools/direct_node.sh','backend/tests/ep_benchmark.py','sequence.json','manifest.json']
  dest=source/m.name;temp=dest.with_name(dest.name+'.overlay-tmp')
  with temp.open('xb') as f:f.write(archive.extractfile(m).read())
  os.chmod(str(temp),m.mode);temp.replace(dest)
after=json.loads((source/'manifest.json').read_text())
assert set(before['files'])==set(after['files'])
assert {k for k in before['files'] if before['files'][k]!=after['files'][k]}=={'backend/tools/direct_node.sh','backend/tests/ep_benchmark.py','sequence.json'}
for root,m in [(parent,before),(source,after)]:
 for relative,digest in m['files'].items():assert hashlib.sha256((root/relative).read_bytes()).hexdigest()==digest,(root,relative)
assert (source/'DeepEP.tar.gz').read_bytes()==(parent/'DeepEP.tar.gz').read_bytes()
assert "runtime_log=$(mktemp" in (source/'backend/tools/direct_node.sh').read_text()
assert 'cp --no-preserve=all "$runtime_log" "$base/smoke.log"' in (source/'backend/tools/direct_node.sh').read_text()
assert (campaign/'preflight'/parent_name/'PASS').is_file()
runtime=campaign/'runtime'/name;assert not runtime.exists();runtime.symlink_to(parent_name,target_is_directory=True)
records=[];builds=campaign/'jobs'/job/'builds'
for variant in json.loads((source/'variants.json').read_text()):
 for node in range(2):
  old=builds/parent_name/variant/('node%d'%node)
  if not (old/'PASS').exists():continue
  data=json.loads((old/'build.json').read_text())
  assert hashlib.sha256(Path(data['extension']).read_bytes()).hexdigest()==data['sha256']
  dest=builds/name/variant/('node%d'%node);dest.parent.mkdir(parents=True,exist_ok=True);dest.symlink_to(old,target_is_directory=True)
  records.append(dict(variant=variant,node=node,parent=str(old),binary_sha256=data['sha256']))
out=campaign/'preflight'/name;out.mkdir(exist_ok=False)
(out/'compile-equivalence.json').write_text(json.dumps(dict(parent=str(parent),changed_sources=['backend/tools/direct_node.sh','backend/tests/ep_benchmark.py','sequence.json'],
 parent_compile_evidence=json.loads((campaign/'preflight'/parent_name/'compile-equivalence.json').read_text()),
 native_reuse=records,scope='Only host runtime logging and provenance change; all compiled inputs and runtime are identical; parent manifests unchanged'),indent=2)+'\n')
(out/'PASS').write_text('PASS exact local runtime logging host-only delta; inherited compilation; GPU execution pending\n')
print('PASS local runtime logging staging and compilation equivalence',name)
