"""Reuse exact GPU compilation evidence after a separately compiled host fix."""
import hashlib,json,sys,tarfile
from pathlib import Path

source=Path(sys.argv[1]).resolve();campaign=source.parent.parent
old=campaign/'sources/source-zero-packed-v1'
parent_name=sys.argv[2] if len(sys.argv)>2 else 'source-retire-refresh-v1'
assert Path(parent_name).name==parent_name
parent=campaign/'sources'/parent_name
def verify(root,name):
 d=json.loads((root/name).read_text())
 for k,h in d['files'].items():assert hashlib.sha256((root/k).read_bytes()).hexdigest()==h,(root,k)
 return d
a=verify(old,'manifest.json')['files'];b=verify(source,'manifest.json')['files'];verify(parent,'manifest.json')
assert set(a)==set(b)
assert {k for k in a if a[k]!=b[k]}=={'DeepEP.tar.gz','backend/host/cxi_resources.cc','runner/validate_gate.py','sequence.json'}
def archive(path):
 with tarfile.open(str(path)) as t:
  return {m.name:hashlib.sha256(t.extractfile(m).read()).hexdigest() for m in t if m.isfile()}
assert archive(old/'DeepEP.tar.gz')==archive(source/'DeepEP.tar.gz')
assert (source/'backend/host/cxi_resources.cc').read_bytes()==(parent/'backend/host/cxi_resources.cc').read_bytes()
assert (campaign/'preflight'/parent.name/'PASS').is_file()
previous=campaign/'preflight'/old.name
assert (previous/'PASS').is_file()
records=list(previous.glob('templates-*/template-compilation.json'));assert len(records)==1
compiled=json.loads(records[0].read_text());assert len(compiled['records'])==32
assert len({x['name'] for x in compiled['records']})==32
for x in compiled['records']:
 path=records[0].parent/(x['name']+'.cubin')
 assert hashlib.sha256(path.read_bytes()).hexdigest()==x['sha256'],x['name']
runtime=campaign/'runtime'/source.name;assert not runtime.exists();runtime.mkdir()
link=runtime/'marker-zero';link.symlink_to(campaign/'runtime'/parent.name/'marker-zero',target_is_directory=True)
assert link.resolve()==(campaign/'runtime'/old.name/'marker-zero').resolve()
assert verify(link,'runtime-manifest.json')['defines']==json.loads((source/'variants.json').read_text())['marker-zero']
compile((source/'runner/validate_gate.py').read_text(),'validate_gate.py','exec')
out=campaign/'preflight'/source.name;out.mkdir()
(out/'compile-equivalence.json').write_text(json.dumps(dict(
 gpu_parent=str(old),host_parent=str(parent),compile_records=str(records[0]),templates=32,
 ordinary_archive_contents_identical=True,runtime_identical=True,
 scope='Exact unchanged packed GPU inputs and verified cubins; separately compiled host lifecycle fix; packed GPU execution still unqualified'),indent=2)+'\n')
(out/'PASS').write_text('PASS exact 32-template GPU compilation reuse plus qualified host compilation; GPU execution pending\n')
print('PASS identical GPU inputs/cubins/runtime; host lifecycle compilation inherited; GPU qualification pending',flush=True)
