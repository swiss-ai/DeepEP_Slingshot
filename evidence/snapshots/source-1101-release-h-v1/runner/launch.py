#!/usr/bin/env python3
"""Stage, compile-check, submit once, then start a read-only local monitor."""
import argparse,datetime,fcntl,json,os,re,shlex,subprocess,sys
from pathlib import Path
HERE=Path(__file__).resolve().parent
CAMPAIGN='/iopsstor/scratch/cscs/zyu/deepep-async-20261030'
TESTED='/iopsstor/scratch/cscs/zyu/deepep-direct-20261026/tenhour/releases/cxi-20261026-201823'
def remote(argv,**kw):
    return subprocess.run(['ssh','-o','BatchMode=yes','-o','ConnectTimeout=15','clariden',shlex.join(argv)],check=True,**kw)
def main():
    p=argparse.ArgumentParser();p.add_argument('snapshot',type=Path);a=p.parse_args();snap=a.snapshot.resolve();root=snap.parent
    assert re.fullmatch(r'source-[A-Za-z0-9_-]+',snap.name)
    lock_file=(root/'launch.lock').open('a')
    fcntl.flock(lock_file.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
    submitted=root/'submitted.json'
    if submitted.exists():raise SystemExit('Submission already recorded: '+str(submitted))
    remote(['true'],timeout=25) # No mutation until SSH authentication works.
    source=CAMPAIGN+'/sources/'+snap.name;runtime=CAMPAIGN+'/runtime/'+snap.name
    remote(['test','!','-e',source]);remote(['mkdir','-p',CAMPAIGN+'/sources'])
    subprocess.run(['rsync','-a','--exclude=__pycache__','--exclude=*.pyc',str(snap)+'/', 'clariden:'+source+'/'],check=True)
    remote(['cp','/iopsstor/scratch/cscs/zyu/deepep-v2-20261022/tools/deepep-v2-cxi.toml',CAMPAIGN+'/container.toml'])
    remote(['python3',source+'/runner/install.py',source,TESTED,runtime])
    with (root/'remote-preflight.log').open('w') as f:
        remote(['env','CAMPAIGN='+CAMPAIGN,'INITIAL_SNAPSHOT='+source,'bash',source+'/runner/preflight.sh'],stdout=f,stderr=subprocess.STDOUT,timeout=1200)
    result=remote(['sbatch','--parsable','--export=ALL,CAMPAIGN='+CAMPAIGN+',INITIAL_SNAPSHOT='+source,source+'/runner/run.sbatch'],capture_output=True,text=True)
    raw=result.stdout.strip();assert re.fullmatch(r'\d+(;[A-Za-z0-9_-]+)?',raw),raw;job=int(raw.split(';')[0])
    record=dict(job=job,utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),campaign=CAMPAIGN,snapshot=source,local_snapshot=str(snap),state='SUBMITTED')
    submitted.write_text(json.dumps(record,indent=2)+'\n')
    dest=root/('job-'+str(job));dest.mkdir()
    with (dest/'monitor.log').open('ab') as log:
        proc=subprocess.Popen([sys.executable,str(snap/'runner/monitor.py'),str(job),str(dest)],stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
    record['monitor_pid']=proc.pid;submitted.write_text(json.dumps(record,indent=2)+'\n')
    print(json.dumps(record,indent=2));remote(['squeue','-j',str(job),'-o','%.18i %.10T %.30j %.10M %.20R'])
if __name__=='__main__':main()
