"""Read-only status polling independent of potentially slow result collection."""
import argparse
import datetime
import json
import shlex
import subprocess
import time
from pathlib import Path

p = argparse.ArgumentParser()
p.add_argument('job', type=int)
p.add_argument('output', type=Path)
a = p.parse_args()
a.output.mkdir(parents=True, exist_ok=True)
remote = '/iopsstor/scratch/cscs/zyu/deepep-pipeline-20261030/jobs/'+str(a.job)
code = '''import json,subprocess
from pathlib import Path
r=Path(%r)
def read(name):
 p=r/name
 return json.loads(p.read_text()) if p.exists() else None
queue=subprocess.check_output(['squeue','-h','-j',%r,'-o','%%T|%%M|%%L|%%R']).decode().strip()
print(json.dumps(dict(slurm=queue,main=read('status.json'),external=read('EXTERNAL_STATUS.json'),
 plan=read('READY_PLAN_STATUS.json'),external_lock=(r/'EXTERNAL_STEP.lock').exists())))
''' % (remote, str(a.job))
while True:
    row = dict(observed_utc=datetime.datetime.now(datetime.timezone.utc).isoformat())
    try:
        result = subprocess.run(['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10',
            '-o', 'HostName=clariden-ln001.cscs.ch', '-o', 'HostKeyAlias=clariden.alps.cscs.ch',
            'clariden', 'python3 -c '+shlex.quote(code)], capture_output=True, text=True, timeout=25)
        assert result.returncode == 0, result.stderr.strip()
        row.update(json.loads(result.stdout))
        row['probe'] = 'OK'
    except Exception as error:
        row.update(probe='FAILED', error=repr(error))
    temp = a.output/'live-status-fast.tmp'
    temp.write_text(json.dumps(row, indent=2)+'\n')
    temp.replace(a.output/'live-status-fast.json')
    with (a.output/'status-fast-history.jsonl').open('a') as file:
        file.write(json.dumps(row)+'\n')
    if row.get('probe') == 'OK' and not row.get('slurm'):
        break
    time.sleep(20)
