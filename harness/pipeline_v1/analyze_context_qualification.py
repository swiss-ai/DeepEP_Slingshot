"""Verify actual per-rank QPs and bounded CT reuse in a collected V4 EP gate.

This supplements the immutable gate validator; it never rewrites FINISHED.json.
The qps+4 bound is specific to this campaign's four bootstrap contexts.
"""
import argparse
import json
import re
from pathlib import Path

def analyze(gate):
    record=json.loads((gate/'FINISHED.json').read_text())
    assert record['returncode']==0 and record['qualification']['status']=='PASS'
    spec=record['spec'];env=spec['environment']
    assert spec['qualification']=='ep' and env['CXI_EP_MODELS']=='v4flash'
    qps=int(env['CXI_EP_CONTEXTS']);assert qps in (129,257)
    evidence=[]
    for node in range(2):
        text=(gate/'direct'/('node%d'%node)/'smoke.log').read_text()
        pools=[tuple(map(int,x)) for x in re.findall(
            r'CXI pool phase=context-created gpu=(\d+) created=(\d+) reused=(\d+) allocated=(\d+) idle=(\d+) ct_in_use=(\d+) usage_rc=(\d+)',text)]
        refresh=[tuple(map(int,x)) for x in re.findall(
            r'CXI_RETIRE_REFRESH gpu=(\d+) ct=(\d+) before=(\d+) posted=(\d+) completed=(\d+) reads=(\d+) teardown_only=(\d+)',text)]
        for gpu in range(4):
            rank=4*node+gpu
            cases=[json.loads(x) for x in (gate/'direct/ep'/('correctness-rank%d.jsonl'%rank)).read_text().splitlines()]
            assert len(cases)>=2 and all(c['rank']==rank and c['status']=='PASS' and
                c['allocated_contexts']==qps and c['qps']==qps and
                c['actual_sms']==int(env['CXI_EP_SMS']) and
                c['progress_update_interval']==int(env['CXI_EP_UPDATE_INTERVAL']) for c in cases)
            rows=[x for x in pools if x[0]==gpu];retired=[x for x in refresh if x[0]==gpu]
            assert rows and all(x[6]==0 for x in rows)
            created=max(x[1] for x in rows);ct=max(x[5] for x in rows);reused=max(x[2] for x in rows)
            assert qps<=created<=qps+4 and qps<=ct<=qps+4 and reused>=qps
            assert retired and all(x[2]<=x[3]==x[4] and x[5]>=1 and x[6]==1 for x in retired)
            evidence.append(dict(rank=rank,cases=len(cases),actual_qps=qps,
                max_created=created,max_ct_in_use=ct,reused=reused,retirement_refreshes=len(retired)))
    result=dict(status='PASS',gate=gate.name,source=Path(spec['snapshot']).name,ranks=evidence,
        scope='Actual QP settings, repeated V4 buffer lifecycle, bounded CT allocation and teardown refresh; no timing claim')
    (gate/'context-qualification.json').write_text(json.dumps(result,indent=2)+'\n')
    return result

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('gate',type=Path)
    print(json.dumps(analyze(p.parse_args().gate),indent=2))
