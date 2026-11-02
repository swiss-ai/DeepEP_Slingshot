#!/usr/bin/env python3
"""One bounded allocation, immutable requests, explicit resume after failure."""
import datetime,json,os,signal,subprocess,time
from pathlib import Path
from allocation_time import allocation_remaining
from validate_gate import qualify

def atomic_json(path, value):
    tmp=path.with_suffix('.tmp'); tmp.write_text(json.dumps(value,indent=2)+'\n'); tmp.replace(path)

def prerequisite_pass(root, names):
    for name in names:
        if Path(name).name!=name: raise ValueError('invalid dependency name')
        p=root/'results'/name/'FINISHED.json'
        if not p.is_file(): return False
        r=json.loads(p.read_text())
        if r.get('returncode')!=0 or r.get('qualification',{}).get('status')!='PASS': return False
    return True

def qualify_burst(out):
    for node in range(2):
        p=out/'dynamic'/('node%d'%node)
        assert sorted(x.split() for x in (p/'status.tsv').read_text().splitlines())==[[str(i),'0'] for i in range(4)]
        for gpu in range(4):
            rows=[json.loads(x) for x in (p/('gpu%d.log'%gpu)).read_text().splitlines() if x.startswith('{')]
            assert len(rows)==2
            a,b=rows
            assert a['rank']==node*4+gpu and a['cases']==4 and a['errors']==0 and a['diagnostic']==0
            assert a['posted']==a['completed']==4*(4096+3)
            assert b['rc']==0 and b['is_nccl_gin'] is False
    return {'status':'PASS','kind':'burst_wrap_source_reuse','ranks':8,'payload_commands_per_rank':16384}

def main():
    campaign=Path(os.environ['CAMPAIGN']).resolve()
    root=campaign/'jobs'/os.environ['SLURM_JOB_ID']
    for d in ['requests','results']: (root/d).mkdir(parents=True,exist_ok=True)
    snapshot=Path(os.environ['INITIAL_SNAPSHOT'])
    for spec in json.loads((snapshot/'sequence.json').read_text()):
        atomic_json(root/'requests'/(spec['name']+'.json'),spec)
    seen=set(); last_work=time.monotonic(); active=[None]; stop=[False]
    def signal_stop(*unused):
        stop[0]=True
        if active[0] is not None:
            try: os.killpg(active[0].pid,signal.SIGTERM)
            except ProcessLookupError: pass
    signal.signal(signal.SIGTERM,signal_stop); signal.signal(signal.SIGINT,signal_stop)
    def status(state, **extra):
        atomic_json(root/'status.json',dict(state=state,utc=datetime.datetime.utcnow().isoformat()+'Z',**extra))
    status('READY')
    while not stop[0] and not (root/'STOP').exists():
        remaining=allocation_remaining(os.environ)['remaining_seconds']
        if remaining<180: break
        if (root/'PAUSED.json').exists():
            if (root/'RESUME.json').exists():
                resume=json.loads((root/'RESUME.json').read_text())
                if not resume.get('reason'): raise ValueError('resume requires an explanation')
                # A drained previous step and responsive GPUs are prerequisites.
                rc=subprocess.call(['timeout','60s','srun','--immediate=30','--kill-on-bad-exit=1',
                                    '--ntasks=2','--ntasks-per-node=1','nvidia-smi','-L'])
                if rc: status('PAUSED_UNHEALTHY',returncode=rc); break
                (root/'RESUME.json').rename(root/('RESUMED-%d.json'%int(time.time())))
                (root/'PAUSED.json').unlink(); last_work=time.monotonic()
            else:
                status('PAUSED_FOR_DEBUG',remaining_seconds=remaining)
                if os.environ.get('CXI_KEEP_ALLOCATION')!='1' and time.monotonic()-last_work>2700: break
                time.sleep(10); continue
        requests=[p for p in sorted((root/'requests').glob('*.json')) if p.name not in seen]
        if not requests:
            status('IDLE_FOR_DEBUG',remaining_seconds=remaining)
            if os.environ.get('CXI_KEEP_ALLOCATION')!='1' and time.monotonic()-last_work>2700: break
            time.sleep(10); continue
        request=requests[0]; seen.add(request.name)
        spec=json.loads(request.read_text()); name=request.stem
        out=root/'results'/name; out.mkdir()
        record={'spec':spec,'start_utc':datetime.datetime.utcnow().isoformat()+'Z'}
        if not prerequisite_pass(root,spec.get('requires',[])):
            # After explicit resume, skip the failed branch rather than running
            # dependent benchmarks or repeatedly pausing on every descendant.
            record.update(state='BLOCKED',error='prerequisite did not pass',returncode=None)
            atomic_json(out/'FINISHED.json',record)
            continue
        try:
            source=Path(spec['snapshot']).resolve()
            if campaign/'sources' not in source.parents: raise ValueError('snapshot outside campaign sources')
            duration=int(spec['timeout_seconds'])
            if not 1<=duration<=1800 or duration+180>remaining: raise ValueError('insufficient allocation time')
            env=os.environ.copy()
            for k,v in spec['environment'].items():
                if not k.startswith(('CXI_','EP_','NCCL_')) or not isinstance(v,str): raise ValueError('invalid environment override')
                env[k]=v
            env.update(SNAPSHOT=str(source),OUT=str(out),MASTER_PORT=str(24000+int(os.environ['SLURM_JOB_ID'])%10000))
            cmd=['timeout','--signal=TERM','--kill-after=20s',str(duration)+'s','srun','--kill-on-bad-exit=1',
                 '--cpu-bind=none','--environment='+str(campaign/'container.toml'),'bash',str(source/'runner/node.sh')]
            atomic_json(out/'STARTED.json',record); status('RUNNING_STEP',request=name,remaining_seconds=remaining)
            with (out/'launch.log').open('w') as log:
                active[0]=subprocess.Popen(cmd,env=env,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
                record['returncode']=active[0].wait(); active[0]=None
            if record['returncode']!=0: raise RuntimeError('test step failed')
            if spec['qualification']=='ep_trace':
                import gzip
                normal=dict(spec,qualification='ep');record['qualification']=qualify(out,normal)
                directory=out/'direct/ep/device-traces'
                for rank in range(8):
                    for op in ['dispatch_fresh','combine']:
                        files=list(directory.glob('*-%s-rank%d-iteration*.json.gz'%(op,rank)))
                        assert len(files)==int(spec['environment']['CXI_TRACE_CAPTURES']), ('missing captures',rank,op)
                        for path in files:
                            with gzip.open(str(path),'rt') as f:r=json.load(f)
                            assert r['correctness']=='PASS' and r['stats']['overflow']==0 and r['events']
                            kinds={e['event'] for e in r['events']}
                            assert {200,203,207}<=kinds, ('missing queue/completion trace',kinds)
                            assert ({100,103,104} if op=='dispatch_fresh' else {130,132,133,134,138})<=kinds
                record['qualification']['device_traces']='PASS'
                subprocess.check_call(['python3',str(source/'runner/analyze.py'),str(out)])
            else:
                record['qualification']=qualify_burst(out) if spec['qualification']=='burst' else qualify(out,spec)
        except Exception as error:
            record['error']=str(error)
            record['qualification']={'status':'FAIL','reason':str(error)}
            atomic_json(root/'PAUSED.json',{'request':name,'reason':str(error)})
        record['end_utc']=datetime.datetime.utcnow().isoformat()+'Z'
        atomic_json(out/'FINISHED.json',record); last_work=time.monotonic()
    status('FINISHED',reason='STOP, allocation deadline, health failure, or configured idle limit')

if __name__=='__main__': main()
