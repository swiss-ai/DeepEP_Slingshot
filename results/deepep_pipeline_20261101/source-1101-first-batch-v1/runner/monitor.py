#!/usr/bin/env python3
"""Read-only live collection. Never modifies code, jobs, or RESUME controls."""
import argparse,datetime,json,subprocess,time
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('job',type=int);p.add_argument('output',type=Path);a=p.parse_args()
a.output.mkdir(parents=True,exist_ok=True)
base='/iopsstor/scratch/cscs/zyu/deepep-pipeline-20261030'; remote=base+'/jobs/'+str(a.job)
terminal_failures=0
while True:
    terminal=False
    try:
        cmd='squeue -h -j {j} -o "%T|%M|%R"; sacct -n -X -j {j} --format=State,ExitCode,Elapsed -P; test ! -f {r}/status.json || cat {r}/status.json'.format(j=a.job,r=remote)
        result=subprocess.run(['ssh','-o','BatchMode=yes','-o','ConnectTimeout=10','clariden',cmd],capture_output=True,text=True,timeout=30)
        value=datetime.datetime.now(datetime.timezone.utc).isoformat()+'\n'+result.stdout+result.stderr
        (a.output/'latest.txt').write_text(value)
        with (a.output/'history.log').open('a') as f:f.write(value+'\n')
        terminal=any(x.startswith(('COMPLETED|','FAILED|','CANCELLED','TIMEOUT|','NODE_FAIL|','OUT_OF_MEMORY|','PREEMPTED|')) for x in result.stdout.splitlines())
        # Collect logs and intermediate correctness/timing evidence during execution.
        if 'RUNNING|' in result.stdout or '"state"' in result.stdout or terminal:
            subprocess.run(['rsync','-a','--exclude=source/','--exclude=jit/','--exclude=overlay/',
                            '--exclude=*.so','--exclude=*.o','--exclude=probe',
                            'clariden:'+remote+'/',str(a.output/'results')+'/'],check=True,timeout=180)
            subprocess.run(['rsync','-a','clariden:'+base+'/job-'+str(a.job)+'.log',str(a.output)+'/'],check=True,timeout=30)
        if terminal: break
    except Exception as e:
        with (a.output/'history.log').open('a') as f:f.write(repr(e)+'\n')
        if terminal:
            terminal_failures+=1
            if terminal_failures>=3:
                (a.output/'COLLECTION_INCOMPLETE.txt').write_text('Slurm terminal; three collection attempts failed: '+repr(e)+'\n')
                break
    time.sleep(30)
