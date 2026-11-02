"""Install a probe-only overlay, audit transport identity, compile actual kernels."""
import hashlib,json,os,shutil,subprocess,sys,tarfile
from pathlib import Path

name=sys.argv[1];assert Path(name).name==name
campaign=Path(__file__).resolve().parent
parent=campaign/'sources/source-zero-packed-v7';source=campaign/'sources'/name
assert not source.exists() and (campaign/'preflight'/parent.name/'PASS').is_file()
before=json.loads((parent/'manifest.json').read_text())
shutil.copytree(str(parent),str(source),copy_function=os.link,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
changed={'backend/tools/direct_node.sh','backend/tests/gin_smoke.py','runner/validate_gate.py','sequence.json'}
added={'backend/tests/gin_stage_ladder.cu'}
with tarfile.open(str(campaign/(name+'-overlay.tar.gz'))) as archive:
 assert {m.name for m in archive.getmembers()}==changed|added|{'manifest.json'}
 for m in archive:
  assert m.isfile();dest=source/m.name;temp=dest.with_name(dest.name+'.new')
  with temp.open('xb') as f:f.write(archive.extractfile(m).read())
  os.chmod(str(temp),m.mode);temp.replace(dest)
after=json.loads((source/'manifest.json').read_text())
assert set(after['files'])-set(before['files'])==added
assert {k for k in before['files'] if before['files'][k]!=after['files'][k]}==changed
for root,manifest in [(parent,before),(source,after)]:
 for relative,digest in manifest['files'].items():assert hashlib.sha256((root/relative).read_bytes()).hexdigest()==digest,(root,relative)
runtime=campaign/'runtime'/name
assert not runtime.exists();runtime.symlink_to(parent.name,target_is_directory=True)
variant=runtime/'marker-zero';rm=json.loads((variant/'runtime-manifest.json').read_text())
for relative,digest in rm['files'].items():assert hashlib.sha256((variant/relative).read_bytes()).hexdigest()==digest,relative
out=campaign/'preflight'/name;out.mkdir()
sdk=Path('/iopsstor/scratch/cscs/zyu/deepep-direct-20261026/cuda-sdk/usr/local/cuda-13.0')
env=os.environ.copy();env['TMPDIR']=str(out)
cmd=[str(sdk/'bin/nvcc'),'-ccbin','/usr/bin/g++-13','-std=c++20','-c',
 str(source/'backend/tests/gin_stage_ladder.cu'),'-o',str(out/'gin_stage_ladder.o'),
 '-I'+str(variant/'include'),'--gpu-architecture=sm_90a','--compiler-options=-fPIC,-O3',
 '--ptxas-options=-v','--expt-relaxed-constexpr','--expt-extended-lambda','-O3']
with (out/'compile.log').open('w') as log:
 log.write(' '.join(cmd)+'\n');log.flush();subprocess.check_call(cmd,env=env,stdout=log,stderr=subprocess.STDOUT)
subprocess.check_call(['bash','-n',str(source/'backend/tools/direct_node.sh')])
# Python3.6 login cannot parse the container's Python3.12 frontend; local syntax
# validation is recorded separately. All archived frontend bytes are audited.
record=dict(parent=parent.name,checker_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
 manifest_sha256=hashlib.sha256((source/'manifest.json').read_bytes()).hexdigest(),command=cmd,
 object_sha256=hashlib.sha256((out/'gin_stage_ladder.o').read_bytes()).hexdigest(),
 scope='Full native translation unit with4320/8256-byte transfer specializations compiled; unchanged transport/DeepEP; GPU unqualified')
(out/'compile.json').write_text(json.dumps(record,indent=2)+'\n')
(out/'PASS').write_text('PASS immutable transport audit, full probe compilation and shell syntax; GPU pending\n')
print('PASS staged and compiled matched transport ladder; GPU pending',name)
