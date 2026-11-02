"""Plot measured call/kernel/launch scopes separately; never invent NIC timing."""
import argparse,csv,json,re,statistics
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

def union(intervals):
 end=None;total=0
 for a,b in sorted(intervals):
  total+=max(0,b-max(a,end if end is not None else a));end=max(b,end if end is not None else b)
 return total

def main():
 p=argparse.ArgumentParser();p.add_argument('lease',type=Path);p.add_argument('output',type=Path);a=p.parse_args();a.output.mkdir(parents=True,exist_ok=True)
 base=a.lease/'results/02-ep4k-profile';ep=base/'direct/ep'
 timings=list(csv.DictReader((ep/'summary.csv').open()));kernels=list(csv.DictReader((base/'profile-kernels.csv').open()))
 checks=[json.loads(x) for f in ep.glob('correctness-rank*.jsonl') for x in f.read_text().splitlines()]
 rows=[]
 for model in ['v4flash','qwen3','minimax']:
  for op in ['dispatch_fresh','combine']:
   t=next(x for x in timings if x['model']==model and x['operation']==op)
   groups={'hybrid':[],'epilogue':[]};launch=[]
   for x in kernels:
    if x['model']==model and x['operation']==op:
     groups['hybrid' if 'hybrid_' in x['kernel'] else 'epilogue'].append(float(x['median_us'])/1000)
   for rank in range(8):
    events=json.loads((ep/'profiles'/f'{model}-uniform-{op}-rank{rank}.json').read_text())['traceEvents']
    markers=[e for e in events if e.get('ph')=='X' and e.get('name','').startswith(f'ep4k/{op}/iteration')]
    samples=[]
    for marker in markers:
     lo=marker['ts'];hi=lo+marker['dur']
     calls=[e for e in events if e.get('ph')=='X' and e.get('cat') in ('cuda_runtime','cuda_driver') and 'launchkernel' in e.get('name','').lower() and lo<=e['ts']<hi]
     assert calls,(model,op,rank)
     samples.append(union([(e['ts'],e['ts']+e['dur']) for e in calls]))
    launch.append(statistics.median(samples))
   cs=[x for x in checks if x['model']==model]
   b=max(x['unique_remote_node_rows']*x['hidden']*(1 if op=='dispatch_fresh' else 2) for x in cs)
   rows.append(dict(model=model,operation=op,call_ms=float(t['median_rank_max_us'])/1000,network_floor_ms=b/25e6,hybrid_ms=statistics.median(groups['hybrid']),epilogue_ms=statistics.median(groups['epilogue']),launch_api_us=statistics.median(launch),launch_api_min_rank_us=min(launch),launch_api_max_rank_us=max(launch)))
 plt.rcParams.update({'font.family':'DejaVu Sans','font.size':11,'axes.spines.top':False,'axes.spines.right':False,'axes.titleweight':'bold'})
 fig=plt.figure(figsize=(14,10.5),facecolor='#f8fafc');gs=fig.add_gridspec(2,2,height_ratios=[1.5,1],hspace=.53,wspace=.32)
 ax=fig.add_subplot(gs[0,0]);bx=fig.add_subplot(gs[0,1]);cx=fig.add_subplot(gs[1,:])
 labels=[{'v4flash':'V4 Flash','qwen3':'Qwen3','minimax':'MiniMax'}[r['model']]+' · '+('FP8 dispatch' if r['operation']=='dispatch_fresh' else 'BF16 combine') for r in rows];y=np.arange(6)
 ax.barh(y,[r['call_ms'] for r in rows],color='#2463a7',height=.62,label='Measured full call')
 ax.scatter([r['network_floor_ms'] for r in rows],y,marker='|',s=300,color='#151515',linewidths=2.5,label='Ideal payload / 25 GB/s')
 for i,r in enumerate(rows):ax.text(r['call_ms']+.07,i,f"{r['call_ms']:.3f}",va='center',fontsize=10)
 ax.set(yticks=y,yticklabels=labels,xlim=(0,5.4),xlabel='Milliseconds',title='A  Actual latency vs ideal network floor');ax.invert_yaxis();ax.legend(loc='upper left',bbox_to_anchor=(0,-.19),fontsize=9,frameon=False);ax.grid(axis='x',alpha=.15);ax.set_axisbelow(True)
 bx.barh(y,[r['hybrid_ms'] for r in rows],color='#db8b32',height=.62,hatch='//',label='Hybrid kernel: network + NVLink + waits')
 bx.barh(y,[r['epilogue_ms'] for r in rows],left=[r['hybrid_ms'] for r in rows],color='#369d8b',height=.62,label='GPU copy / reduction epilogue')
 for i,r in enumerate(rows):bx.text(r['hybrid_ms']+r['epilogue_ms']+.06,i,f"{r['hybrid_ms']:.2f} + {r['epilogue_ms']:.2f}",va='center',fontsize=9)
 bx.set(yticks=y,yticklabels=['Dispatch','Combine']*3,xlim=(0,5.45),xlabel='Profiled kernel milliseconds',title='B  GPU kernel breakdown');bx.invert_yaxis();bx.legend(loc='upper left',bbox_to_anchor=(0,-.19),fontsize=8,frameon=False);bx.grid(axis='x',alpha=.15);bx.set_axisbelow(True)
 xx=np.arange(6);vals=[r['launch_api_us'] for r in rows]
 cx.bar(xx,vals,color='#8060ae',width=.58)
 for i,v in enumerate(vals):cx.text(i,v+.5,f'{v:.1f} µs',ha='center',fontsize=10)
 cx.set(xticks=xx,xticklabels=[s.replace(' · ','\n') for s in labels],ylabel='Microseconds',ylim=(0,max(vals)*1.3+1),title='C  Host kernel-launch API time — overlaps GPU work; not additive to A or B')
 cx.grid(axis='y',alpha=.15);cx.set_axisbelow(True)
 fig.suptitle('DeepEP v2 direct CXI GIN · EP8 latency decomposition',x=.06,ha='left',fontsize=20,fontweight='bold',y=.975)
 fig.text(.06,.935,'2 × GH200 nodes  |  4,096 tokens/GPU  |  Job 3781109  |  FP8 dispatch → BF16 combine',fontsize=11,color='#475569')
 fig.subplots_adjust(left=.17,right=.96,top=.87,bottom=.17)
 fig.text(.06,.10,'Real network-transfer time is NOT isolated in these traces. The orange kernel includes NIC DMA, GPU submission,\ncompletion polling, NVLink forwarding and synchronization. Black marks are activation-only lower bounds, not measurements.',fontsize=10,color='#303947')
 fig.text(.06,.045,'A: unprofiled rank-max median (50 iterations). B/C: median of per-rank medians (5 profiled iterations, 8 ranks).\nProfiling changes timing; stacked kernel medians are illustrative, not a reconstructed critical path. Quantization / expert GEMM excluded.',fontsize=9,color='#64748b')
 for ext in ['png','pdf','svg']:fig.savefig(a.output/f'ep8_latency_decomposition.{ext}',dpi=180,facecolor=fig.get_facecolor())
 with (a.output/'decomposition.csv').open('w') as f:
  w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
 print(json.dumps(rows,indent=2))
if __name__=='__main__':main()
