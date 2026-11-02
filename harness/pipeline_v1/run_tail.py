"""Run two predeclared follow-up phases after delivery validation; stop on failure.

Login-node Python 3.6. This scheduler never edits source or invents fixes. It only
runs immutable, compile-qualified requests and resumes the original controller
after every requested gate has passed. The active agent handles diagnosis.
"""
import datetime
import json
import subprocess
import sys
import time
from pathlib import Path


def main():
    job = sys.argv[1]
    assert job.isdigit()
    campaign = Path('/iopsstor/scratch/cscs/zyu/deepep-pipeline-20261030')
    root = campaign / 'jobs' / job
    lock = root / 'TAIL_EXECUTOR.lock'
    lock.mkdir()
    def status(state, **extra):
        value = dict(state=state, utc=datetime.datetime.utcnow().isoformat()+'Z', **extra)
        temp = root / 'TAIL_STATUS.tmp'
        temp.write_text(json.dumps(value, indent=2)+'\n')
        temp.replace(root / 'TAIL_STATUS.json')
        print(json.dumps(value), flush=True)
    def qualify_sequence(source, missing_allowed=False):
        specs = json.loads((source / 'sequence.json').read_text())
        missing = []
        for spec in specs:
            path = root / 'results' / spec['name'] / 'FINISHED.json'
            if not path.exists():
                missing.append(spec['name'])
                continue
            record = json.loads(path.read_text())
            assert record.get('returncode') == 0 and record.get('qualification', {}).get('status') == 'PASS', str(path)
        assert missing_allowed or not missing, missing
        return missing
    try:
        prerequisite = campaign / 'sources/source-delivery-v3'
        end = time.monotonic() + 1800
        while True:
            assert not (root / 'STOP').exists(), 'STOP requested'
            missing = qualify_sequence(prerequisite, missing_allowed=True)
            if not missing and not (root / 'EXTERNAL_STEP.lock').exists():
                break
            assert time.monotonic() < end, 'delivery sequence did not finish within scheduler deadline'
            status('WAITING_FOR_DELIVERY', missing=missing)
            time.sleep(15)
        for name in ['source-delivery-ladder-v1', 'source-hw-fence-v2']:
            source = campaign / 'sources' / name
            assert (campaign / 'preflight' / name / 'PASS').is_file(), 'compile gate missing: ' + name
            assert not (root / 'STOP').exists(), 'STOP requested'
            status('RUNNING_PHASE', snapshot=name)
            subprocess.check_call([sys.executable, str(campaign / 'run_external_v1.py'), job,
                                   str(source), str(source / 'sequence.json')])
            qualify_sequence(source)
            external = json.loads((root / 'EXTERNAL_STATUS.json').read_text())
            assert external['state'] == 'COMPLETE', external
        assert not (root / 'EXTERNAL_STEP.lock').exists()
        pause = json.loads((root / 'PAUSED.json').read_text())
        assert pause.get('external_executor') is True
        assert not (root / 'RESUME.json').exists()
        temp = root / 'TAIL_RESUME.tmp'
        temp.write_text(json.dumps({'reason': 'All declared delivery-v3, matched transport ladder, and native CQ-fence gates passed. Resume remaining original interval, trace, aggregation and context-sharing requests with the existing GPU-health check.'})+'\n')
        temp.replace(root / 'RESUME.json')
        status('COMPLETE_RESUME_REQUESTED')
    except Exception as error:
        status('PAUSED_FOR_DEBUG', reason=str(error))
        raise
    finally:
        lock.rmdir()


if __name__ == '__main__':
    main()
