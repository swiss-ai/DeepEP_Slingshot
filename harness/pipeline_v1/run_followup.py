"""Execute named immutable phases in the held allocation; halt on any failure."""
import datetime
import json
import re
import subprocess
import sys
from pathlib import Path


def main():
    job=sys.argv[1];names=sys.argv[2:]
    assert job.isdigit() and names
    assert all(re.match(r'^source-[a-zA-Z0-9_-]+$',name) for name in names)
    campaign=Path('/iopsstor/scratch/cscs/zyu/deepep-pipeline-20261030')
    root=campaign/'jobs'/job;lock=root/'TAIL_EXECUTOR.lock';lock.mkdir()
    def status(state,**extra):
        data=dict(state=state,utc=datetime.datetime.utcnow().isoformat()+'Z',**extra)
        temporary=root/'TAIL_STATUS.tmp';temporary.write_text(json.dumps(data,indent=2)+'\n')
        temporary.replace(root/'TAIL_STATUS.json');print(json.dumps(data),flush=True)
    try:
        assert not (root/'EXTERNAL_STEP.lock').exists()
        assert json.loads((root/'PAUSED.json').read_text()).get('external_executor') is True
        for name in names:
            source=campaign/'sources'/name
            assert (campaign/'preflight'/name/'PASS').is_file(),'compile prerequisite missing'
            assert not (root/'STOP').exists(),'STOP requested'
            status('RUNNING_PHASE',snapshot=name)
            subprocess.check_call([sys.executable,str(campaign/'run_external_v1.py'),job,
                                   str(source),str(source/'sequence.json')])
            for spec in json.loads((source/'sequence.json').read_text()):
                record=json.loads((root/'results'/spec['name']/'FINISHED.json').read_text())
                assert record.get('returncode')==0 and record.get('qualification',{}).get('status')=='PASS',spec['name']
            assert json.loads((root/'EXTERNAL_STATUS.json').read_text())['state']=='COMPLETE'
        assert not (root/'EXTERNAL_STEP.lock').exists()
        assert not (root/'RESUME.json').exists() and not (root/'STOP').exists()
        temporary=root/'TAIL_RESUME.tmp'
        temporary.write_text(json.dumps(dict(reason='All follow-up phase gates passed: '+', '.join(names)+'. Resume original requests through its GPU-health check.'))+'\n')
        temporary.replace(root/'RESUME.json');status('COMPLETE_RESUME_REQUESTED',snapshots=names)
    except Exception as error:
        status('PAUSED_FOR_DEBUG',reason=str(error));raise
    finally:
        lock.rmdir()


if __name__=='__main__':main()
