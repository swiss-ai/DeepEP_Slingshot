"""Separate PUT size, strong-signal cadence and ordinary doorbell cadence.

Probe-only derivative of the matched-width ladder; the EP and transport inputs
remain unchanged. These interventions are not additive EP stage timings.
"""
import argparse, hashlib, json, shutil, subprocess, tarfile
from pathlib import Path
from package import ROOT, REMOTE, replace

p=argparse.ArgumentParser();p.add_argument('name');a=p.parse_args()
assert Path(a.name).name==a.name
campaign=ROOT/'results/deepep_pipeline_20261030'
parent=campaign/'source-transport-ladder-v1';out=campaign/a.name
assert not out.exists()
shutil.copytree(parent,out,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
probe=out/'backend/tests/gin_stage_ladder.cu'
replace(probe,'int contexts,int rows,int interval,bool coalesce,int iteration,Stamp* stamps)',
    'int contexts,int rows,int interval,bool coalesce,int batch_rows,int publish_interval,int iteration,Stamp* stamps)')
replace(probe,'''  const int step=coalesce?count:1;
  for(int row=first;row<last;row+=step){''','''  const int step=coalesce?(batch_rows?min(batch_rows,count):count):1;
  for(int row=first;row<last;){
    int n=min(step,last-row);
    // Never skip a requested signal or publication boundary in a multirow PUT.
    if(interval)n=min(n,interval-(row-first)%interval);
    if(publish_interval)n=min(n,publish_interval-(row-first)%publish_interval);
    const auto flags=publish_interval && (row-first+n)%publish_interval==0 ?
        0 : ncclGinOptFlagsAggregateRequests;''')
replace(probe,'size_t(step)*row_bytes,','size_t(n)*row_bytes,')
replace(probe,'''cuda::thread_scope_thread,cuda::thread_scope_device,ncclGinOptFlagsAggregateRequests);
    if(interval && (row-first+1)%interval==0)''','''cuda::thread_scope_thread,cuda::thread_scope_device,flags);
    row+=n;
    if(interval && (row-first)%interval==0)''')
replace(probe,'    const bool coalesce=option("CXI_LADDER_COALESCE",0);',
    '''    const bool coalesce=option("CXI_LADDER_COALESCE",0);
    const int batch_rows=option("CXI_LADDER_BATCH_ROWS",0);
    const int publish_interval=option("CXI_LADDER_PUBLISH_INTERVAL",0);''')
replace(probe,'interval<0 || interval>64 || (coalesce && interval)',
    'interval<0 || interval>64 || batch_rows<0 || batch_rows>64 || (!coalesce && batch_rows) || publish_interval<0 || publish_interval>64')
for width in [4320,8256]:
    replace(probe,'transfer<%d><<<64,128>>>(dev,sw,dw,contexts,rows,interval,coalesce,iteration,device);'%width,
        'transfer<%d><<<64,128>>>(dev,sw,dw,contexts,rows,interval,coalesce,batch_rows,publish_interval,iteration,device);'%width)
# Include the exact requested cadences in every timer record.
replace(probe, r'\"signal_interval\":%d,\"coalesce\":%s,',
    r'\"signal_interval\":%d,\"coalesce\":%s,\"batch_rows\":%d,\"publish_interval\":%d,')
replace(probe,'row_bytes,interval,coalesce?"true":"false",elapsed,bad);',
    'row_bytes,interval,coalesce?"true":"false",batch_rows,publish_interval,elapsed,bad);')
validator=out/'runner/validate_gate.py'
replace(validator,"and r['coalesce'] == bool(int(env['CXI_LADDER_COALESCE']))", 
    """and r['coalesce'] == bool(int(env['CXI_LADDER_COALESCE']))
                            and r['batch_rows'] == int(env['CXI_LADDER_BATCH_ROWS'])
                            and r['publish_interval'] == int(env['CXI_LADDER_PUBLISH_INTERVAL'])""")
template=json.loads((parent/'sequence.json').read_text())[0]
sequence=[]
for tokens in [4096,16384]:
    for width in [4320,8256]:
        for label,coalesce,batch,signal,publish in [
            ('rows-final',0,0,0,0),('rows-publish3',0,0,0,3),
            ('batch16-final',1,16,0,0),('batch16-signal16',1,16,16,0)]:
            g=json.loads(json.dumps(template))
            g.update(name='%d-cadence-%dB-%d-%s'%(5600+len(sequence),width,tokens,label),
                     snapshot=REMOTE+'/sources/'+out.name,requires=[])
            g['environment'].update(CXI_LADDER_ROWS=str(tokens),CXI_LADDER_ROW_BYTES=str(width),
                CXI_LADDER_CONTEXTS='129',CXI_LADDER_COALESCE=str(coalesce),
                CXI_LADDER_BATCH_ROWS=str(batch),CXI_LADDER_SIGNAL_INTERVAL=str(signal),
                CXI_LADDER_PUBLISH_INTERVAL=str(publish))
            sequence.append(g)
(out/'sequence.json').write_text(json.dumps(sequence,indent=2)+'\n')
before=json.loads((parent/'manifest.json').read_text())
files={str(f.relative_to(out)):hashlib.sha256(f.read_bytes()).hexdigest()
       for f in out.rglob('*') if f.is_file() and f.name!='manifest.json'}
changed={'backend/tests/gin_stage_ladder.cu','runner/validate_gate.py','sequence.json'}
assert set(files)==set(before['files'])
assert {k for k in files if files[k]!=before['files'][k]}==changed
compile(validator.read_text(),str(validator),'exec')
before.update(files=files,source_parent=str(parent),
    scope='Probe-only PUT batch/strong-signal/publication interventions; unchanged EP and GPU transport; GPU unqualified')
(out/'manifest.json').write_text(json.dumps(before,indent=2)+'\n')
with tarfile.open(campaign/(out.name+'-overlay.tar.gz'),'w:gz') as archive:
    for name in sorted(changed|{'manifest.json'}):archive.add(out/name,arcname=name)
print('Prepared cadence probe; actual compilation/GPU qualification pending',out)
