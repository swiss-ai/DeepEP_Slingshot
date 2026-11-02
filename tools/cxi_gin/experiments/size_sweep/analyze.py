"""Fit warmed end-to-end EP latency; slope is not intrinsic NIC bandwidth."""
import argparse,csv,json,statistics
from collections import defaultdict
from pathlib import Path
import numpy as np

def fit(x,y):
 x=np.asarray(x,float);y=np.asarray(y,float)
 slope,intercept=np.polyfit(x,y,1);pred=intercept+slope*x;ss=float(((y-y.mean())**2).sum())
 return dict(intercept_ms=float(intercept),slope_ms_per_MB=float(slope),incremental_effective_GBps=float(1/slope) if slope>0 else None,
             r_squared=1-float(((y-pred)**2).sum())/ss if ss else None,max_abs_residual_ms=float(abs(y-pred).max()))
def load(root):
 rows=[]
 for attempt in sorted((root/'results/results').glob('*size-sweep-repeat*')):
  record=json.loads((attempt/'FINISHED.json').read_text());assert record.get('qualification',{}).get('status')=='PASS',attempt
  trial=int(record['spec']['environment']['CXI_SWEEP_REPEAT']);base=attempt/'direct/ep'
  checks=[json.loads(s) for p in base.glob('correctness-rank*.jsonl') for s in p.read_text().splitlines()]
  times=[json.loads(s) for p in base.glob('timings-rank*.jsonl') for s in p.read_text().splitlines()]
  for n in range(2048,16385,2048):
   cs=[r for r in checks if r['tokens_per_gpu']==n];assert len(cs)==8 and all(r['status']=='PASS' for r in cs)
   assert {r['rank'] for r in cs}==set(range(8))
   assert len({r['dispatch_row_bytes'] for r in cs})==1
   # Unique remote-node payload is counted once per rail after deduplication.
   dispatch_bytes=max(r['unique_remote_node_rows']*r['dispatch_row_bytes'] for r in cs)
   combine_bytes=max(r['unique_remote_node_rows']*r['combine_row_bytes'] for r in cs)
   for op in ['dispatch_fresh','dispatch_cached','combine','cycle']:
    ts=[r for r in times if r['tokens_per_gpu']==n and r['operation']==op];assert len(ts)==8
    assert {r['rank'] for r in ts}==set(range(8));assert all(len(r['cuda_event_us'])==100 for r in ts)
    maxima=[max(r['cuda_event_us'][i] for r in ts)/1000 for i in range(100)]
    ms=statistics.median(maxima)
    numbytes=combine_bytes if op=='combine' else dispatch_bytes if op.startswith('dispatch') else dispatch_bytes+combine_bytes
    rows.append(dict(repeat=trial,tokens_per_rank=n,operation=op,median_rank_max_ms=ms,p95_rank_max_ms=float(np.percentile(maxima,95)),
        modeled_max_rail_bytes=numbytes,serialization_bound_ms=numbytes/25e6,payload_effective_GBps=numbytes/(ms*1e6),
        excess_over_serialization_ms=ms-numbytes/25e6))
 assert {r['repeat'] for r in rows}=={1,2,3} and len(rows)==3*8*4
 return rows

def main(root):
 root=Path(root);rows=load(root);out=root/'size-analysis';out.mkdir(exist_ok=True)
 with (out/'size-sweep.csv').open('w') as f:w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
 models={}
 for op in ['dispatch_fresh','dispatch_cached','combine']:
  rr=[r for r in rows if r['operation']==op]
  allfit=fit([r['modeled_max_rail_bytes']/1e6 for r in rr],[r['median_rank_max_ms'] for r in rr])
  repeats={str(i):fit([r['modeled_max_rail_bytes']/1e6 for r in rr if r['repeat']==i],[r['median_rank_max_ms'] for r in rr if r['repeat']==i]) for i in [1,2,3]}
  allfit['per_repeat']=repeats;allfit['intercept_repeat_range_ms']=[min(r['intercept_ms'] for r in repeats.values()),max(r['intercept_ms'] for r in repeats.values())]
  allfit['scope']='T = intercept + slope * max per-rail payload MB. Warm per-call intercept, not startup. Slope includes per-token packing/queue/signaling; not NIC DMA bandwidth. Repeat ranges are not confidence intervals.'
  models[op]=allfit
 (out/'latency-fits.json').write_text(json.dumps(models,indent=2)+'\n')
 import matplotlib
 matplotlib.use('Agg')
 import matplotlib.pyplot as plt
 fig,axes=plt.subplots(1,3,figsize=(15,4.2))
 for trial in [1,2,3]:
  rs=sorted([r for r in rows if r['repeat']==trial and r['operation']=='dispatch_fresh'],key=lambda r:r['tokens_per_rank'])
  x=np.array([r['tokens_per_rank']/1024 for r in rs]);y=np.array([r['median_rank_max_ms'] for r in rs]);ideal=np.array([r['serialization_bound_ms'] for r in rs])
  axes[0].plot(x,y,'o-',label='Repeat '+str(trial));axes[1].plot(x,y-ideal,'o-');axes[2].plot(x,[r['payload_effective_GBps'] for r in rs],'o-')
 axes[0].plot(x,ideal,'k--',label='Payload / 25 GB/s')
 m=models['dispatch_fresh'];bytes_=np.array([r['modeled_max_rail_bytes']/1e6 for r in rs])
 axes[0].plot(x,m['intercept_ms']+m['slope_ms_per_MB']*bytes_,color='gray',linestyle=':',label='Linear fit')
 axes[0].set_ylabel('Fresh dispatch latency (ms)');axes[1].set_ylabel('Latency above serialization bound (ms)');axes[2].set_ylabel('Payload / full dispatch time (GB/s)');axes[2].axhline(25,color='black',linestyle='--')
 for ax in axes:ax.set_xlabel('Tokens per rank (K = 1024)');ax.set_xticks(range(2,17,2));ax.grid(alpha=.25)
 axes[0].legend(fontsize=8);fig.suptitle('V4 Flash · EP8 · FP8 · direct CXI threshold completion · tracing off')
 fig.tight_layout();fig.savefig(out/'fp8-dispatch-size-sweep.pdf');fig.savefig(out/'fp8-dispatch-size-sweep.png',dpi=180);plt.close(fig)
 lines=['# EP8 FP8 token-size sweep','','All 24 size/repeat cases passed correctness. Three warmed runs on one node pair; fixed routing seed and fixed SM/context counts.','',
 '| Tokens/rank | Dispatch median (ms) | Range across repeats (ms) | Serialization bound (ms) | Effective payload GB/s |','|---:|---:|---:|---:|---:|']
 for n in range(2048,16385,2048):
  rr=[r for r in rows if r['tokens_per_rank']==n and r['operation']=='dispatch_fresh'];v=[r['median_rank_max_ms'] for r in rr];med=statistics.median(v)
  lines.append('| %d | %.4f | %.4f–%.4f | %.4f | %.3f |'%(n,med,min(v),max(v),rr[0]['serialization_bound_ms'],statistics.median([r['payload_effective_GBps'] for r in rr])))
 lines+=['','Linear fit: intercept %.4f ms; slope %.4f ms/MB; incremental effective throughput %.3f GB/s; R² %.4f.'%(m['intercept_ms'],m['slope_ms_per_MB'],m['incremental_effective_GBps'] or 0,m['r_squared'] or 0),'',m['scope'],'','Inspect residuals and repeat consistency before calling the gap fixed or bandwidth-limited. A size-dependent slope can reflect software per-token work as well as network throughput.']
 (out/'summary.md').write_text('\n'.join(lines)+'\n');print(out)
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('root');main(p.parse_args().root)
