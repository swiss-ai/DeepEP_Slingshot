"""Launch one reviewed immutable plan when its queued allocation becomes ready.

This scheduler does not generate patches, retry failed GPU tests, or submit jobs.
It hands control to the existing fail-closed launcher once, then exits.
"""
import datetime
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

job, plan_name, expected_sha, deadline = sys.argv[1:]
assert job.isdigit() and Path(plan_name).name == plan_name
campaign = Path(__file__).resolve().parent
plan = campaign / plan_name
assert hashlib.sha256(plan.read_bytes()).hexdigest() == expected_sha
end = datetime.datetime.strptime(deadline, '%Y-%m-%dT%H:%M:%SZ')
marker = campaign / ('scheduled-%s-%s' % (job, plan.stem))
marker.mkdir()
root = campaign / 'jobs' / job

def status(state, **extra):
    data = dict(state=state, utc=datetime.datetime.utcnow().isoformat()+'Z',
                job=job, plan=plan_name, sha256=expected_sha, **extra)
    temp = marker/'status.tmp'
    temp.write_text(json.dumps(data, indent=2)+'\n')
    temp.replace(marker/'status.json')
    print(json.dumps(data), flush=True)

status('WAITING_FOR_ALLOCATION')
try:
    while datetime.datetime.utcnow() < end:
        assert hashlib.sha256(plan.read_bytes()).hexdigest() == expected_sha
        states = subprocess.check_output(['squeue','-h','-j',job,'-o','%T'], timeout=30).decode().split()
        if not states:
            status('JOB_NOT_QUEUED_OR_RUNNING'); break
        assert len(states) == 1, states
        state = states[0]
        if state == 'RUNNING' and (root/'status.json').is_file():
            main = json.loads((root/'status.json').read_text())
            if main['state'] == 'PAUSED_FOR_DEBUG':
                status('LAUNCHING')
                output = subprocess.check_output(['python3',str(campaign/'launch_ready_plan_v1.py'),
                    job,plan_name,'run_ready_plan_v3.py'], stderr=subprocess.STDOUT, timeout=60).decode()
                result = json.loads(output)
                assert result['plan_sha256'] == expected_sha
                (marker/'launch.json').write_text(json.dumps(result, indent=2)+'\n')
                status('LAUNCHED', executor=result)
                break
        if state not in ('RUNNING','PENDING','CONFIGURING'):
            status('ALLOCATION_UNAVAILABLE', slurm=state); break
        time.sleep(20)
    else:
        status('CAMPAIGN_DEADLINE')
except Exception as e:
    detail = e.output.decode(errors='replace') if isinstance(e, subprocess.CalledProcessError) else str(e)
    status('REQUIRES_DEBUG', reason=detail)
    raise
