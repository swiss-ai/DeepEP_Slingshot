"""Plot only complete three-repeat ordinary EP8 comparisons."""
import argparse
import csv
import json
import statistics
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

p=argparse.ArgumentParser();p.add_argument('job',type=Path);a=p.parse_args()
rows=list(csv.DictReader((a.job/'variant-analysis/repeats.csv').open()))
families=[('zero-rows','Rows\ninterval3'),('zero-packed','Packed\ninterval3'),
          ('rows-i16','Rows\ninterval16'),('packed-i16','Packed\ninterval16')]
records=[]
for family,label in families:
    for tokens in [4096,16384]:
        for operation in ['dispatch_fresh','combine']:
            selected=[r for r in rows if r['snapshot']=='source-zero-packed-v7' and
                r['variant']=='marker-zero' and r['experiment']==family and r['contexts']=='129' and
                r['model']=='v4flash' and int(r['tokens'])==tokens and r['dtype']=='fp8' and
                r['routing']=='mixed' and r['operation']==operation]
            assert len(selected)==3 and {r['repeat'] for r in selected}=={'1','2','3'},(family,tokens,operation)
            values=[float(r['median_ms']) for r in selected]
            records.append(dict(experiment=family,tokens=tokens,operation=operation,
                median_ms=statistics.median(values),min_ms=min(values),max_ms=max(values),
                gates=';'.join(r['gate'] for r in selected)))
fig,axes=plt.subplots(1,2,figsize=(11,4.6))
colors={'dispatch_fresh':'#2878b5','combine':'#dd8452'}
for ax,tokens in zip(axes,[4096,16384]):
    x=np.arange(len(families));width=.36
    for index,operation in enumerate(['dispatch_fresh','combine']):
        data=[next(r for r in records if r['experiment']==family and r['tokens']==tokens and
                   r['operation']==operation) for family,_ in families]
        values=np.array([r['median_ms'] for r in data])
        errors=np.array([[r['median_ms']-r['min_ms'] for r in data],
                         [r['max_ms']-r['median_ms'] for r in data]])
        bars=ax.bar(x+(index-.5)*width,values,width,yerr=errors,capsize=3,
                    color=colors[operation],label='Fresh FP8 dispatch' if index==0 else 'BF16 combine')
        ax.bar_label(bars,labels=['%.2f'%v for v in values],padding=4,fontsize=8)
        bound=tokens*(4320 if index==0 else 8256)/25e6
        ax.axhline(bound,color=colors[operation],linestyle='--',linewidth=1,alpha=.8)
    ax.set_xticks(x,[label for _,label in families],fontsize=9)
    ax.set_title('{:,} tokens per GPU'.format(tokens));ax.set_ylabel('Latency (ms)')
    ax.set_ylim(0,max(r['max_ms'] for r in records if r['tokens']==tokens)*1.14)
    ax.grid(axis='y',alpha=.15);ax.set_axisbelow(True)
fig.suptitle('DeepEP v2 direct CXI GIN — EP8 batching comparison',fontsize=13)
handles,labels=axes[0].get_legend_handles_labels()
fig.legend(handles,labels,loc='lower center',bbox_to_anchor=(.5,.105),ncol=2,frameon=False)
fig.text(.5,.055,'Three repeats; bars: median of rank-max CUDA medians; whiskers: repeat range. Tracing off.',ha='center',fontsize=8)
fig.text(.5,.02,'Dashed lines: RDMA payload / 25 GB/s only; relay, packet/control overhead and synchronization excluded.',ha='center',fontsize=8)
fig.tight_layout(rect=(0,.17,1,.95))
out=a.job/'figures';out.mkdir(exist_ok=True)
for suffix in ['pdf','png']:fig.savefig(out/('packed_dispatch_comparison.'+suffix),dpi=170)
(out/'packed_dispatch_comparison.json').write_text(json.dumps(dict(job=a.job.name,
    source='source-zero-packed-v7',contexts=129,forward_chunk=3,rows=records,
    scope='Same two-node allocation; qualified ordinary timing; no wire-level decomposition'),indent=2)+'\n')
print(out/'packed_dispatch_comparison.pdf')
