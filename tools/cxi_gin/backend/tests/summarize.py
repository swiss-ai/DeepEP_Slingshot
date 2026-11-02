import argparse
import csv
import itertools
import json
from pathlib import Path
import statistics

def read(root,pattern):
    return [json.loads(s) for p in sorted(root.glob(pattern)) for s in p.read_text().splitlines() if s]

def summarize(root):
    root=Path(root); manifests=read(root,'manifest-rank*.jsonl'); assert manifests
    ep=manifests[0]['ep']; args=manifests[0]['args']
    assert len(manifests)==ep and {m['rank'] for m in manifests}==set(range(ep))
    assert len({json.dumps(m['script_hashes'],sort_keys=True) for m in manifests})==1
    assert len({m['source_commit'] for m in manifests})==1
    assert len({m.get('deployed_source_sha256') for m in manifests})==1
    assert all((root/f'DONE-rank{r}').exists() for r in range(ep))
    assert not read(root,'failures-rank*.jsonl')
    fields=['rank','seed','model','tokens_per_gpu','dispatch_dtype','routing']
    expected=set(itertools.product(range(ep),args['seeds'],args['models'],args['tokens'],args['dtypes'],args['routing']))
    key=lambda r:tuple(r[k] for k in fields)
    checks=read(root,'correctness-rank*.jsonl')
    assert len(checks)==len(expected) and {key(r) for r in checks}==expected
    assert all(r['status']=='PASS' for r in checks)
    ts=read(root,'timings-rank*.jsonl')
    expected_ops={k+(op,) for k in expected for op in ['dispatch_fresh','dispatch_cached','combine','cycle']}
    assert len(ts)==len(expected_ops) and {key(r)+(r['operation'],) for r in ts}==expected_ops
    groups={}
    for r in ts:
        v=r['cuda_event_us']; assert len(v)==args['iters'] and all(x>0 for x in v)
        groups.setdefault(key(r)[1:]+(r['operation'],),[]).append(r)
    rows=[]
    for k,rs in sorted(groups.items()):
        assert len(rs)==ep
        maxima=sorted(max(r['cuda_event_us'][i] for r in rs) for i in range(args['iters']))
        rows.append(dict(backend=args['backend'],ep=ep,**dict(zip(fields[1:]+['operation'],k)),
            median_rank_max_us=statistics.median(maxima),p95_rank_max_us=maxima[min(len(maxima)-1,int(.95*len(maxima)))],
            mean_rank_max_us=statistics.mean(maxima),max_host_us_per_iteration=max(r['host_us_per_iteration'] for r in rs),
            max_process_cpu_core_equivalents=max(r['process_cpu_core_equivalents'] for r in rs)))
    with (root/'summary.csv').open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
    repeats={}
    for r in rows:
        k=tuple(r[f] for f in ['model','tokens_per_gpu','dispatch_dtype','routing','operation'])
        repeats.setdefault(k,[]).append(r['median_rank_max_us'])
    variations=[dict(zip(['model','tokens_per_gpu','dispatch_dtype','routing','operation'],k),
        repeat_median_us=statistics.median(v),repeat_cv=statistics.stdev(v)/statistics.mean(v) if len(v)>1 else None)
        for k,v in repeats.items()]
    (root/'repeatability.json').write_text(json.dumps(variations,indent=2)+'\n')
    status=dict(status='PASS',ep=ep,correctness_records=len(checks),operation_records=len(ts),
                cuda_event_samples=sum(len(r['cuda_event_us']) for r in ts),
                nic_windows=len(read(root,'nic-node*.jsonl')))
    if ep==8 and args['nic_iters'] and 4096 in args['tokens']:
        assert status['nic_windows']==(ep//4)*len(args['models'])*len(args['dtypes'])*len(args['routing'])*4
    (root/'validation.json').write_text(json.dumps(status,indent=2)+'\n'); print(json.dumps(status))

if __name__=='__main__':
    p=argparse.ArgumentParser(); p.add_argument('root'); summarize(p.parse_args().root)
