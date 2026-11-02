"""Diagnostic-only reproduction; GPU/transport sources remain byte-identical."""
import argparse
import hashlib
import json
import shutil
from pathlib import Path
from package import ROOT, REMOTE, replace


def add_observer(out):
    shutil.copyfile(Path(__file__).with_name('diagnostic_watch.py'), out / 'backend/tests/diagnostic_watch.py')
    benchmark = out / 'backend/tests/ep_benchmark.py'
    replace(benchmark, 'def measure(fn, args):', 'import diagnostic_watch\n\ndef measure(fn, args):')
    replace(benchmark, '    for _ in range(args.warmup): result=fn()', '''    for i in range(args.warmup):
        diagnostic_watch.mark('warmup_host_enter', call_index=i)
        result=fn()
        diagnostic_watch.mark('warmup_host_return', call_index=i)
    diagnostic_watch.mark('warmup_synchronize_enter')''')
    replace(benchmark, '    starts=[torch.cuda.Event(enable_timing=True)',
            "    diagnostic_watch.mark('warmup_synchronize_and_barrier_return')\n    starts=[torch.cuda.Event(enable_timing=True)")
    replace(benchmark, '    for a,b in zip(starts,ends):\n        a.record(); result=fn(); b.record()', '''    for i,(a,b) in enumerate(zip(starts,ends)):
        diagnostic_watch.mark('timed_host_enter', call_index=i)
        a.record(); result=fn(); b.record()
        diagnostic_watch.mark('timed_host_return', call_index=i)
    diagnostic_watch.mark('timed_synchronize_enter')''')
    replace(benchmark, '    wall=time.monotonic()-wall; cpu=time.process_time()-cpu',
            "    diagnostic_watch.mark('timed_synchronize_return')\n    wall=time.monotonic()-wall; cpu=time.process_time()-cpu")
    replace(benchmark, "    print('CASE_START',json.dumps(case),flush=True)",
            "    diagnostic_watch.mark('case_start', model=model, tokens=n, dtype=dtype, routing=routing, operation=None)\n    print('CASE_START',json.dumps(case),flush=True)")
    replace(benchmark, '    cy,_,_=cycle()', "    diagnostic_watch.mark('cycle_check_host_enter', operation='cycle_check')\n    cy,_,_=cycle()\n    diagnostic_watch.mark('cycle_check_host_return')")
    replace(benchmark, '    for op,fn in funcs.items():\n        samples=measure(fn,args)',
            "    for op,fn in funcs.items():\n        diagnostic_watch.mark('operation_begin', operation=op)\n        samples=measure(fn,args)")
    replace(benchmark, '    source=os.environ[', "    diagnostic_watch.start(out,rank)\n    source=os.environ[")
    replace(benchmark, "    (out/f'libraries-rank{rank}.txt')", "    diagnostic_watch.finish()\n    (out/f'libraries-rank{rank}.txt')")
    replace(out / 'runner/validate_gate.py', "        ep = base / 'ep'", '''        ep = base / 'ep'
        if env.get('CXI_DIAGNOSTIC_WATCHDOG') == '1':
            for rank in range(8):
                watch=[json.loads(line) for line in (ep/('diagnostic-watch-rank%d.jsonl'%rank)).read_text().splitlines()]
                require(watch and watch[0]['phase']=='observer_started' and
                        watch[-1]['phase']=='observer_stopped' and watch[-1]['thread_stopped'],
                        'diagnostic observer incomplete')
                require(not any(w.get('diagnostic_code',0) for w in watch), 'GPU diagnostic reported')''')


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('output', type=Path)
    out = parser.parse_args().output.resolve()
    base = ROOT / 'results/deepep_pipeline_20261030/source-credit-cache-v2'
    shutil.copytree(base, out, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    add_observer(out)
    sequence = []
    originals = json.loads((base / 'sequence.json').read_text())
    for number, variant, parent in [(700, 'credit-control', '503-credit-control-ep-correctness'),
                                     (701, 'credit-cached', '507-credit-cached-ep-correctness')]:
        spec = next(s for s in originals if s['name'] == ('520-credit-control-repeat1' if number == 700 else '521-credit-cached-repeat1'))
        spec['name'] = '%d-%s-diagnostic' % (number, variant)
        spec['snapshot'] = REMOTE + '/sources/' + out.name
        spec['environment']['CXI_DIAGNOSTIC_WATCHDOG'] = '1'
        spec['requires'] = [parent]
        sequence.append(spec)
    (out / 'sequence.json').write_text(json.dumps(sequence, indent=2) + '\n')
    changed = []
    for path in base.rglob('*'):
        if path.is_file() and '__pycache__' not in path.parts and path.suffix != '.pyc':
            relative = path.relative_to(base)
            if path.read_bytes() != (out / relative).read_bytes():
                changed.append(str(relative))
    assert set(changed) == {'backend/tests/ep_benchmark.py', 'runner/validate_gate.py', 'sequence.json'}, changed
    manifest = json.loads((base / 'manifest.json').read_text())
    manifest.update(scope='Diagnostic-only cached-credit failure reproduction; no GPU or transport source changes',
        files={str(p.relative_to(out)): hashlib.sha256(p.read_bytes()).hexdigest()
               for p in sorted(out.rglob('*')) if p.is_file() and p.name != 'manifest.json'})
    (out / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(out)


if __name__ == '__main__':
    main()
