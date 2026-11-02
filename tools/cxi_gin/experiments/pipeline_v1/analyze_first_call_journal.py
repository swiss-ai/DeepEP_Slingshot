"""Summarize cold host calls; do not label them GPU/network latency."""
import argparse,json,statistics
from pathlib import Path

p=argparse.ArgumentParser();p.add_argument('gate',type=Path);gate=p.parse_args().gate
finished=json.loads((gate/'FINISHED.json').read_text())
assert finished['returncode']==0 and finished['qualification']['status']=='PASS'
pairs=[('buffer_create_enter','buffer_create_return'),
       ('correctness_fresh_enter','correctness_fresh_return'),
       ('correctness_combine_enter','correctness_combine_return'),
       ('correctness_cached_enter','correctness_cached_return')]
values=[];entries={}
for rank in range(8):
 rows=[json.loads(s) for s in (gate/('direct/ep/diagnostic-watch-rank%d.jsonl'%rank)).read_text().splitlines()]
 assert rows[0]['phase']=='observer_started' and rows[-1]['phase']=='observer_stopped'
 assert not any(r.get('diagnostic_code') for r in rows)
 for start,end in pairs:
  a=[r for r in rows if r['phase']==start];b=[r for r in rows if r['phase']==end]
  expected=2 if 'combine_' in start else 1
  assert len(a)==len(b)==expected
  for index,(x,y) in enumerate(zip(a,b)):
   elapsed=(y['monotonic_ns']-x['monotonic_ns'])/1e9;assert elapsed>=0
   values.append(dict(rank=rank,phase=start.removesuffix('_enter'),call=index,host_seconds=elapsed))
  if 'cached' in start:entries[rank]=a[0]['monotonic_ns']
groups={}
for r in values:groups.setdefault((r['phase'],r['call']),[]).append(r['host_seconds'])
summary=[dict(phase=k[0],call=k[1],min_seconds=min(v),median_seconds=statistics.median(v),max_seconds=max(v)) for k,v in groups.items()]
skew=[dict(node=node,cached_host_entry_spread_seconds=(max(entries[r] for r in range(4*node,4*node+4))-min(entries[r] for r in range(4*node,4*node+4)))/1e9) for node in range(2)]
out=dict(scope='Diagnostic cold host entry/return durations including JIT, API work and possible synchronization. Not GPU completion, steady-state or NIC transfer time. Clock differences compared only within a node.',
         gate=gate.name,qualified=True,per_rank=values,summary=summary,same_node_entry_skew=skew)
(gate/'first-call-analysis.json').write_text(json.dumps(out,indent=2)+'\n')
print(json.dumps(dict(gate=gate.name,summary=summary,same_node_entry_skew=skew),indent=2))
