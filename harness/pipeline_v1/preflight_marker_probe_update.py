"""Compile a corrected GIN test with byte-identical transport and DeepEP inputs."""
import hashlib,json,subprocess,sys
from pathlib import Path
source,parent=map(Path,sys.argv[1:]);campaign=source.parent.parent
assert (campaign/'preflight'/parent.name/'PASS').is_file()
a=json.loads((parent/'manifest.json').read_text())['files'];b=json.loads((source/'manifest.json').read_text())['files']
assert set(a)==set(b)
assert {k for k in a if a[k]!=b[k]}=={'backend/tests/gin_smoke.cu','sequence.json'}
for k,h in b.items():assert hashlib.sha256((source/k).read_bytes()).hexdigest()==h,k
out=campaign/'preflight'/source.name;out.mkdir(exist_ok=True)
sdk=Path('/iopsstor/scratch/cscs/zyu/deepep-direct-20261026/cuda-sdk/usr/local/cuda-13.0')
variants=json.loads((source/'variants.json').read_text());records=[]
for v in variants:
 before=campaign/'runtime'/parent.name/v;after=campaign/'runtime'/source.name/v
 assert before.resolve()==after.resolve()
 command=[str(sdk/'bin/nvcc'),'-std=c++17','-arch=sm_90','-I'+str(after/'include'),'-c',str(source/'backend/tests/gin_smoke.cu'),'-o',str(out/(v+'-gin-smoke.o'))]
 subprocess.check_call(command);records.append(dict(variant=v,command=command));print('PASS corrected probe compiled '+v,flush=True)
(out/'compile-equivalence.json').write_text(json.dumps(dict(parent=str(parent),changed=['backend/tests/gin_smoke.cu','sequence.json'],runtime_alias=str((campaign/'runtime'/source.name).resolve()),compilation=records,scope='Synchronized probe reset and fixed handshake targets; transport/DeepEP unchanged; no GPU result asserted'),indent=2)+'\n')
(out/'PASS').write_text('PASS corrected probe compiles for all three identical transport runtimes\n')
