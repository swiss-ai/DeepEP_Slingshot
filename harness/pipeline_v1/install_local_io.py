"""Audit host-only I/O changes and reuse byte-identical native/runtime inputs."""
import hashlib,json,subprocess,sys
from pathlib import Path

source=Path(sys.argv[1]).resolve();job=sys.argv[2];assert job.isdigit()
campaign=source.parent.parent;parent=campaign/'sources/source-first-call-debug-v1'
def manifest(root):
 data=json.loads((root/'manifest.json').read_text())
 for name,digest in data['files'].items():
  assert hashlib.sha256((root/name).read_bytes()).hexdigest()==digest,(root,name)
 return data['files']
old,new=manifest(parent),manifest(source)
assert set(new)-set(old)=={'backend/tests/result_spool.py'} and not set(old)-set(new)
changed={k for k in old if old[k]!=new[k]}
assert changed=={'backend/tests/common.py','backend/tests/ep_benchmark.py','backend/tools/direct_node.sh','runner/node.sh','sequence.json'}
assert (campaign/'preflight'/parent.name/'PASS').is_file()
runtime=campaign/'runtime'/source.name;assert not runtime.exists()
runtime.symlink_to(parent.name,target_is_directory=True)
for variant in json.loads((source/'variants.json').read_text()):
 a=json.loads((runtime/variant/'runtime-manifest.json').read_text())
 b=json.loads((campaign/'runtime'/parent.name/variant/'runtime-manifest.json').read_text())
 assert a==b
 for name,digest in a['files'].items():assert hashlib.sha256((runtime/variant/name).read_bytes()).hexdigest()==digest
for name in ['backend/tests/common.py','backend/tests/ep_benchmark.py','backend/tests/result_spool.py']:
 compile((source/name).read_text(),name,'exec')
for name in ['runner/node.sh','backend/tools/direct_node.sh']:subprocess.check_call(['bash','-n',str(source/name)])
builds=campaign/'jobs'/job/'builds';records=[]
for variant in ['marker-zero','marker-control']:
 for node in range(2):
  oldbuild=builds/parent.name/variant/('node%d'%node)
  assert (oldbuild/'PASS').is_file()
  evidence=json.loads((oldbuild/'build.json').read_text());binary=Path(evidence['extension'])
  assert hashlib.sha256(binary.read_bytes()).hexdigest()==evidence['sha256']
  dest=builds/source.name/variant/('node%d'%node);dest.parent.mkdir(parents=True,exist_ok=True)
  assert not dest.exists();dest.symlink_to(oldbuild,target_is_directory=True)
  records.append(dict(variant=variant,node=node,parent=str(oldbuild),binary_sha256=evidence['sha256']))
out=campaign/'preflight'/source.name;out.mkdir(parents=True,exist_ok=False)
(out/'compile-equivalence.json').write_text(json.dumps(dict(changed_sources=sorted(changed),
 records=records,scope='Host I/O only; no GPU, transport, native or ABI changes; GPU execution pending'),indent=2)+'\n')
(out/'PASS').write_text('Host I/O syntax and exact GPU/native/runtime input equivalence PASS\n')
print('PASS host I/O preparation; GPU validation pending')
