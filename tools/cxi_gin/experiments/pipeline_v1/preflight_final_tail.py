"""Compile merged/unmerged final dispatch notifications; no GPU execution."""
import argparse,hashlib,json,os,subprocess,tarfile
from pathlib import Path

p=argparse.ArgumentParser();p.add_argument('source',type=Path);a=p.parse_args()
s=a.source.resolve();campaign=s.parent.parent;preflight=campaign/'preflight'/s.name
assert (preflight/'TRANSPORT_PREFLIGHT_PASS').is_file()
manifest=json.loads((s/'manifest.json').read_text())
for name,digest in manifest['files'].items():assert hashlib.sha256((s/name).read_bytes()).hexdigest()==digest,name
checker=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
out=preflight/('templates-'+checker[:12]);out.mkdir();ep=out/'source';ep.mkdir()
with tarfile.open(str(s/'DeepEP.tar.gz')) as archive:
 for m in archive:
  name=Path(m.name);assert not name.is_absolute() and '..' not in name.parts
  target=ep/name
  if m.isdir():target.mkdir(parents=True,exist_ok=True)
  else:
   assert m.isfile();target.parent.mkdir(parents=True,exist_ok=True)
   target.write_bytes(archive.extractfile(m).read())
sdk=Path('/iopsstor/scratch/cscs/zyu/deepep-direct-20261026/cuda-sdk/usr/local/cuda-13.0')
runtime=campaign/'runtime'/s.name/'marker-zero';env=os.environ.copy();env['TMPDIR']=str(out)
records=[]
for qps in [129,257]:
 for merge in [0,1]:
  for tokens in [32,257,4096,16384]:
   for dtype,hidden,scales in [('fp8',4096,32),('bf16',8192,0)]:
    for mode,cpu,reuse,notify in [('fresh','true','false',4),('cached','false','true',0)]:
     name='%s-%s-%d-q%d-merge%d'%(mode,dtype,tokens,qps,merge)
     unit=out/(name+'.cu');binary=out/(name+'.cubin')
     unit.write_text('#include <deep_ep/impls/hybrid_dispatch.cuh>\nusing namespace deep_ep::elastic;\n'
       'static void __instantiate_kernel() { auto ptr = reinterpret_cast<void*>(&hybrid_dispatch_impl<%s,%s,64,%d,4,4,2,4,%d,%d,%d,256,6,128,%d,118800000000>); }\n'
       %(cpu,reuse,notify,hidden,scales,tokens,qps))
     cmd=[str(sdk/'bin/nvcc'),'-ccbin','/usr/bin/g++-13',str(unit),'-cubin','-o',str(binary),'-std=c++20',
      '-DCXI_EP_PACK_ROWS=1','-DCXI_EP_UPDATE_INTERVAL=16','-DCXI_EP_FORWARD_CHUNK=3','-DCXI_EP_MERGE_FINAL_TAIL='+str(merge),
      '--ptxas-options=-v','--ptxas-options=--register-usage-level=10','-I'+str(runtime/'include'),'-I'+str(ep/'deep_ep/include'),
      '--gpu-architecture=sm_90a','--compiler-options=-fPIC,-O3,-fconcepts,-Wno-deprecated-declarations,-Wno-abi',
      '-O3','--expt-relaxed-constexpr','--expt-extended-lambda','--diag-suppress=39,161,174,177,186,940,3012']
     with (out/(name+'.log')).open('w') as log:
      log.write(' '.join(cmd)+'\n');log.flush();subprocess.check_call(cmd,env=env,stdout=log,stderr=subprocess.STDOUT)
     records.append(dict(name=name,command=cmd,sha256=hashlib.sha256(binary.read_bytes()).hexdigest()))
     print('TEMPLATE_PASS '+name,flush=True)
(out/'compile.json').write_text(json.dumps(dict(checker_sha256=checker,records=records,
 source=s.name,manifest_sha256=hashlib.sha256((s/'manifest.json').read_bytes()).hexdigest(),
 scope='64 actual final-tail dispatch templates; no GPU qualification'),indent=2)+'\n')
(preflight/'PASS').write_text('Transport/archive audit and64 actual SM90a templates PASS; GPU unqualified\n')
print('PASS all64 final-tail templates',flush=True)
