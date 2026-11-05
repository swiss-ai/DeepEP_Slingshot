"""Per-rank local timeline and wait unions; overlap is never double-counted."""
import csv,gzip,json,sys
from pathlib import Path
from collections import defaultdict

def union(intervals):
    total=0;end=None
    for a,b in sorted(intervals):
        if end is None or a>end:total+=b-a
        elif b>end:total+=b-end
        end=b if end is None else max(end,b)
    return total

def main(root):
    root=Path(root);target=root/'analysis';target.mkdir(exist_ok=True);rows=[];stages=[]
    for path in sorted((root/'direct/ep/device-traces').glob('*iteration*.json.gz')):
        with gzip.open(str(path),'rt') as f:r=json.load(f)
        events=r['events'];group=defaultdict(list)
        for e in events:group[e['event']].append(e)
        for kind,ev in sorted(group.items()):
            stages.append(dict(rank=r['rank'],operation=r['operation'],iteration=r['iteration'],event=kind,count=len(ev),sum_lane_ms=sum(e['end_ns']-e['start_ns'] for e in ev)/1e6,rank_union_ms=union([(e['start_ns'],e['end_ns']) for e in ev])/1e6))
        # A role interval is one warp's lifetime. Choose the latest-finishing
        # sender/forwarder; subtract only waits on that same warp, clipped to it.
        origins=min(e['start_ns'] for e in events)
        for role in ([103,104] if r['operation']=='dispatch_fresh' else [132,133]):
            candidates=group[role];assert candidates,role;last=max(candidates,key=lambda e:e['end_ns'])
            waiting=[e for e in events if e['block']==last['block'] and e['thread']//32==last['thread']//32 and e['event'] in {200,202,207,208,105,134,136,138}]
            spans=[(max(last['start_ns'],e['start_ns']),min(last['end_ns'],e['end_ns'])) for e in waiting if e['end_ns']>last['start_ns'] and e['start_ns']<last['end_ns']]
            rows.append(dict(rank=r['rank'],operation=r['operation'],iteration=r['iteration'],role=role,block=last['block'],warp=last['thread']//32,cuda_event_ms=r['cuda_event_us']/1000,role_start_ms=(last['start_ns']-origins)/1e6,role_end_ms=(last['end_ns']-origins)/1e6,role_duration_ms=(last['end_ns']-last['start_ns'])/1e6,wait_union_ms=union(spans)/1e6))
    for name,data in [('critical-role-waits.csv',rows),('stage-observations.csv',stages)]:
        assert data
        with (target/name).open('w') as f:w=csv.DictWriter(f,fieldnames=list(data[0]));w.writeheader();w.writerows(data)
    (target/'README.txt').write_text('Local GPU timestamps only. Sum-lane durations are parallel work, not additive wall time. Rank unions and latest-role wait unions overlap with other roles. CT observation is not wire time. Compare trace-disabled timers and separate ordinary builds before interpreting overhead.\n')
if __name__=='__main__':main(sys.argv[1])
