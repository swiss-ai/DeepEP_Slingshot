"""Launch an immutable plan only between completed GPU steps in a held job."""
import hashlib
import json
import socket
import subprocess
import sys
from pathlib import Path


def main():
    job,plan_name,runner_name=sys.argv[1:]
    assert job.isdigit() and Path(plan_name).name==plan_name and Path(runner_name).name==runner_name
    campaign=Path(__file__).resolve().parent;root=campaign/'jobs'/job;plan_path=campaign/plan_name
    data=plan_path.read_bytes();plan=json.loads(data.decode())
    assert json.loads((root/'status.json').read_text())['state']=='PAUSED_FOR_DEBUG'
    for name in ['EXTERNAL_STEP.lock','READY_PLAN_EXECUTOR.lock','RESUME.json']:
        assert not (root/name).exists(),name
    for name in plan['requires']:
        record=json.loads((root/'results'/name/'FINISHED.json').read_text())
        assert record['returncode']==0 and record['qualification']['status']=='PASS',name
    steps=subprocess.check_output(['squeue','--steps','-h','-j',job,'-o','%i']).decode().split()
    assert set(steps)<=set([job+'.batch',job+'.extern']),steps
    log_path=root/(plan_path.stem+'-executor.log')
    assert not log_path.exists(),'Use a new plan/attempt after inspecting the previous executor'
    pause=json.loads((root/'PAUSED.json').read_text())
    pause.update(external_executor=True,ready_plan_sha256=hashlib.sha256(data).hexdigest(),
                 reason='Execute '+plan_name+' between completed GPU steps')
    temp=root/'PAUSED.tmp';temp.write_text(json.dumps(pause,indent=2)+'\n');temp.replace(root/'PAUSED.json')
    with log_path.open('x') as log:
        process=subprocess.Popen([sys.executable,'-u',str(campaign/runner_name),job,str(plan_path)],
            stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
    record=dict(pid=process.pid,host=socket.gethostname(),plan=plan_name,executor=runner_name,
                plan_sha256=hashlib.sha256(data).hexdigest(),
                executor_sha256=hashlib.sha256((campaign/runner_name).read_bytes()).hexdigest())
    (root/(plan_path.stem+'-launch.json')).write_text(json.dumps(record,indent=2)+'\n')
    print(json.dumps(record))


if __name__=='__main__':main()
