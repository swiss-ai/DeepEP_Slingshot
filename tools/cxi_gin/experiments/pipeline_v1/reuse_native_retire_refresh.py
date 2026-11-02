"""Reuse only the unchanged DeepEP extension, never the patched host GIN plugin."""
import hashlib,json,sys
from pathlib import Path

campaign=Path(sys.argv[1]);job=sys.argv[2];assert job.isdigit()
parent=campaign/'sources/source-marker-probe-v3';source=campaign/'sources'/(sys.argv[3] if len(sys.argv)>3 else 'source-retire-refresh-v1')
assert (campaign/'preflight'/source.name/'PASS').is_file()
a=json.loads((parent/'manifest.json').read_text())['files'];b=json.loads((source/'manifest.json').read_text())['files']
assert set(a)==set(b)
assert {k for k in a if a[k]!=b[k]}=={'backend/host/cxi_resources.cc','runner/validate_gate.py','sequence.json'}
for name in ['DeepEP.tar.gz','DeepEP-trace.tar.gz','backend/tests/nvcc_wrapper.py','runner/node.sh','backend/tools/direct_node.sh']:
 assert hashlib.sha256((parent/name).read_bytes()).hexdigest()==hashlib.sha256((source/name).read_bytes()).hexdigest()
assert (campaign/'runtime'/source.name/'marker-zero').resolve()==(campaign/'runtime'/parent.name/'marker-zero').resolve()
base=campaign/'jobs'/job/'builds';dest=base/source.name/'marker-zero';assert not dest.exists()
dest.mkdir(parents=True);records=[]
for node in range(2):
 old=base/parent.name/'marker-zero'/('node%d'%node)
 assert (old/'PASS').is_file()
 record=json.loads((old/'build.json').read_text());binary=Path(record['extension'])
 assert hashlib.sha256(binary.read_bytes()).hexdigest()==record['sha256']
 (dest/('node%d'%node)).symlink_to(old,target_is_directory=True)
 records.append(dict(node=node,native_build=str(old),extension_sha256=record['sha256']))
(dest/'NATIVE_BUILD_REUSE.json').write_text(json.dumps(dict(records=records,
 scope='Exact unchanged DeepEP native build inputs/runtime; the changed host GIN plugin is compiled freshly by direct_node.sh in every gate'),indent=2)+'\n')
print('PASS unchanged native extension reused; new host plugin remains separately rebuilt')
