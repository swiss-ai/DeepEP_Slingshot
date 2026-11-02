"""Qualify a host-readiness-only raw-probe change against a compiled parent.

For login-node Python 3.6. Rebuild every selected raw probe and require bytewise
identity of all other source/runtime compilation inputs. GPU tests are separate.
"""
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path


def main():
    source,parent=map(Path,sys.argv[1:])
    campaign=source.parent.parent
    out=campaign/'preflight'/source.name
    out.mkdir(parents=True,exist_ok=True)
    assert (campaign/'preflight'/parent.name/'PASS').is_file()
    def check(root,manifest):
        data=json.loads((root/manifest).read_text())
        for name,digest in data['files'].items():
            assert hashlib.sha256((root/name).read_bytes()).hexdigest()==digest,(root,name)
        return data
    previous=check(parent,'manifest.json');current=check(source,'manifest.json')
    assert previous['files'].keys()==current['files'].keys()
    changed={k for k in current['files'] if previous['files'][k]!=current['files'][k]}
    assert changed=={'runner/burst_probe.cu','sequence.json'},changed
    variants=json.loads((source/'variants.json').read_text())
    assert variants==json.loads((parent/'variants.json').read_text())
    sdk=Path('/iopsstor/scratch/cscs/zyu/deepep-direct-20261026/cuda-sdk/usr/local/cuda-13.0')
    env=os.environ.copy();temp=campaign/'tmp'/source.name;temp.mkdir(parents=True,exist_ok=True);env['TMPDIR']=str(temp)
    for variant,definitions in variants.items():
        new_runtime=campaign/'runtime'/source.name/variant
        old_runtime=campaign/'runtime'/parent.name/variant
        assert check(new_runtime,'runtime-manifest.json')['files']==check(old_runtime,'runtime-manifest.json')['files']
        command=[str(sdk/'bin/nvcc'),'-std=c++17','-arch=sm_90']
        command+=['-D%s=%s'%(k,v) for k,v in sorted(definitions.items())]
        command+=['-I'+str(source/'backend/include'),'-I'+str(source/'backend/device'),
                  '-c',str(source/'runner/burst_probe.cu'),'-o',str(out/(variant+'-burst.o'))]
        subprocess.check_call(command,env=env)
        print('SM90_RAW_COMPILE_PASS '+variant,flush=True)
    evidence=dict(parent=str(parent),changed_sources=sorted(changed),
                  unchanged_runtime_variants=list(variants),
                  scope='Compile equivalence for unchanged inputs plus rebuilt raw probe; GPU qualification pending')
    (out/'compile-equivalence.json').write_text(json.dumps(evidence,indent=2)+'\n')
    (out/'PASS').write_text('Host-readiness-only update: unchanged compilation inputs verified; all raw GPU variants rebuilt.\n')
    print(json.dumps(evidence),flush=True)


if __name__=='__main__':main()
