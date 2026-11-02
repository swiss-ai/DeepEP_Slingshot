"""Refresh completed CT accounting at destruction, preserving GPU datapath bytes."""
import argparse,copy,hashlib,json,shutil
from pathlib import Path
from package import ROOT,REMOTE,replace

p=argparse.ArgumentParser();p.add_argument('output',type=Path);p.add_argument('--gate-base',type=int,default=1600)
args=p.parse_args();out=args.output.resolve()
parent=ROOT/'results/deepep_pipeline_20261030/source-marker-probe-v3'
shutil.copytree(parent,out,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
host=out/'backend/host/cxi_resources.cc'
replace(host,'int cxi_channel_recycle(CxiChannel* q,const CxiGpuContext* state) {',
 Path(__file__).with_name('retire_refresh_host.cc.inc').read_text()+'\nint cxi_channel_recycle(CxiChannel* q,const CxiGpuContext* state) {')
replace(host,'state->pending_dst || state->tx_unpublished || state->posted!=state->completed || cxi_channel_error(q))',
 'state->pending_dst || state->tx_unpublished || cxi_channel_error(q))')
replace(host,'  q->descriptor=*state;','''  CxiGpuContext retired=*state;
  if(retired.posted!=retired.completed && refresh_retired_completion(q,retired))return 1;
  state=&retired;
  q->descriptor=*state;''')
validator=out/'runner/validate_gate.py'
replace(validator,"    if mode == 'ep':\n        ep = base / 'ep'",'''    if mode == 'ep':
        if env.get('CXI_REQUIRE_REUSE') == '1':
            import re
            for node in range(2):
                text=(base/('node%d'%node)/'smoke.log').read_text()
                entries=re.findall(r'CXI pool phase=context-created gpu=(\\d+) created=(\\d+) reused=(\\d+) allocated=(\\d+) idle=(\\d+) ct_in_use=(\\d+) usage_rc=(\\d+)',text)
                for gpu in range(4):
                    rows=[tuple(map(int,x)) for x in entries if int(x[0])==gpu]
                    require(rows and all(x[6]==0 for x in rows), 'missing/error lifecycle resource records')
                    require(max(x[2] for x in rows)>0, 'healthy channels never reused')
                    require(max(x[1] for x in rows)<=260 and max(x[5] for x in rows)<=260,
                            'CT resources did not plateau below the service limit')
                require('CXI_RETIRE_REFRESH ' in text and 'teardown_only=1' in text,
                        'retirement completion refresh was not exercised')
        ep = base / 'ep' ''')
campaign=ROOT/'results/deepep_pipeline_20261030'
parents=json.loads((campaign/'newnode-marker-v3-zero-qualification-sequence.json').read_text())
seq=[]
for i,original in enumerate(parents):
 s=copy.deepcopy(original);s['name']=str(args.gate_base+i)+'-retire-refresh-'+original['name'].split('-zero-marker-',1)[1]
 s['snapshot']=REMOTE+'/sources/'+out.name
 s['requires']=['1122-marker-zero-notification-probe','1202-zero-marker-producers'] if i==0 else [seq[-1]['name']]
 s['timeout_seconds']=1200 if i in (0,3,4) else max(600,s['timeout_seconds'])
 s['environment']['CXI_TEST_TIMEOUT']=str(s['timeout_seconds']-60)
 if i in (3,4):s['environment']['CXI_REQUIRE_REUSE']='1'
 seq.append(s)
assert len(seq)==9
(out/'sequence.json').write_text(json.dumps(seq,indent=2)+'\n')
m=json.loads((parent/'manifest.json').read_text());files={str(p.relative_to(out)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(out.rglob('*')) if p.is_file() and p.name!='manifest.json'}
assert set(files)==set(m['files'])
assert {k for k in files if files[k]!=m['files'][k]}=={'backend/host/cxi_resources.cc','runner/validate_gate.py','sequence.json'}
m.update(files=files,source_parent=str(parent),scope='Teardown-only local CT completion refresh for healthy queue pooling; GPU/device/ABI/NCCL/DeepEP bytes unchanged; full lifecycle qualification pending')
(out/'manifest.json').write_text(json.dumps(m,indent=2)+'\n')
for p in [validator]:compile(p.read_text(),str(p),'exec')
print('PASS exact host lifecycle/qualifier/sequence delta; GPU datapath unchanged; GPU unqualified')
