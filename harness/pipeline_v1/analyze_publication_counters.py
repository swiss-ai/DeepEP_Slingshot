"""Extract cumulative queue-counter deltas from matched two-size timing runs.

The counters cover every operation, warmup, correctness check and NIC window in
the case. They are not isolated dispatch request counts or NIC packet counts.
"""
import argparse,csv,json,re
from pathlib import Path


def analyze(job):
    output=job/'publication-counter-analysis';output.mkdir(exist_ok=True)
    rows=[];excluded=[]
    for finished in sorted((job/'results/results').glob('*-repeat[123]/FINISHED.json')):
        record=json.loads(finished.read_text());spec=record['spec'];env=spec['environment']
        if spec['qualification']!='ep' or env.get('CXI_EP_TOKENS')!='4096 16384':continue
        if env.get('CXI_EP_CONTEXTS') not in ('129','257') or env.get('CXI_DEVICE_TRACE','0')!='0':continue
        if record.get('returncode')!=0 or record.get('qualification',{}).get('status')!='PASS':continue
        gate=finished.parent
        try:
            counters={rank:[] for rank in range(8)}
            for node in range(2):
                text=(gate/'direct'/('node%d'%node)/'smoke.log').read_text()
                for rank,commands,doorbells,pending in re.findall(
                        r'CXI_TX_PUBLICATION rank=(\d+) cumulative_commands=(\d+) cumulative_doorbells=(\d+) unpublished=(\d+)',text):
                    rank,commands,doorbells,pending=map(int,[rank,commands,doorbells,pending])
                    assert rank//4==node and pending==0
                    if commands:counters[rank].append((commands,doorbells))
            temporary=[]
            for rank in range(8):
                cases=[json.loads(line) for line in (gate/'direct/ep'/('correctness-rank%d.jsonl'%rank)).read_text().splitlines()]
                assert len(cases)==len(counters[rank])==2
                assert [case['tokens_per_gpu'] for case in cases]==[4096,16384]
                assert all(case['allocated_contexts']==int(env['CXI_EP_CONTEXTS']) and
                           case['actual_sms']==int(env['CXI_EP_SMS']) and
                           case['qps']==int(env['CXI_EP_CONTEXTS']) for case in cases)
                previous=(0,0)
                for case,current in zip(cases,counters[rank]):
                    commands,doorbells=(a-b for a,b in zip(current,previous));previous=current
                    assert commands>0 and doorbells>0
                    temporary.append(dict(gate=gate.name,snapshot=Path(spec['snapshot']).name,
                        variant=env['CXI_VARIANT'],packed=env.get('CXI_EP_PACK_ROWS','0'),
                        contexts=env['CXI_EP_CONTEXTS'],sms=env['CXI_EP_SMS'],
                        interval=env.get('CXI_EP_UPDATE_INTERVAL','3'),rank=rank,
                        warmup=env['CXI_EP_WARMUP'],iterations=env['CXI_EP_ITERS'],nic_iterations=env['CXI_EP_NIC_ITERS'],
                        tokens=case['tokens_per_gpu'],model=case['model'],
                        case_commands=commands,case_doorbells=doorbells,
                        commands_per_doorbell=commands/doorbells))
            rows+=temporary
        except (AssertionError,OSError,ValueError) as error:
            excluded.append(dict(gate=gate.name,reason=repr(error)))
    assert rows
    with (output/'counters.csv').open('w') as file:
        writer=csv.DictWriter(file,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    (output/'excluded.json').write_text(json.dumps(excluded,indent=2)+'\n')
    (output/'README.md').write_text('Queue counters persist across pooled-channel reuse; second-case values are '
        'differenced from first-case values. Context counts are recorded separately and verified in every rank; '
        'zero-count bootstrap contexts are excluded. Each case includes correctness checks, warmups, '
        'all four timed operations, and configured NIC windows. Counters are software enqueue/doorbell '
        'counts, not wire packets or dispatch-only requests. Only formally passed, completely collected '
        'runs are admitted. Do not compare totals from different benchmark loop settings.\n')
    return output


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('job',type=Path);print(analyze(p.parse_args().job))
