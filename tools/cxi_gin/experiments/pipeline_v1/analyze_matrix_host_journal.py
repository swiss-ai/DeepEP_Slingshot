"""Pair host API phases by fixture; incomplete runs remain explicitly incomplete."""
import argparse,collections,json,statistics
from pathlib import Path

p=argparse.ArgumentParser();p.add_argument('gate',type=Path);args=p.parse_args()
keys=['model','tokens','dtype','routing','seed']
pairs={'buffer_create_enter':'buffer_create_return',
       'correctness_fresh_enter':'correctness_fresh_return',
       'correctness_combine_enter':'correctness_combine_return',
       'correctness_cached_enter':'correctness_cached_return'}
reverse={v:k for k,v in pairs.items()}
result=[];missing=[];entries=collections.defaultdict(dict)
finished=args.gate/'FINISHED.json'
verdict=json.loads(finished.read_text()) if finished.exists() else {}
qualified=verdict.get('returncode')==0 and verdict.get('qualification',{}).get('status')=='PASS'
for rank in range(8):
 rows=[json.loads(s) for s in (args.gate/('direct/ep/diagnostic-watch-rank%d.jsonl'%rank)).read_text().splitlines()]
 pending={}
 for row in rows:
  phase=row['phase'];fixture=tuple(row.get(k) for k in keys)
  if phase in pairs:
   identity=(fixture,phase,row.get('floating') if 'combine_' in phase else None)
   assert identity not in pending
   pending[identity]=row
   if 'cached_' in phase:entries[fixture][rank]=row['monotonic_ns']
  elif phase in reverse:
   start=reverse[phase];identity=(fixture,start,row.get('floating') if 'combine_' in start else None)
   before=pending.pop(identity)
   elapsed=(row['monotonic_ns']-before['monotonic_ns'])/1e9;assert elapsed>=0
   result.append(dict(zip(keys,fixture),rank=rank,phase=start[:-6],floating=identity[2],host_seconds=elapsed))
 for (fixture,phase,floating),row in pending.items():
  missing.append(dict(zip(keys,fixture),rank=rank,phase=phase,floating=floating,reason='entry has no recorded return'))
 if qualified:
  assert not pending and rows[-1]['phase']=='observer_stopped'
  assert not any(x.get('diagnostic_code') for x in rows)
groups=collections.defaultdict(list)
for row in result:groups[tuple(row[k] for k in keys)+ (row['phase'],row['floating'])].append(row)
summary=[]
for key,records in groups.items():
 values=[r['host_seconds'] for r in records]
 summary.append(dict(zip(keys,key[:5]),phase=key[5],floating=key[6],ranks=len(records),
  min_seconds=min(values),median_seconds=statistics.median(values),max_seconds=max(values)))
skew=[]
for fixture,rank_times in entries.items():
 for node in range(2):
  values=[rank_times[r] for r in range(node*4,node*4+4) if r in rank_times]
  if len(values)==4:skew.append(dict(zip(keys,fixture),node=node,seconds=(max(values)-min(values))/1e9))
out=dict(gate=args.gate.name,qualified=qualified,scope='Host API entry/return including JIT, launch and possible synchronization; not isolated GPU or wire latency. Entry skew compared only within one node.',
 per_rank=result,summary=summary,incomplete_calls=missing,same_node_cached_entry_skew=skew)
(args.gate/'matrix-host-analysis.json').write_text(json.dumps(out,indent=2)+'\n')
print(json.dumps(dict(gate=args.gate.name,qualified=qualified,completed_host_calls=len(result),incomplete_calls=len(missing),
 selected=[r for r in summary if r['tokens']==4096 and r['dtype']=='bf16' and r['routing']=='mixed' and r['seed']==1]),indent=2))
