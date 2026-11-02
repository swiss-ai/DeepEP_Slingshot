"""Audit exact packed GPU inputs while changing only the host storage harness."""
import hashlib,json,subprocess,sys,tarfile
from pathlib import Path

source=Path(sys.argv[1]).resolve();campaign=source.parent.parent
parent=campaign/'sources/source-zero-packed-v3';harness=campaign/'sources/source-local-io-v1'
def verify(root):
 data=json.loads((root/'manifest.json').read_text())['files']
 for name,digest in data.items():assert hashlib.sha256((root/name).read_bytes()).hexdigest()==digest,(root,name)
 return data
old,new=verify(parent),verify(source);verify(harness)
assert set(new)-set(old)=={'backend/tests/diagnostic_watch.py','backend/tests/result_spool.py'}
assert not set(old)-set(new)
changed={k for k in old if old[k]!=new[k]}
assert changed=={'DeepEP.tar.gz','backend/tests/common.py','backend/tests/ep_benchmark.py','backend/tools/direct_node.sh','runner/node.sh','runner/validate_gate.py','sequence.json'}
def archive(path):
 with tarfile.open(str(path)) as t:return {m.name:hashlib.sha256(t.extractfile(m).read()).hexdigest() for m in t if m.isfile()}
assert archive(parent/'DeepEP.tar.gz')==archive(source/'DeepEP.tar.gz')
for name in ['backend/tests/common.py','backend/tests/diagnostic_watch.py','backend/tests/result_spool.py','backend/tools/direct_node.sh']:
 assert (source/name).read_bytes()==(harness/name).read_bytes()
for name in ['backend/tests/ep_benchmark.py','backend/tests/diagnostic_watch.py','backend/tests/result_spool.py','runner/validate_gate.py']:
 compile((source/name).read_text(),name,'exec')
for name in ['runner/node.sh','backend/tools/direct_node.sh']:subprocess.check_call(['bash','-n',str(source/name)])
for name in [parent.name,harness.name]:assert (campaign/'preflight'/name/'PASS').is_file()
runtime=campaign/'runtime'/source.name;assert not runtime.exists();runtime.symlink_to(parent.name,target_is_directory=True)
for variant in json.loads((source/'variants.json').read_text()):
 a=json.loads((runtime/variant/'runtime-manifest.json').read_text())
 b=json.loads((campaign/'runtime'/harness.name/variant/'runtime-manifest.json').read_text())
 assert a==b
 for name,digest in a['files'].items():assert hashlib.sha256((runtime/variant/name).read_bytes()).hexdigest()==digest
out=campaign/'preflight'/source.name;out.mkdir(exist_ok=False)
(out/'compile-equivalence.json').write_text(json.dumps(dict(parent=str(parent),
 unchanged_gpu_archive_contents=True,unchanged_transport=True,unchanged_runtime=True,
 parent_compile_evidence=json.loads((campaign/'preflight'/parent.name/'compile-equivalence.json').read_text()),
 changed_sources=sorted(changed),native_build_reused=False,
 scope='Exact previously compiled packed GPU inputs; host I/O harness only; GPU qualification pending'),indent=2)+'\n')
(out/'PASS').write_text('PASS unchanged packed GPU compilation inputs and host I/O syntax; GPU execution pending\n')
print('PASS exact packed GPU content/runtime equivalence; GPU execution pending')
