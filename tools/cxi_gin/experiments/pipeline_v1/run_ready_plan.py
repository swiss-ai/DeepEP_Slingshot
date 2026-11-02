"""Run an immutable plan in an explicitly held allocation; no competing steps."""
import hashlib
import json
import subprocess
import sys
from pathlib import Path


def main():
    job = sys.argv[1]; plan_path = Path(sys.argv[2]).resolve(); assert job.isdigit()
    campaign = plan_path.parent; root = campaign / 'jobs' / job
    plan_bytes = plan_path.read_bytes(); plan = json.loads(plan_bytes.decode())
    assert isinstance(plan.get('resume_original', True), bool)
    digest = hashlib.sha256(plan_bytes).hexdigest()
    lock = root / 'READY_PLAN_EXECUTOR.lock'; lock.mkdir()
    def status(state, **extra):
        data = dict(state=state, plan_sha256=digest, **extra)
        temp = root / 'READY_PLAN_STATUS.tmp'; temp.write_text(json.dumps(data, indent=2) + '\n')
        temp.replace(root / 'READY_PLAN_STATUS.json'); print(json.dumps(data), flush=True)
    def passed(name):
        record = json.loads((root / 'results' / name / 'FINISHED.json').read_text())
        return record.get('returncode') == 0 and record.get('qualification', {}).get('status') == 'PASS'
    try:
        assert json.loads((root / 'status.json').read_text())['state'] == 'PAUSED_FOR_DEBUG'
        assert json.loads((root / 'PAUSED.json').read_text()).get('ready_plan_sha256') == digest
        assert not any((root / name).exists() for name in ['EXTERNAL_STEP.lock', 'TAIL_EXECUTOR.lock', 'POST_TRACE_EXECUTOR.lock', 'RESUME.json'])
        assert all(passed(name) for name in plan['requires'])
        for phase in plan['phases']:
            source = campaign / 'sources' / phase['snapshot']; sequence = campaign / phase['sequence']
            assert (campaign / 'preflight' / source.name / 'PASS').is_file()
            assert hashlib.sha256(sequence.read_bytes()).hexdigest() == phase['sequence_sha256']
        for phase in plan['phases']:
            if (root / 'STOP').exists(): status('STOP_REQUESTED'); return
            source = campaign / 'sources' / phase['snapshot']; sequence = campaign / phase['sequence']
            status('RUNNING_PHASE', snapshot=source.name)
            subprocess.check_call([sys.executable, str(campaign / 'run_external_v2.py'), job, str(source), str(sequence)])
            external = json.loads((root / 'EXTERNAL_STATUS.json').read_text())
            if external['state'] == 'DEFERRED_ALLOCATION_DEADLINE':
                status('DEFERRED_ALLOCATION_DEADLINE', snapshot=source.name, next_step=external['next_step']); return
            assert external['state'] == 'COMPLETE'
            assert all(passed(step['name']) for step in json.loads(sequence.read_text()))
        assert not (root / 'EXTERNAL_STEP.lock').exists() and not (root / 'RESUME.json').exists()
        assert json.loads((root / 'PAUSED.json').read_text()).get('ready_plan_sha256') == digest
        if not plan.get('resume_original', True):
            status('COMPLETE_HELD')
            return
        temp = root / 'RESUME.tmp'
        temp.write_text(json.dumps(dict(reason='All configuration-aware trace and prepared experiment gates passed; health-check resume original queue.')) + '\n')
        temp.replace(root / 'RESUME.json'); status('COMPLETE_RESUME_REQUESTED')
    except Exception as error:
        status('REQUIRES_DEBUG', reason=str(error)); raise
    finally:
        lock.rmdir()


if __name__ == '__main__':
    main()
