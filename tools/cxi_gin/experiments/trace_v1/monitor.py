"""Read-only detached monitor; does not edit code or resubmit failed jobs."""
import argparse
import datetime
from pathlib import Path
import subprocess
import time

p=argparse.ArgumentParser();p.add_argument('job',type=int);p.add_argument('output',type=Path);a=p.parse_args()
a.output.mkdir(parents=True,exist_ok=True)
root='/iopsstor/scratch/cscs/zyu/deepep-direct-20261026/trace-20261028'
remote=root+'/jobs/'+str(a.job)
while True:
    cmd=f'squeue -h -j {a.job} -o "%T|%M|%R"; sacct -n -X -j {a.job} --format=State,ExitCode,Elapsed -P; for p in {remote}/build-node*/STAGE {remote}/EXIT_CODE; do if test -f "$p"; then echo "$p"; cat "$p"; fi; done'
    try:
        r=subprocess.run(['ssh','-o','BatchMode=yes','-o','ConnectTimeout=10','clariden',cmd],capture_output=True,text=True,timeout=25)
        text=datetime.datetime.now(datetime.timezone.utc).isoformat()+'\n'+r.stdout+r.stderr
        (a.output/'latest.txt').write_text(text)
        with (a.output/'history.log').open('a') as f:f.write(text+'\n')
        if any(l.startswith(('COMPLETED|','FAILED|','CANCELLED','TIMEOUT|','NODE_FAIL|','OUT_OF_MEMORY|')) for l in r.stdout.splitlines()):
            # Skip native-build intermediates/JIT cubins; retain logs/manifests.
            subprocess.run(['rsync','-a','--exclude=source/','--exclude=jit-capture/','--exclude=jit-build/','--exclude=runtime/','--exclude=overlay/',f'clariden:{remote}/',str(a.output/'results')+'/'],timeout=300,check=True)
            subprocess.run(['rsync','-a',f'clariden:{root}/trace-{a.job}.log',str(a.output)+'/'],timeout=30,check=True)
            break
    except Exception as e:
        with (a.output/'history.log').open('a') as f:f.write(repr(e)+'\n')
    time.sleep(20)
