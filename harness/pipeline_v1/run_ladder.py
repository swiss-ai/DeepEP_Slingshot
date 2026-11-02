#!/usr/bin/env python3
"""Run new qualified gates in an idle held allocation without altering its controller.

Run on the login node with JOB SNAPSHOT. Compatible with Python 3.6. Refuses to
compete with the existing request sequence; writes separate live status/evidence.
"""
import datetime
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path


def atomic(path, value):
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(value, indent=2) + '\n')
    temp.replace(path)


def main():
    job, source = sys.argv[1], Path(sys.argv[2]).resolve()
    campaign = source.parent.parent
    assert job.isdigit() and source.parent.name == 'sources'
    root = campaign / 'jobs' / job
    lock = root / 'EXTERNAL_STEP.lock'
    lock.mkdir()  # One external executor; stale locks require explicit inspection.
    try:
        status = json.loads((root/'status.json').read_text())
        planned_pause = False
        if status['state'] == 'PAUSED_FOR_DEBUG':
            pause = json.loads((root/'PAUSED.json').read_text())
            planned_pause = pause.get('external_ladder') is True
        assert status['state'] == 'IDLE_FOR_DEBUG' or planned_pause, status
        for request in (root/'requests').glob('*.json'):
            finished = root/'results'/request.stem/'FINISHED.json'
            if not finished.exists():
                assert planned_pause, 'original sequence still has pending work'
                continue
            r = json.loads(finished.read_text())
            assert r.get('qualification', {}).get('status') == 'PASS', 'original gate failed'
        assert planned_pause or not (root/'PAUSED.json').exists()
        sys.path.insert(0, str(source/'runner'))
        from allocation_time import allocation_remaining
        from validate_gate import qualify
        env = os.environ.copy()
        env.update(SLURM_JOB_ID=job, CAMPAIGN=str(campaign), SNAPSHOT=str(source),
                   MASTER_PORT=str(24000+int(job)%10000))
        job_info = json.loads(subprocess.check_output(['scontrol','show','job',job,'--json']).decode())['jobs'][0]
        nodes = job_info['nodes']
        env['MASTER_ADDR'] = subprocess.check_output(['scontrol','show','hostnames',nodes]).decode().splitlines()[0]
        for spec in json.loads((source/'sequence.json').read_text()):
            if (root/'STOP').exists():
                break
            assert spec['qualification'] == 'ladder' and spec['snapshot'] == str(source)
            for dependency in spec.get('requires', []):
                r=json.loads((root/'results'/dependency/'FINISHED.json').read_text())
                assert r.get('returncode') == 0 and r.get('qualification', {}).get('status') == 'PASS'
            name = spec['name']
            assert Path(name).name == name
            dest = root/'results'/name
            if dest.exists():
                r = json.loads((dest/'FINISHED.json').read_text())
                assert r.get('qualification', {}).get('status') == 'PASS', 'failed gate requires a new immutable attempt'
                continue
            duration = int(spec['timeout_seconds'])
            remaining = allocation_remaining(env)['remaining_seconds']
            if duration+180 > remaining:
                atomic(root/'EXTERNAL_STATUS.json',dict(state='DEFERRED_ALLOCATION_DEADLINE',next_step=name))
                return
            dest.mkdir()
            record = dict(spec=spec,start_utc=datetime.datetime.utcnow().isoformat()+'Z',
                          executor_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                          scheduled_between_gates=planned_pause)
            atomic(dest/'STARTED.json',record)
            atomic(root/'EXTERNAL_STATUS.json',dict(state='RUNNING',request=name,remaining_seconds=remaining))
            runenv = env.copy()
            runenv.update(spec['environment'])
            runenv['OUT'] = str(dest)
            cmd = ['timeout','--signal=TERM','--kill-after=20s',str(duration)+'s',
                   'srun','--jobid='+job,'--kill-on-bad-exit=1','--ntasks=2','--ntasks-per-node=1',
                   '--gpus-per-node=4','--cpus-per-task=288','--cpu-bind=none',
                   '--environment='+str(campaign/'container.toml'),'bash',str(source/'runner/node.sh')]
            try:
                with (dest/'launch.log').open('w') as log:
                    record['returncode'] = subprocess.call(cmd,env=runenv,stdout=log,stderr=subprocess.STDOUT)
                assert record['returncode'] == 0, 'Slurm step failed'
                record['qualification'] = qualify(dest,spec)
            except Exception as error:
                record['qualification'] = dict(status='FAIL',reason=str(error))
                record['end_utc'] = datetime.datetime.utcnow().isoformat()+'Z'
                atomic(dest/'FINISHED.json',record)
                atomic(root/'EXTERNAL_STATUS.json',dict(state='PAUSED_FOR_DEBUG',request=name,reason=str(error)))
                raise
            record['end_utc'] = datetime.datetime.utcnow().isoformat()+'Z'
            atomic(dest/'FINISHED.json',record)
        atomic(root/'EXTERNAL_STATUS.json',dict(state='COMPLETE',utc=datetime.datetime.utcnow().isoformat()+'Z'))
    finally:
        lock.rmdir()


if __name__ == '__main__':
    main()
