"""Short all-rank CPU/CUDA traces, separate from unprofiled latency samples."""
from collections import defaultdict
from contextlib import contextmanager
import json
import statistics
import torch
import torch.distributed as dist


@contextmanager
def region(name):
    with torch.profiler.record_function(name), torch.cuda.nvtx.range(name):
        yield


def capture(backend, funcs, args, out, case):
    rank=dist.get_rank()
    activity=torch.profiler.ProfilerActivity
    assert activity.CUDA in torch.profiler.supported_activities(), 'CUDA profiler activity unavailable'
    target=out/'profiles'; target.mkdir(exist_ok=True)
    originals={}
    for name in ['get_dispatch_layout','dispatch','combine']:
        if not hasattr(backend.buf,name): continue
        fn=getattr(backend.buf,name); originals[name]=fn
        def wrapped(*a,_fn=fn,_name=name,**kw):
            with region('ep4k/'+args.backend+'/'+_name): return _fn(*a,**kw)
        setattr(backend.buf,name,wrapped)
    try:
        for op,fn in funcs.items():
            for _ in range(5): result=fn()
            torch.cuda.synchronize(); dist.barrier()
            with torch.profiler.profile(activities=[activity.CPU,activity.CUDA],
                    record_shapes=False,profile_memory=False,with_stack=False) as prof:
                for i in range(args.profile_steps):
                    with region('ep4k/'+op+'/iteration'+str(i)):
                        result=fn()
                    prof.step()
                with region('ep4k/profile_tail_wait'): torch.cuda.synchronize()
            stem=f"{case['model']}-{case['routing']}-{op}-rank{rank}"
            path=target/(stem+'.json'); prof.export_chrome_trace(str(path))
            events=json.loads(path.read_text())['traceEvents']
            kernels=[e for e in events if e.get('ph')=='X' and 'kernel' in e.get('cat','').lower()]
            assert kernels, f'No CUDA kernels in {path}; CPU-only trace is insufficient'
            groups=defaultdict(list)
            for e in kernels: groups[e['name']].append(e['dur'])
            # These are inclusive host-side observations, not additive phases:
            # CPU calls and GPU kernels can overlap, and nested ranges overlap.
            host_groups=defaultdict(list)
            for e in events:
                if e.get('ph') != 'X' or 'dur' not in e:
                    continue
                if e.get('cat') in ('cuda_runtime', 'cuda_driver') or e.get('name','').startswith('ep4k/'):
                    host_groups[(e.get('cat',''),e['name'])].append(e['dur'])
            summary=dict(case=case,operation=op,rank=rank,profiled_iterations=args.profile_steps,
                warning='Instrumented durations are diagnostic; CPU/GPU overlap means totals are not additive critical-path times.',
                kernels=[dict(name=k,count=len(v),total_us=sum(v),median_us=statistics.median(v)) for k,v in groups.items()],
                host_ranges_and_cuda_calls=[dict(category=c,name=k,count=len(v),inclusive_total_us=sum(v),
                    median_us=statistics.median(v)) for (c,k),v in host_groups.items()])
            (target/(stem+'-summary.json')).write_text(json.dumps(summary,indent=2)+'\n')
            dist.barrier()
    finally:
        for name,fn in originals.items(): setattr(backend.buf,name,fn)
