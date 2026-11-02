"""Validate eight ranks and export Chrome/Perfetto traces and inclusive stats.

No sum over concurrent threads is presented as wall time. Cross-rank flow
timestamps use calibrated estimates with explicitly reported uncertainty.
"""
import argparse
import csv
import gzip
import json
import statistics as st
import html
from collections import defaultdict
from pathlib import Path
from events import EVENTS

def union(intervals):
    total=0;end=None
    for a,b in sorted(intervals):
        if b<a:raise ValueError('negative duration')
        total+=max(0,b-max(a,end if end is not None else a));end=max(b,end if end is not None else b)
    return total

def alignment(manifest):
    endpoints=[]
    for key in ('pre','post'):
        c=manifest['clock_'+key];g=manifest['gpu_clock_'+key]['best']
        lo=g['host_lower_ns']-g['gpu_ns']-c['offset_upper_ns']
        hi=g['host_upper_ns']-g['gpu_ns']-c['offset_lower_ns']
        assert hi>=lo
        endpoints.append((lo,hi))
    lo=min(x[0] for x in endpoints);hi=max(x[1] for x in endpoints)
    return {'gpu_to_rank0_ns':(lo+hi)//2,'alignment_uncertainty_ns':(hi-lo)//2,
            'scope':'pre/post calibration envelope; unmeasured clock drift within window is not proven bounded'}

def validate_capture(c):
    assert c['correctness']=='PASS' and c['stats']['overflow']==0
    ids={e['event'] for e in c['events']}
    assert {100,101,102,103,104,105,106,111,112,120,121,200,201,202,203,204,206}<=ids,('missing stages',ids)
    for e in c['events']:assert e['end_ns']>=e['start_ns']>0 and e['event'] in EVENTS
    names=[x[0] for x in c['host_events']]
    assert names[0]=='dispatch_enter' and names[-1]=='dispatch_exit',names
    assert all(b[1]>=a[1] for a,b in zip(c['host_events'],c['host_events'][1:]))

def analyze(base,out):
    out.mkdir(parents=True,exist_ok=True);manifests={}
    for rank in range(8):
        assert (base/f'DONE-rank{rank}').read_text().strip()=='PASS'
        manifests[rank]=json.loads((base/f'manifest-rank{rank}.json').read_text())
        assert manifests[rank]['rank']==rank and manifests[rank]['gin_type']=='6'
    align={r:alignment(m) for r,m in manifests.items()}
    samples=[];stats=[];chrome=[];host_stats=[];counts=defaultdict(int);overview=[]
    for path in sorted(base.glob('dispatch-rank*-iteration*.json.gz')):
        with gzip.open(path,'rt') as f:c=json.load(f)
        validate_capture(c);rank=c['rank'];iteration=c['iteration'];m=manifests[rank];counts[rank]+=1
        groups=defaultdict(list)
        payloads=[x for x in c['events'] if x['event']==111]
        assert len(payloads)==m['remote_tokens'],('token put count mismatch',rank,len(payloads),m['remote_tokens'])
        packed=m['hidden']+((m['hidden']//128*4+31)//32*32)+((12*m['topk']+4+31)//32*32)
        # Nested GIN events may include control traffic. The exact activation
        # put count is checked against event111, not all GIN calls.
        start=min(x['start_ns'] for x in payloads);end=max(x['end_ns'] for x in payloads)
        baseline=st.median(m['disabled_before']['cuda_event_us']+m['disabled_after']['cuda_event_us'])
        original_path=base.parents[1]/'original-control/direct/ep'/f'timings-rank{rank}.jsonl'
        original=[json.loads(l) for l in original_path.read_text().splitlines()]
        original=next(x for x in original if x['model']=='v4flash' and x['operation']=='dispatch_fresh')
        assert original['route_sha256']==m['route_sha256']
        original_us=st.median(original['cuda_event_us'])
        samples.append(dict(rank=rank,iteration=iteration,cuda_event_us=c['cuda_event_us'],disabled_median_us=baseline,
                            original_control_median_us=original_us,disabled_to_original_ratio=baseline/original_us,
                            instrumentation_ratio=c['cuda_event_us']/baseline,remote_token_puts=len(payloads),
                            packed_remote_bytes=len(payloads)*packed,payload_issue_span_us=(end-start)/1000,
                            issue_window_GBps=len(payloads)*packed/(end-start),
                            alignment_uncertainty_us=align[rank]['alignment_uncertainty_ns']/1000))
        for e in c['events']:
            groups[e['event']].append(e)
            chrome.append(dict(name=EVENTS[e['event']],cat='GPU inclusive',ph='X',pid=rank,
                tid=f"GPU block{e['block']} warp{e['thread']//32} lane{e['thread']%32}",
                ts=(e['start_ns']+align[rank]['gpu_to_rank0_ns'])/1000,dur=(e['end_ns']-e['start_ns'])/1000,
                args=dict(iteration=iteration,aux0=e['aux0'],aux1=e['aux1'],sm=e['sm'],alignment_uncertainty_us=align[rank]['alignment_uncertainty_ns']/1000)))
        for code,es in groups.items():
            ds=[(x['end_ns']-x['start_ns'])/1000 for x in es]
            stats.append(dict(rank=rank,iteration=iteration,event=EVENTS[code],count=len(es),median_us=st.median(ds),max_us=max(ds),
                inclusive_thread_sum_us=sum(ds),union_all_threads_us=union([(x['start_ns'],x['end_ns']) for x in es])/1000))
        if iteration==1:
            # A readable overview uses one representative late-finishing warp
            # per role. The full Perfetto export retains every recorded lane.
            for code in (101,102,103,104,106,120,121):
                es=groups.get(code,[])
                if es:
                    e=max(es,key=lambda x:x['end_ns'])
                    overview.append(dict(rank=rank,name=EVENTS[code],start=(e['start_ns']+align[rank]['gpu_to_rank0_ns'])/1000,
                        end=(e['end_ns']+align[rank]['gpu_to_rank0_ns'])/1000,block=e['block'],thread=e['thread']))
        host_offset=(m['clock_pre']['offset_lower_ns']+m['clock_pre']['offset_upper_ns'])/2
        for a,b in zip(c['host_events'],c['host_events'][1:]):
            name=a[0]+' -> '+b[0];duration=(b[1]-a[1])/1000
            host_stats.append(dict(rank=rank,iteration=iteration,stage=name,duration_us=duration))
            chrome.append(dict(name=name,cat='Host boundary interval',ph='X',pid=rank,tid='CPU',ts=(a[1]-host_offset)/1000,dur=duration,args={'iteration':iteration}))
    assert len(set(counts.values()))==1 and set(counts)==set(range(8)),dict(counts)
    assert all(counts[r]==len(manifests[r]['captures']) for r in range(8)),dict(counts)
    origin=min(x['ts'] for x in chrome)
    for e in chrome:e['ts']-=origin
    for name,rows in [('capture-summary.csv',samples),('gpu-inclusive-stages.csv',stats),('host-stages.csv',host_stats)]:
        with (out/name).open('w') as f:
            w=csv.DictWriter(f,fieldnames=rows[0]);w.writeheader();w.writerows(rows)
    with gzip.open(out/'all-eight-ranks.perfetto.json.gz','wt') as f:
        json.dump({'traceEvents':chrome,'displayTimeUnit':'us','metadata':{'clock_alignment':align,'warning':'Intervals are inclusive and overlap. Issue-window rate is NOT NIC-active throughput.'}},f)
    # Preserve raw NIC timestamp intervals. No inferred association to a GPU
    # until the job's GPU/NIC mapping has been checked against resource logs.
    nic=[]
    for p in sorted(base.glob('nic-node*.jsonl')):
        records=[json.loads(l) for l in p.read_text().splitlines()]
        keys=set(k for r in records for k in r['counters'])
        for key in keys:
            points=[r['counters'][key] for r in records if key in r['counters']]
            unique={x['timestamp']:x['value'] for x in points}
            ts=sorted(unique)
            for a,b in zip(ts,ts[1:]):
                delta=unique[b]-unique[a]
                if b>a and delta>=0:nic.append(dict(node=p.stem,key=key,counter_start=a,counter_end=b,seconds=b-a,octets=delta,GBps=delta/(b-a)/1e9))
    if nic:
        with (out/'nic-observed-intervals.csv').open('w') as f:
            w=csv.DictWriter(f,fieldnames=nic[0]);w.writeheader();w.writerows(nic)
    verdict=dict(status='PASS',ranks=8,captures_per_rank=dict(counts),clock_alignment=align,
        instrumentation_ratio_median=st.median(x['instrumentation_ratio'] for x in samples),
        nic_intervals=len(nic),limitations=['GPU spans inclusive and concurrent, not additive','Full tracing perturbs timing; inspect overhead ratio','NIC interval rates include protocol/control; no DMA-active occupancy measurement','No exact cross-rank causal ordering below clock uncertainty','Fresh FP8 dispatch only; combine instrumentation is a separate follow-up'])
    verdict['low_perturbation_diagnostic']=max(x['instrumentation_ratio'] for x in samples)<=1.2 and max(x['disabled_to_original_ratio'] for x in samples)<=1.2
    verdict['overhead_policy']='Above 20% overhead, use full traces to locate dependencies, not to assign baseline milliseconds; add targeted lower-overhead captures before quantitative attribution.'
    if overview:
        lo=min(x['start'] for x in overview);hi=max(x['end'] for x in overview);scale=1000/max(hi-lo,1)
        colors=['#64748b','#eab308','#f97316','#2563eb','#dc2626','#059669','#9333ea'];names=list(dict.fromkeys(x['name'] for x in overview))
        svg=['<svg viewBox="0 0 1300 1600" xmlns="http://www.w3.org/2000/svg">']
        for x in overview:
            line=x['rank']*8+names.index(x['name']);y=40+line*24
            title=html.escape(f"rank {x['rank']} {x['name']}: {x['end']-x['start']:.3f} us; block {x['block']} thread {x['thread']}")
            svg.append(f'<text x="0" y="{y+13}" font-size="11">r{x["rank"]} {html.escape(x["name"])}</text><rect x="{280+(x["start"]-lo)*scale:.3f}" y="{y}" width="{max(.5,(x["end"]-x["start"])*scale):.3f}" height="17" fill="{colors[names.index(x["name"])]}"><title>{title}</title></rect>')
        svg.append('</svg>')
        (out/'overview.html').write_text('<!doctype html><meta charset="utf-8"><title>EP8 dispatch trace</title><h1>Eight-rank dispatch trace: capture 1</h1><p>Representative latest-finishing warp per role, not an additive decomposition. Hover bars for durations. Full lane events are in the Perfetto trace. Clock alignment and tracing overhead are in validation.json.</p><p>Horizontal range: '+f'{hi-lo:.3f} microseconds. All ranks share the estimated rank-0 time axis.</p>'+''.join(svg))
    (out/'validation.json').write_text(json.dumps(verdict,indent=2)+'\n')
    return verdict

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('input',type=Path);p.add_argument('output',type=Path);a=p.parse_args()
    print(json.dumps(analyze(a.input,a.output),indent=2))
