"""Compare qualified 129/257-context traces with matched ordinary EP timings.

Trace intervals overlap and include observer overhead. The per-rank tables use
each rank's latest-finishing warp for each role, not an inferred wire timeline.
"""
import argparse, csv, json, math, statistics
from pathlib import Path

def read(path):
    with path.open() as file:
        return list(csv.DictReader(file))

def write(path, rows):
    with path.open('w') as file:
        writer=csv.DictWriter(file,fieldnames=list(rows[0]))
        writer.writeheader();writer.writerows(rows)

def main():
    p=argparse.ArgumentParser();p.add_argument('job',type=Path)
    p.add_argument('--gates',nargs=2,required=True)
    p.add_argument('--families',nargs=2,required=True)
    a=p.parse_args();ordinary=read(a.job/'variant-analysis/repeats.csv')
    summaries=[];per_rank=[];seen=set()
    for gate_name,family in zip(a.gates,a.families):
        gate=a.job/'results/results'/gate_name
        finish=json.loads((gate/'FINISHED.json').read_text())
        assert finish['returncode']==0 and finish['qualification']['device_traces']=='PASS'
        env=finish['spec']['environment'];contexts=int(env['CXI_EP_CONTEXTS'])
        assert contexts in (129,257) and contexts not in seen;seen.add(contexts)
        assert Path(finish['spec']['snapshot']).name=='source-packed-trace-v2'
        assert env['CXI_EP_PACK_ROWS']=='1' and env['CXI_EP_UPDATE_INTERVAL']=='16'
        assert env['CXI_EP_SMS']=='64'
        assert env['CXI_EP_TOKENS']=='4096' and env['CXI_EP_MODELS']=='v4flash'
        assert env['CXI_EP_DTYPES']=='fp8' and env['CXI_EP_ROUTING']=='mixed'
        captures=int(env['CXI_TRACE_CAPTURES'])
        timings=read(gate/'trace-analysis/timing.csv')
        roles=read(gate/'trace-analysis/critical-role-waits.csv')
        stages=read(gate/'trace-analysis/critical-role-stages.csv')
        assert len(timings)==2 and len(roles)==8*captures*4
        for operation in ['dispatch_fresh','combine']:
            selected=[r for r in ordinary if r['snapshot']=='source-zero-packed-v7' and
                r['variant']=='marker-zero' and r['experiment']==family and
                r['contexts']==str(contexts) and r['interval']=='16' and
                r['sms']=='64' and
                r['tokens']=='4096' and r['model']=='v4flash' and r['dtype']=='fp8' and
                r['routing']=='mixed' and r['operation']==operation]
            assert len(selected)==3 and {r['repeat'] for r in selected}=={'1','2','3'}
            values=[float(r['median_ms']) for r in selected]
            timing=next(r for r in timings if r['operation']==operation)
            before,after,enabled=[float(timing[k]) for k in
                ['disabled_before_ms','disabled_after_ms','enabled_ms']]
            assert all(math.isfinite(v) and v>0 for v in values+[before,after,enabled])
            summaries.append(dict(contexts=contexts,operation=operation,gate=gate_name,
                ordinary_ms=statistics.median(values),ordinary_min_ms=min(values),ordinary_max_ms=max(values),
                disabled_before_ms=before,disabled_after_ms=after,enabled_ms=enabled,
                enabled_vs_disabled_ratio=enabled/((before+after)/2),
                disabled_vs_ordinary_ratio=((before+after)/2)/statistics.median(values)))
            expected_roles=(['dispatch_sender','dispatch_forwarder'] if operation=='dispatch_fresh'
                            else ['combine_NVLink_sender','combine_forwarder'])
            for role in expected_roles:
                for rank in range(8):
                    picked=[r for r in roles if r['operation']==operation and r['role']==role and int(r['rank'])==rank]
                    assert len(picked)==captures and {int(r['iteration']) for r in picked}==set(range(captures))
                    result=dict(contexts=contexts,operation=operation,role=role,rank=rank,captures=captures)
                    for key in ['duration_ms','wait_union_ms','event_200_union_ms','event_202_union_ms',
                                'event_207_union_ms','event_208_union_ms','event_105_union_ms',
                                'event_134_union_ms','event_136_union_ms','event_138_union_ms']:
                        result[key]=statistics.median(float(r[key]) for r in picked)
                    for event in [112,113,114,135,137,209,210,211,212,213]:
                        chunks=[r for r in stages if r['operation']==operation and r['role']==role and
                                int(r['rank'])==rank and int(r['event'])==event]
                        assert len({int(r['iteration']) for r in chunks})==len(chunks)
                        by_iteration={int(r['iteration']):float(r['clipped_union_ms']) for r in chunks}
                        assert set(by_iteration)<=set(range(captures))
                        result['stage_%d_ms'%event]=statistics.median(by_iteration.get(i,0.) for i in range(captures))
                    per_rank.append(result)
    assert seen=={129,257}
    out=a.job/'context-trace-comparison';out.mkdir(exist_ok=True)
    write(out/'timing.csv',summaries);write(out/'per-rank-roles.csv',per_rank)
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import numpy as np
    for operation in ['dispatch_fresh','combine']:
        timing=sorted([r for r in summaries if r['operation']==operation],key=lambda r:r['contexts'])
        fig,(top,bottom)=plt.subplots(2,1,figsize=(11,10),gridspec_kw={'height_ratios':[1,2.6]})
        x=np.arange(2);width=.19
        for i,(key,label,color) in enumerate([
            ('ordinary_ms','Ordinary build (3 repeats)','#68737d'),
            ('disabled_before_ms','Instrumented, disabled before','#268b9e'),
            ('disabled_after_ms','Instrumented, disabled after','#85b9b4'),
            ('enabled_ms','Recording enabled','#dd9951')]):
            bars=top.bar(x+(i-1.5)*width,[r[key] for r in timing],width,label=label,color=color)
            top.bar_label(bars,fmt='%.2f',fontsize=8,padding=2)
        top.set_xticks(x,['129 contexts','257 contexts']);top.set_ylabel('Rank-max median latency (ms)')
        top.set_ylim(0,max(r[k] for r in timing for k in
            ['ordinary_ms','disabled_before_ms','disabled_after_ms','enabled_ms'])*1.3)
        top.legend(fontsize=8,ncol=2);top.spines[['top','right']].set_visible(False)
        role='dispatch_sender' if operation=='dispatch_fresh' else 'combine_forwarder'
        data=sorted([r for r in per_rank if r['operation']==operation and r['role']==role],
                    key=lambda r:(r['contexts'],r['rank']))
        cols=[('duration_ms','Role\nlifetime'),('wait_union_ms','Wait\nunion'),
              ('event_200_union_ms','Context\nlock'),('event_202_union_ms','TX queue\nwait'),
              ('event_207_union_ms','CT\nwriteback'),('event_208_union_ms','CT queue\nconsume'),
              ('stage_209_ms','TX\npublication')]
        cols+=([('stage_112_ms','Packing'),('stage_114_ms','Notification\ninclusive')]
               if operation=='dispatch_fresh' else
               [('event_134_union_ms','Local\ncontributors'),('event_138_union_ms','Remote\ntail')])
        matrix=np.array([[r[k] for k,_ in cols] for r in data])
        heat=bottom.imshow(matrix,aspect='auto',cmap='Blues',vmin=0)
        for i in range(len(data)):
            for j in range(len(cols)):
                bottom.text(j,i,'%.3f'%matrix[i,j],ha='center',va='center',fontsize=7,
                    color='white' if matrix[i,j]>.6*matrix.max() else 'black')
        bottom.set_xticks(range(len(cols)),[label for _,label in cols],fontsize=8)
        bottom.set_yticks(range(len(data)),['q%d / rank%d'%(r['contexts'],r['rank']) for r in data],fontsize=8)
        bottom.axhline(7.5,color='black',linewidth=1)
        bottom.set_title('Recorded intervals: latest-finishing %s warp on each rank'%role,fontsize=10)
        fig.colorbar(heat,ax=bottom,label='Median recorded interval (ms)',fraction=.025,pad=.02)
        fig.suptitle('EP8 direct CXI GIN: '+operation+' — V4 Flash, 4K tokens/GPU',fontsize=13)
        fig.text(.5,.025,'Trace categories overlap and are NOT additive. These are GPU observations, not NIC wire timestamps.',ha='center',fontsize=8)
        fig.text(.5,.008,'Recording overhead is measured above; both roles and every rank are preserved in per-rank-roles.csv.',ha='center',fontsize=8)
        fig.tight_layout(rect=(0,.045,1,.96))
        for ext in ['pdf','png']:fig.savefig(out/(operation+'.'+ext),dpi=170)
        plt.close(fig)
    (out/'README.md').write_text('Matched context comparison on the same allocation. Ordinary results require three complete qualified repeats. '
        'Disabled recordings use the instrumented build and remain separate from ordinary timings. '
        'Per-rank role values are medians across captures of that rank’s latest-finishing warp for each role. '
        'Category unions overlap and cannot be summed; unclassified time is not proven network or compute time. '
        'A smaller lock wait does not establish a smaller end-to-end latency.\n')
    print(out)

if __name__=='__main__':main()
