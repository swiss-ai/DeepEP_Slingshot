"""Schedule immutable experiments after a declared trace gate, within one job.

Never interrupts a GPU step. Claims a pause only while the target trace is
running or after it passed, then waits for the main controller to reach that
pause. A failed trace/experiment stays paused for agent diagnosis. Python 3.6.
"""
import datetime
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path


def atomic(path, value):
    temp=path.with_suffix('.tmp');temp.write_text(json.dumps(value,indent=2)+'\n');temp.replace(path)


def main():
    job=sys.argv[1];plan_path=Path(sys.argv[2]).resolve();assert job.isdigit()
    campaign=Path('/iopsstor/scratch/cscs/zyu/deepep-pipeline-20261030')
    root=campaign/'jobs'/job;lock=root/'POST_TRACE_EXECUTOR.lock';lock.mkdir()
    plan_bytes=plan_path.read_bytes();plan=json.loads(plan_bytes.decode())
    plan_sha=hashlib.sha256(plan_bytes).hexdigest();target=plan['after_gate']
    assert Path(target).name==target
    sys.path.insert(0,str(campaign/'sources/source-v1/runner'))
    from allocation_time import allocation_remaining
    env=os.environ.copy();env['SLURM_JOB_ID']=job
    owns_pause=False
    def status(state,**extra):
        data=dict(state=state,utc=datetime.datetime.utcnow().isoformat()+'Z',
                  plan_sha256=plan_sha,after_gate=target,**extra)
        atomic(root/'POST_TRACE_STATUS.json',data);print(json.dumps(data),flush=True)
    def passed(name):
        p=root/'results'/name/'FINISHED.json'
        if not p.is_file():return False
        record=json.loads(p.read_text())
        return record.get('returncode')==0 and record.get('qualification',{}).get('status')=='PASS'
    def claim_pause():
        nonlocal owns_pause
        # A hard link publishes a complete file and cannot overwrite another
        # owner's pause, including a failure reported by the main controller.
        temp=root/'POST_TRACE_PAUSE.tmp'
        temp.write_text(json.dumps(dict(external_executor=True,post_trace_plan=plan_sha,
            reason='Declared experiments after '+target+'; finish current GPU step before holding.'))+'\n')
        try:os.link(str(temp),str(root/'PAUSED.json'))
        except FileExistsError:return False
        finally:temp.unlink()
        owns_pause=True;status('WAITING_FOR_CONTROLLER_HOLD');return True
    try:
        phases=[]
        for phase in plan['phases']:
            source=campaign/'sources'/phase['snapshot'];sequence=campaign/phase['sequence']
            assert source.parent==campaign/'sources' and sequence.is_file()
            assert (campaign/'preflight'/source.name/'PASS').is_file()
            assert hashlib.sha256(sequence.read_bytes()).hexdigest()==phase['sequence_sha256']
            phases.append((source,sequence))
        status('WAITING_FOR_TRACE')
        while True:
            if (root/'STOP').exists():status('STOP_REQUESTED');return
            if time.time()>plan['allocation_end_epoch']-180:
                status('DEFERRED_DECLARED_WINDOW_END');return
            # Use live Slurm accounting, not a stale status/lock, for the window.
            try:
                allocation=allocation_remaining(env)
                if allocation.get('source')!='scontrol current job record':
                    status('OBSERVATION_RETRY',reason=allocation.get('query_error','Live allocation unavailable'))
                    time.sleep(10);continue
                remaining=allocation['remaining_seconds']
            except Exception as error:
                status('OBSERVATION_RETRY',reason=str(error));time.sleep(10);continue
            if remaining<180:status('DEFERRED_ALLOCATION_DEADLINE');return
            state=json.loads((root/'status.json').read_text())
            finished=root/'results'/target/'FINISHED.json'
            if finished.is_file() and not passed(target):
                status('TRACE_FAILED_REQUIRES_DEBUG');return
            busy=(root/'EXTERNAL_STEP.lock').exists() or (root/'TAIL_EXECUTOR.lock').exists()
            is_target=state.get('state')=='RUNNING_STEP' and state.get('request')==target
            if not owns_pause and not busy and not (root/'RESUME.json').exists() and (is_target or passed(target)):
                claim_pause()
            if owns_pause and not busy and state.get('state')=='PAUSED_FOR_DEBUG':
                pause=json.loads((root/'PAUSED.json').read_text())
                assert pause.get('post_trace_plan')==plan_sha,'Pause ownership changed; manual diagnosis required'
                assert not (root/'RESUME.json').exists()
                assert passed(target) and all(passed(n) for n in plan['requires'])
                break
            time.sleep(10)
        for source,sequence in phases:
            if (root/'STOP').exists():status('STOP_REQUESTED');return
            status('RUNNING_PHASE',snapshot=source.name)
            subprocess.check_call([sys.executable,str(campaign/'run_external_v1.py'),job,str(source),str(sequence)])
            external=json.loads((root/'EXTERNAL_STATUS.json').read_text())
            if external['state']=='DEFERRED_ALLOCATION_DEADLINE':
                status('DEFERRED_ALLOCATION_DEADLINE',snapshot=source.name,next_step=external['next_step']);return
            assert external['state']=='COMPLETE',external
            assert all(passed(s['name']) for s in json.loads(sequence.read_text()))
        assert not (root/'EXTERNAL_STEP.lock').exists() and not (root/'RESUME.json').exists()
        assert json.loads((root/'PAUSED.json').read_text()).get('post_trace_plan')==plan_sha
        if (root/'STOP').exists():status('STOP_REQUESTED');return
        atomic(root/'RESUME.json',dict(reason='All declared post-trace experiments passed; resume original queue through GPU-health check.'))
        status('COMPLETE_RESUME_REQUESTED')
    except Exception as error:
        status('REQUIRES_DEBUG',reason=str(error));raise
    finally:lock.rmdir()


if __name__=='__main__':main()
