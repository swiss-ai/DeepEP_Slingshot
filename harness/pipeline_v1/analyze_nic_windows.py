"""Audit measured per-port TX/RX octet rates from qualified ordinary repeats.

These are isolated repeated-operation windows, including control traffic and
barriers. They are not payload-only bandwidth or instantaneous NIC busy time.
"""
import argparse
import csv
import json
import itertools
import re
import statistics
from collections import defaultdict
from pathlib import Path


def main():
    parser=argparse.ArgumentParser();parser.add_argument('job',type=Path)
    args=parser.parse_args();rows=[];excluded=[]
    for finished in sorted((args.job/'results/results').glob('*/FINISHED.json')):
        record=json.loads(finished.read_text());spec=record['spec'];env=spec['environment']
        match=re.search(r'-repeat([123])$',spec['name'])
        if not match or spec['qualification']!='ep' or env.get('CXI_DEVICE_TRACE','0')!='0':continue
        if record.get('returncode')!=0 or record.get('qualification',{}).get('status')!='PASS':continue
        if int(env.get('CXI_EP_NIC_ITERS','0'))<=0:continue
        if '4096' not in env['CXI_EP_TOKENS'].split():continue
        transport=env['CXI_TRANSPORT']
        expected_iters=int(env['CXI_EP_NIC_ITERS'])
        family=re.sub(r'^[0-9][0-9a-z]*-','',re.sub(r'-repeat[123]$','',spec['name']))
        sources=[finished.parent/transport/'ep'/('nic-node%d.jsonl'%node) for node in range(2)]
        if not all(source.is_file() for source in sources):
            excluded.append(spec['name']+': both NIC files not collected yet');continue
        try:
            cases=[[json.loads(line) for line in source.read_text().splitlines()] for source in sources]
            expected=set(itertools.product(env['CXI_EP_MODELS'].split(),env['CXI_EP_DTYPES'].split(),
                                           env['CXI_EP_ROUTING'].split(),('dispatch_fresh','dispatch_cached','combine','cycle')))
            complete=all(len(node)==len(expected) and
                {(c['model'],c['dispatch_dtype'],c['routing'],c['operation']) for c in node}==expected for node in cases)
        except (json.JSONDecodeError,KeyError,TypeError):
            complete=False
        if not complete:
            excluded.append(spec['name']+': collected NIC matrix incomplete or malformed');continue
        for node in range(2):
            for case in cases[node]:
                assert case['rank']==node*4 and case['ep']==8 and case['iterations']==expected_iters
                assert case['progress_update_interval']==int(env.get('CXI_EP_UPDATE_INTERVAL','3'))
                assert case['allocated_contexts']==int(env['CXI_EP_CONTEXTS'])
                assert case['actual_sms']==int(env['CXI_EP_SMS'])
                before,after=case['before'],case['after']
                assert before.keys()==after.keys() and len(before)==8
                for key,start in before.items():
                    port,counter=key.split('/');end=after[key]
                    assert counter in ('hni_sts_tx_ok_octets','hni_sts_rx_ok_octets')
                    delta=end['value']-start['value'];seconds=end['timestamp']-start['timestamp']
                    assert delta>=0 and seconds>0
                    calculated=delta/seconds/1e9
                    assert abs(calculated-case['rates'][key]['GBps'])<1e-9
                    rows.append(dict(snapshot=Path(spec['snapshot']).name,variant=env['CXI_VARIANT'],
                        experiment=family,transport=transport,contexts=int(env['CXI_EP_CONTEXTS']),sms=int(env['CXI_EP_SMS']),
                        interval=case['progress_update_interval'],model=case['model'],tokens=case['tokens_per_gpu'],
                        dtype=case['dispatch_dtype'],routing=case['routing'],operation=case['operation'],
                        repeat=int(match[1]),node=node,port=port,direction='TX' if '_tx_' in counter else 'RX',
                        GBps=calculated,MB_per_iteration=delta/expected_iters/1e6,
                        counter_window_ms_per_iteration=seconds*1000/expected_iters,
                        wall_ms_per_iteration=case['wall_seconds']*1000/expected_iters,gate=spec['name']))
    out=args.job/'nic-analysis';out.mkdir(exist_ok=True)
    def write(name,data):
        if not data:return
        with (out/name).open('w') as file:
            writer=csv.DictWriter(file,fieldnames=list(data[0]));writer.writeheader();writer.writerows(data)
    write('ports.csv',rows)
    keys=('snapshot','variant','experiment','transport','contexts','sms','interval','model','tokens','dtype','routing','operation','direction')
    grouped=defaultdict(list)
    for row in rows:grouped[tuple(row[k] for k in keys)+(row['repeat'],)].append(row)
    repeats=[]
    for group,values in sorted(grouped.items()):
        assert len(values)==8 and len({(v['node'],v['port']) for v in values})==8
        assert {v['node'] for v in values}=={0,1}
        data=dict(zip(keys,group[:-1]));data['repeat']=group[-1]
        for key in ['GBps','MB_per_iteration','counter_window_ms_per_iteration','wall_ms_per_iteration']:
            data['median_'+key]=statistics.median(v[key] for v in values)
        data['min_GBps']=min(v['GBps'] for v in values);data['max_GBps']=max(v['GBps'] for v in values)
        repeats.append(data)
    write('repeats.csv',repeats)
    grouped=defaultdict(list)
    for row in repeats:grouped[tuple(row[k] for k in keys)].append(row)
    text=['# Measured NIC octet rates','',
        'Median across eight ports within each repeat, then median across available repeats. '
        'Each direction is separate; TX and RX are not added. All eight ranks must have passed the EP gate.','',
        '| Snapshot / variant | Experiment | Operation | Direction | Repeats | GB/s per port | MB per call per port | Window ms/call |',
        '|---|---|---|---|---:|---:|---:|---:|']
    for group,values in sorted(grouped.items()):
        assert len({v['repeat'] for v in values})==len(values)
        one=values[0]
        label='%s / %s / %d tokens / %s'%(one['experiment'],one['model'],one['tokens'],one['dtype'])
        text.append('| %s / %s | %s | %s | %s | %d/3 | %.3f | %.3f | %.4f |'%(
            one['snapshot'],one['variant'],label,one['operation'],one['direction'],len(values),
            statistics.median(v['median_GBps'] for v in values),
            statistics.median(v['median_MB_per_iteration'] for v in values),
            statistics.median(v['median_counter_window_ms_per_iteration'] for v in values)))
    text+=['','Rates use the telemetry counter timestamps, recomputed from before/after octets. '
           'Windows include repeated operations, readiness/barrier and protocol traffic. They are not '
           'instantaneous link utilization, useful-payload throughput, or isolated transfer time. '
           'The port CSV retains directional imbalance and window duration; no cross-node clock alignment is assumed.']
    if excluded:text+=['','Excluded from this live collection:','']+['- '+entry for entry in excluded]
    (out/'summary.md').write_text('\n'.join(text)+'\n');print(out/'summary.md')


if __name__=='__main__':main()
