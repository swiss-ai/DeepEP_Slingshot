"""Observe source-described NIC counters with unchanged native-fence GPU code."""
import argparse
import hashlib
import json
import shutil
from pathlib import Path
from package import ROOT, REMOTE, replace


def main():
    parser=argparse.ArgumentParser();parser.add_argument('output',type=Path)
    out=parser.parse_args().output.resolve();base=ROOT/'results/deepep_pipeline_20261030/source-hw-fence-v3'
    shutil.copytree(base,out,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    shutil.copyfile(Path(__file__).with_name('nic_extra.py'),out/'backend/tests/nic_extra.py')
    shutil.copyfile(ROOT/'results/deepep_pipeline_20261030/nic-counter-catalog-v1.json',
                    out/'backend/tests/nic-counter-catalog.json')
    benchmark=out/'backend/tests/ep_benchmark.py'
    replace(benchmark,'def nic_window(fn,args,out,case):',
            'import nic_extra\n\ndef nic_window(fn,args,out,case):')
    replace(benchmark,'    before=nic_snapshot() if rank%4==0 else None',
            '    before=nic_snapshot() if rank%4==0 else None\n    extra_before=nic_extra.snapshot() if before else None')
    replace(benchmark,'        after=nic_snapshot(); rates={}',
            '        after=nic_snapshot(); rates={}\n        extra_after=nic_extra.snapshot()')
    replace(benchmark,"               scope='isolated operation window including synchronization/control traffic'))",
            "               scope='isolated operation window including synchronization/control traffic'))\n        nic_extra.record(out/f'nic-extra-node{rank//4}.jsonl',case,extra_before,extra_after,args.nic_iters,elapsed)")
    validator=out/'runner/validate_gate.py'
    old="        return {'status': 'PASS', 'kind': 'ep', 'ranks': 8, 'cases_per_rank': len(expected), 'gin_type': gin}"
    replace(validator,old,"""        import importlib.util
        helper=Path(__file__).resolve().parents[1]/'backend/tests/nic_extra.py'
        definition=importlib.util.spec_from_file_location('qualified_nic_extra',str(helper))
        module=importlib.util.module_from_spec(definition);definition.loader.exec_module(module)
        windows=module.validate(ep,env)
        return {'status': 'PASS', 'kind': 'ep', 'ranks': 8, 'cases_per_rank': len(expected),
                'gin_type': gin, 'nic_extra_windows': windows}""")
    original=json.loads((base/'sequence.json').read_text());sequence=[]
    for index,(variant,parent) in enumerate([('fence-control','412-fence-control-repeat1'),
                                           ('fence-dc','413-fence-dc-repeat1'),
                                           ('fence-batched','414-fence-batched-repeat1')]):
        spec=json.loads(json.dumps(next(r for r in original if r['name']==parent)))
        spec.update(name='%d-%s-nic-counters'%(1000+index,variant),snapshot=REMOTE+'/sources/'+out.name,
                    timeout_seconds=900)
        spec['environment'].update(CXI_EP_TOKENS='4096',CXI_TEST_TIMEOUT='840')
        sequence.append(spec)
    (out/'sequence.json').write_text(json.dumps(sequence,indent=2)+'\n')
    manifest=json.loads((base/'manifest.json').read_text())
    manifest.update(source_parent=str(base),scope='Additional NIC counter snapshots outside CUDA timing; all GPU/transport/runtime inputs unchanged',
        files={str(p.relative_to(out)):hashlib.sha256(p.read_bytes()).hexdigest()
               for p in sorted(out.rglob('*')) if p.is_file() and p.name!='manifest.json'})
    (out/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n');print(out)


if __name__=='__main__':main()
