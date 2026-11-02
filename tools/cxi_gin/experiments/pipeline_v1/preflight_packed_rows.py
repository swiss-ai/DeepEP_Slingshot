"""Compile actual fresh/cached EP8 dispatch templates for both staging layouts.

Run on Clariden login with SNAPSHOT; Python 3.6 compatible, no GPU execution.
"""
import argparse
import hashlib
import json
import os
import subprocess
import sys
import tarfile
from pathlib import Path


def main():
    parser=argparse.ArgumentParser();parser.add_argument('source',type=Path)
    parser.add_argument('--transport-parent',default='source-hw-fence-v3')
    parser.add_argument('--variant',default='fence-batched');args=parser.parse_args()
    source=args.source.resolve();campaign=source.parent.parent
    assert Path(args.transport_parent).name==args.transport_parent and Path(args.variant).name==args.variant
    parent=campaign/'sources'/args.transport_parent
    preflight=campaign/'preflight'/source.name
    assert (preflight/'TRANSPORT_PREFLIGHT_PASS').is_file()
    checker_sha=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    out=preflight/('templates-'+checker_sha[:12]);out.mkdir()
    manifest=json.loads((source/'manifest.json').read_text())
    for name,digest in manifest['files'].items():
        assert hashlib.sha256((source/name).read_bytes()).hexdigest()==digest,name
    for p in (parent/'backend').rglob('*'):
        if p.is_file() and (p.parent.name in ('device','host','include')):
            assert p.read_bytes()==(source/p.relative_to(parent)).read_bytes(),p
    ep=out/'ordinary-source';ep.mkdir()
    with tarfile.open(str(source/'DeepEP.tar.gz')) as archive:archive.extractall(str(ep))
    sdk=Path('/iopsstor/scratch/cscs/zyu/deepep-direct-20261026/cuda-sdk/usr/local/cuda-13.0')
    runtime=campaign/'runtime'/source.name/args.variant
    env=os.environ.copy();env['TMPDIR']=str(out)
    records=[]
    for packed in [0,1]:
        for tokens in [32,257,4096,16384]:
            for dtype,hidden,scales in [('fp8',4096,32),('bf16',8192,0)]:
                for mode,cpu,reuse,notify in [('fresh','true','false',4),('cached','false','true',0)]:
                    name='%s-%s-%d-packed%d'%(mode,dtype,tokens,packed)
                    unit=out/(name+'.cu');binary=out/(name+'.cubin')
                    unit.write_text('''#include <deep_ep/impls/hybrid_dispatch.cuh>
using namespace deep_ep::elastic;
static void __instantiate_kernel() {
 auto ptr = reinterpret_cast<void*>(&hybrid_dispatch_impl<%s,%s,64,%d,4,4,2,4,%d,%d,%d,256,6,128,129,118800000000>);
}
'''%(cpu,reuse,notify,hidden,scales,tokens))
                    command=[str(sdk/'bin/nvcc'),'-ccbin','/usr/bin/g++-13',str(unit),'-cubin','-o',str(binary),'-std=c++20',
                        '-DCXI_EP_PACK_ROWS='+str(packed),'-DCXI_EP_UPDATE_INTERVAL=3','-DCXI_EP_FORWARD_CHUNK=3',
                        '--ptxas-options=-v','--ptxas-options=--register-usage-level=10',
                        '-I'+str(runtime/'include'),'-I'+str(ep/'deep_ep/include'),
                        '--gpu-architecture=sm_90a','--compiler-options=-fPIC,-O3,-fconcepts,-Wno-deprecated-declarations,-Wno-abi',
                        '-O3','--expt-relaxed-constexpr','--expt-extended-lambda',
                        '--diag-suppress=39,161,174,177,186,940,3012']
                    with (out/(name+'.log')).open('w') as log:
                        log.write(' '.join(command)+'\n');log.flush()
                        subprocess.check_call(command,env=env,stdout=log,stderr=subprocess.STDOUT)
                    records.append(dict(name=name,command=command,sha256=hashlib.sha256(binary.read_bytes()).hexdigest()))
                    print('EP8_TEMPLATE_COMPILE_PASS '+name,flush=True)
    (out/'template-compilation.json').write_text(json.dumps(dict(checker_sha256=checker_sha,records=records),indent=2)+'\n')
    (preflight/'PASS').write_text('Transport identity, CPU packing model, and 32 fresh/cached FP8/BF16 EP8 templates passed; GPU unqualified. Evidence: '+str(out)+'\n')


if __name__=='__main__':main()
