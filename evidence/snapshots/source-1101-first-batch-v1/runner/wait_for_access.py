#!/usr/bin/env python3
"""Bounded auth watcher: submit the already authorized snapshot once, then exit."""
import argparse,datetime,json,subprocess,sys,time
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('snapshot',type=Path);p.add_argument('--seconds',type=int,default=7200);a=p.parse_args()
snap=a.snapshot.resolve();root=snap.parent;deadline=time.monotonic()+a.seconds
state=root/'access-watch.json'
def status(value,**extra):
    state.write_text(json.dumps(dict(state=value,utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),snapshot=str(snap),**extra),indent=2)+'\n')
while time.monotonic()<deadline:
    if (root/'STOP_ACCESS_WATCH').exists():status('STOPPED');break
    if (root/'submitted.json').exists():status('ALREADY_SUBMITTED');break
    try:
        r=subprocess.run(['ssh','-o','BatchMode=yes','-o','ConnectTimeout=10','clariden','true'],capture_output=True,text=True,timeout=20)
    except subprocess.TimeoutExpired:
        status('WAITING_FOR_SSH',reason='SSH timeout')
    else:
        if r.returncode==0:
            status('LAUNCHING')
            # Any staging/build/submission error stops here; never blindly retry
            # sbatch or overwrite an immutable source/runtime.
            with (root/'launch.log').open('a') as f:
                code=subprocess.call([sys.executable,str(snap/'runner/launch.py'),str(snap)],stdout=f,stderr=subprocess.STDOUT)
            status('SUBMITTED' if code==0 else 'LAUNCH_FAILED',returncode=code);break
        status('WAITING_FOR_SSH',reason=r.stderr.strip())
    time.sleep(60)
else:status('EXPIRED_NO_SUBMISSION')
