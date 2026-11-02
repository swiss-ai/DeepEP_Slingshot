"""Host-only compilation of private FP8 4K tracing; no GPU qualification."""
import argparse,hashlib,json,os,subprocess,tarfile
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('source',type=Path);a=p.parse_args()
s=a.source.resolve();campaign=s.parent.parent
assert (campaign/'preflight'/s.name/'staged.json').is_file()
m=json.loads((s/'manifest.json').read_text())
for name,digest in m['files'].items():assert hashlib.sha256((s/name).read_bytes()).hexdigest()==digest,name
checker=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
out=campaign/'preflight'/s.name/('trace-templates-'+checker[:12]);out.mkdir()
ep=out/'source';ep.mkdir()
with tarfile.open(str(s/'DeepEP-trace.tar.gz')) as t:
 for member in t:
  name=Path(member.name)
  assert not name.is_absolute() and '..' not in name.parts
  target=ep/name
  if member.isdir():target.mkdir(parents=True,exist_ok=True)
  else:
   assert member.isfile(),member.name
   target.parent.mkdir(parents=True,exist_ok=True)
   # Compilation needs source bytes, not archive ownership/timestamps. Lustre
   # attribute restoration can block independently of reading those bytes.
   target.write_bytes(t.extractfile(member).read())
sdk=Path('/iopsstor/scratch/cscs/zyu/deepep-direct-20261026/cuda-sdk/usr/local/cuda-13.0')
runtime=campaign/'runtime'/s.name/'marker-zero-trace'
runtime_manifest=json.loads((runtime/'runtime-manifest.json').read_text())
for name,digest in runtime_manifest['files'].items():
 assert hashlib.sha256((runtime/name).read_bytes()).hexdigest()==digest,name
env=os.environ.copy();env['TMPDIR']=str(out)
records=[]
for interval in [3,8,16]:
 for packed in [0,1]:
  for tokens in [4096]:
   for dtype,hidden,scales in [('fp8',4096,32)]:
    for mode,cpu,reuse,notify in [('fresh','true','false',4),('cached','false','true',0)]:
     name='%s-%s-%d-packed%d-i%d'%(mode,dtype,tokens,packed,interval)
     unit=out/(name+'.cu');binary=out/(name+'.cubin')
     unit.write_text('''#include <deep_ep/impls/hybrid_dispatch.cuh>
using namespace deep_ep::elastic;
static void __instantiate_kernel() {
 auto ptr = reinterpret_cast<void*>(&hybrid_dispatch_impl<%s,%s,64,%d,4,4,2,4,%d,%d,%d,256,6,128,129,118800000000>);
}
'''%(cpu,reuse,notify,hidden,scales,tokens))
     cmd=[str(sdk/'bin/nvcc'),'-ccbin','/usr/bin/g++-13',str(unit),'-cubin','-o',str(binary),'-std=c++20',
      '-DEP_TRACE_PTR=4096ULL','-DCXI_EP_PACK_ROWS='+str(packed),'-DCXI_EP_UPDATE_INTERVAL='+str(interval),'-DCXI_EP_FORWARD_CHUNK=3',
      '--ptxas-options=-v','--ptxas-options=--register-usage-level=10','-I'+str(runtime/'include'),'-I'+str(ep/'deep_ep/include'),
      '--gpu-architecture=sm_90a','--compiler-options=-fPIC,-O3,-fconcepts,-Wno-deprecated-declarations,-Wno-abi',
      '-O3','--expt-relaxed-constexpr','--expt-extended-lambda','--diag-suppress=39,161,174,177,186,940,3012']
     with (out/(name+'.log')).open('w') as log:
      log.write(' '.join(cmd)+'\n');log.flush();subprocess.check_call(cmd,env=env,stdout=log,stderr=subprocess.STDOUT)
     records.append(dict(name=name,command=cmd,sha256=hashlib.sha256(binary.read_bytes()).hexdigest()))
     print('TEMPLATE_PASS '+name,flush=True)
(out/'compile.json').write_text(json.dumps(dict(checker_sha256=checker,source=s.name,manifest_sha256=hashlib.sha256((s/'manifest.json').read_bytes()).hexdigest(),records=records,scope='Private trace FP8 4K dispatch templates only; no GPU execution; ordinary packing qualification prerequisite'),indent=2)+'\n')
(out/'PASS').write_text('PASS 12 private trace SM90a templates; no GPU execution\n')
print('PASS all12 private trace templates',flush=True)

(campaign/'preflight'/s.name/'PASS').write_text('PASS 12 actual FP8 4K traced dispatch templates; transport inherits byte-identical parent with trace scopes only; GPU qualification pending. Evidence: '+str(out)+'\n')
