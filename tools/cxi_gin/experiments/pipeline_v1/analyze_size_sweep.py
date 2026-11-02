"""Fit warmed end-to-end EP latency; slope is not intrinsic NIC bandwidth."""
import argparse,ast,csv,hashlib,json,re,statistics,tarfile
from collections import defaultdict
from pathlib import Path
import numpy as np

def fit(x,y):
 x=np.asarray(x,float);y=np.asarray(y,float)
 slope,intercept=np.polyfit(x,y,1);pred=intercept+slope*x;ss=float(((y-y.mean())**2).sum())
 return dict(intercept_ms=float(intercept),slope_ms_per_MB=float(slope),incremental_effective_GBps=float(1/slope) if slope>0 else None,
             r_squared=1-float(((y-pred)**2).sum())/ss if ss else None,max_abs_residual_ms=float(abs(y-pred).max()))
def load(root, snapshot, family):
 manifest=json.loads((snapshot/'manifest.json').read_text())
 for name,digest in manifest['files'].items():
  assert hashlib.sha256((snapshot/name).read_bytes()).hexdigest()==digest,name
 with tarfile.open(snapshot/'DeepEP.tar.gz') as archive:
  member=next(m for m in archive if m.name.endswith('/common/layout.cuh'))
  layout_sha=hashlib.sha256(archive.extractfile(member).read()).hexdigest()
 assert layout_sha=='773cb68bff98dc0a91ec7113e7a7fc9a456b55dcb44b9cf52e2d62c08578b3b1','Re-audit changed TokenLayout'
 text=(snapshot/'backend/tests/ep_benchmark.py').read_text()
 function=next(n for n in ast.parse(text).body if isinstance(n,ast.FunctionDef) and n.name=='fp8')
 fp8_sha=hashlib.sha256(ast.get_source_segment(text,function).encode()).hexdigest()
 assert fp8_sha=='c1f32fca05fee55a36ba2cf54d74c77ba9d5b7b5c3462735c415fbda0ac8049d','Re-audit changed FP8 layout'
 align32=lambda n:((n+31)//32)*32
 rows=[];configuration=None;gate_names=[];digests=set();repeats=set()
 for attempt in sorted((root/'results/results').glob('*size-sweep-repeat*')):
  match=re.fullmatch(r'[0-9][0-9a-z]*-(.+)-repeat([123])',attempt.name)
  if not match or match[1]!=family:continue
  record=json.loads((attempt/'FINISHED.json').read_text());env=record['spec']['environment']
  assert record['returncode']==0 and record.get('qualification',{}).get('status')=='PASS',attempt
  assert Path(record['spec']['snapshot']).name==snapshot.name
  assert record['spec']['qualification']=='ep' and env.get('CXI_DEVICE_TRACE','0')=='0'
  assert env['CXI_EP_MODELS']=='v4flash' and env['CXI_EP_DTYPES']=='fp8' and env['CXI_EP_ROUTING']=='mixed'
  assert set(map(int,env['CXI_EP_TOKENS'].split()))==set(range(2048,16385,2048))
  assert env['CXI_EP_ITERS']=='100' and env['CXI_EP_WARMUP']=='20' and env['CXI_EP_SEEDS']=='1'
  config={k:env.get(k,'0') for k in ['CXI_VARIANT','CXI_EP_SMS','CXI_EP_CONTEXTS','CXI_EP_PACK_ROWS','CXI_EP_UPDATE_INTERVAL','CXI_EP_FORWARD_CHUNK','CXI_EP_MERGE_FINAL_TAIL']}
  if configuration is None:configuration=config
  assert config==configuration
  trial=int(match[2]);assert trial not in repeats;repeats.add(trial);gate_names.append(attempt.name)
  reports=list((attempt/'compiler-reports').rglob('*.txt'));assert reports
  assert all('-DCXI_EP_PACK_ROWS='+config['CXI_EP_PACK_ROWS']+' ' in p.read_text() and
             '-DCXI_EP_UPDATE_INTERVAL='+config['CXI_EP_UPDATE_INTERVAL']+' ' in p.read_text() for p in reports)
  base=attempt/'direct/ep';checks=[];times=[]
  for rank in range(8):
   provenance=json.loads((base/('manifest-rank%d.jsonl'%rank)).read_text())
   assert provenance['script_hashes']['ep_benchmark.py']==manifest['files']['backend/tests/ep_benchmark.py']
   digests.add(provenance['deployed_source_sha256'])
   cc=[json.loads(s) for s in (base/('correctness-rank%d.jsonl'%rank)).read_text().splitlines()]
   tt=[json.loads(s) for s in (base/('timings-rank%d.jsonl'%rank)).read_text().splitlines()]
   assert len(cc)==8 and len(tt)==32 and all(r['rank']==rank for r in cc+tt)
   assert all(r['model']=='v4flash' and r['hidden']==4096 and r['topk']==6 and r['experts']==256 and
              r['dispatch_dtype']=='fp8' and r['combine_dtype']=='bf16' and r['drop_every']==0 and r['gin_type']=='6' and
              r['ep']==8 and r['seed']==1 and r['routing']=='mixed' and
              r['actual_sms']==int(config['CXI_EP_SMS']) and r['qps']==int(config['CXI_EP_CONTEXTS']) and
              r['allocated_contexts']==int(config['CXI_EP_CONTEXTS']) and
              r['packed_remote_rows']==bool(int(config['CXI_EP_PACK_ROWS'])) and
              r['progress_update_interval']==int(config['CXI_EP_UPDATE_INTERVAL']) and
              r['forward_chunk']==int(config['CXI_EP_FORWARD_CHUNK']) for r in cc)
   checks+=cc;times+=tt
  for n in range(2048,16385,2048):
   cs=[r for r in checks if r['tokens_per_gpu']==n];assert len(cs)==8 and all(r['status']=='PASS' for r in cs)
   assert {r['rank'] for r in cs}==set(range(8))
   dispatch_row_bytes=align32(4096)+align32((4096//128)*4)+align32(8*6+4*(1+6))
   combine_row_bytes=align32(4096*2)+align32(8*6)
   dispatch_bytes=max(r['unique_remote_node_rows']*dispatch_row_bytes for r in cs)
   combine_bytes=max(r['unique_remote_node_rows']*combine_row_bytes for r in cs)
   for op in ['dispatch_fresh','dispatch_cached','combine','cycle']:
    ts=[r for r in times if r['tokens_per_gpu']==n and r['operation']==op];assert len(ts)==8
    assert {r['rank'] for r in ts}==set(range(8));assert all(len(r['cuda_event_us'])==100 for r in ts)
    assert all(np.isfinite(v) and v>0 for r in ts for v in r['cuda_event_us'])
    maxima=[max(r['cuda_event_us'][i] for r in ts)/1000 for i in range(100)]
    assert all(np.isfinite(v) and v>0 for v in maxima)
    ms=statistics.median(maxima)
    numbytes=combine_bytes if op=='combine' else dispatch_bytes if op.startswith('dispatch') else dispatch_bytes+combine_bytes
    rows.append(dict(repeat=trial,tokens_per_rank=n,operation=op,median_rank_max_ms=ms,p95_rank_max_ms=float(np.percentile(maxima,95)),
        modeled_max_rail_bytes=numbytes,serialization_bound_ms=numbytes/25e6,payload_effective_GBps=numbytes/(ms*1e6),
        excess_over_serialization_ms=ms-numbytes/25e6))
 assert repeats=={1,2,3} and len(rows)==3*8*4 and len(digests)==1
 return rows,dict(source=snapshot.name,configuration=configuration,gates=gate_names,
  token_layout_sha256=layout_sha,fp8_function_sha256=fp8_sha,deployed_source_sha256=next(iter(digests)),
  byte_model='32-byte aligned hidden+FP32 group scales+TokenLayout metadata; unique remote-node rows counted once per rail. Excludes NIC protocol/control traffic.')

def main(root,snapshot,family):
 root=Path(root);rows,provenance=load(root,Path(snapshot),family);out=root/'size-analysis';out.mkdir(exist_ok=True)
 (out/'provenance.json').write_text(json.dumps(provenance,indent=2)+'\n')
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
 axes[0].legend(fontsize=8);fig.suptitle('V4 Flash · EP8 · FP8 · direct CXI · '+provenance['source']+' · tracing off')
 fig.tight_layout();fig.savefig(out/'fp8-dispatch-size-sweep.pdf');fig.savefig(out/'fp8-dispatch-size-sweep.png',dpi=180);plt.close(fig)
 lines=['# EP8 FP8 token-size sweep','','All 24 size/repeat cases passed correctness. Three warmed runs on one node pair; fixed routing seed and fixed SM/context counts.','',
 '| Tokens/rank | Dispatch median (ms) | Range across repeats (ms) | Serialization bound (ms) | Effective payload GB/s |','|---:|---:|---:|---:|---:|']
 for n in range(2048,16385,2048):
  rr=[r for r in rows if r['tokens_per_rank']==n and r['operation']=='dispatch_fresh'];v=[r['median_rank_max_ms'] for r in rr];med=statistics.median(v)
  lines.append('| %d | %.4f | %.4f–%.4f | %.4f | %.3f |'%(n,med,min(v),max(v),rr[0]['serialization_bound_ms'],statistics.median([r['payload_effective_GBps'] for r in rr])))
 lines+=['','Linear fit: intercept %.4f ms; slope %.4f ms/MB; incremental effective throughput %.3f GB/s; R² %.4f.'%(m['intercept_ms'],m['slope_ms_per_MB'],m['incremental_effective_GBps'] or 0,m['r_squared'] or 0),'',m['scope'],'','Inspect residuals and repeat consistency before calling the gap fixed or bandwidth-limited. A size-dependent slope can reflect software per-token work as well as network throughput.']
 (out/'summary.md').write_text('\n'.join(lines)+'\n');print(out)
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('root');p.add_argument('snapshot');p.add_argument('--family',required=True);a=p.parse_args();main(a.root,a.snapshot,a.family)
