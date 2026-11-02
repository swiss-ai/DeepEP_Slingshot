"""Isolate the tiny-token control failure without changing GPU source."""
import argparse
import hashlib
import json
import shutil
from pathlib import Path
from package import ROOT, REMOTE, replace
from package_credit_debug import add_observer


def main():
    parser=argparse.ArgumentParser();parser.add_argument('output',type=Path)
    parser.add_argument('--buffered',action='store_true')
    args=parser.parse_args();out=args.output.resolve()
    base=ROOT/'results/deepep_pipeline_20261030/source-packed-rows-v2'
    shutil.copytree(base,out,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    add_observer(out)
    if args.buffered:
        shutil.copyfile(Path(__file__).with_name('diagnostic_watch_buffered.py'),
                        out/'backend/tests/diagnostic_watch.py')
    benchmark=out/'backend/tests/ep_benchmark.py'
    replace(benchmark,'        rr=b.dispatch(x,idx,w)',
            "        diagnostic_watch.mark('cycle_dispatch_host_enter')\n        rr=b.dispatch(x,idx,w)\n        diagnostic_watch.mark('cycle_dispatch_host_return')")
    replace(benchmark,'        return b.combine(cycle_y,hh,rr[2])',
            "        diagnostic_watch.mark('cycle_combine_host_enter')\n        result=b.combine(cycle_y,hh,rr[2])\n        diagnostic_watch.mark('cycle_combine_host_return')\n        return result")
    original=json.loads((base/'sequence.json').read_text())[0]
    seq=[]
    cases=([(855,'mixed uniform hot_rank local remote'),(856,'mixed uniform hot_rank local remote')]
           if args.buffered else [(850,'local'),(851,'mixed uniform hot_rank local remote')])
    for number,routes in cases:
        spec=json.loads(json.dumps(original))
        spec.update(name='%d-rows-32-%s-diagnostic'%(number,'local' if number==850 else 'routes'),
                    snapshot=REMOTE+'/sources/'+out.name, timeout_seconds=720)
        spec['environment'].update(CXI_DIAGNOSTIC_WATCHDOG='1',CXI_EP_TOKENS='32',
                                  CXI_EP_ROUTING=routes,CXI_TEST_TIMEOUT='660')
        if args.buffered:
            tokens='32' if number==855 else '257'
            spec.update(name='%d-rows-%s-buffered-stress'%(number,tokens),timeout_seconds=1200)
            spec['environment'].update(CXI_EP_TOKENS=tokens,CXI_EP_SEEDS='1 2 3',
                CXI_EP_WARMUP='20',CXI_EP_ITERS='100',CXI_TEST_TIMEOUT='1140')
        if seq:spec['requires']=[seq[-1]['name']]
        seq.append(spec)
    (out/'sequence.json').write_text(json.dumps(seq,indent=2)+'\n')
    manifest=json.loads((base/'manifest.json').read_text())
    changed=[str(p.relative_to(base)) for p in base.rglob('*') if p.is_file()
             and '__pycache__' not in p.parts and p.suffix!='.pyc'
             and p.read_bytes()!=(out/p.relative_to(base)).read_bytes()]
    assert set(changed)=={'backend/tests/ep_benchmark.py','runner/validate_gate.py','sequence.json'},changed
    manifest.update(source_parent=str(base),scope='Tiny-token unpacked control diagnostic; GPU/transport bytes unchanged',
        files={str(p.relative_to(out)):hashlib.sha256(p.read_bytes()).hexdigest()
               for p in sorted(out.rglob('*')) if p.is_file() and p.name!='manifest.json'})
    (out/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n');print(out)


if __name__=='__main__':main()
