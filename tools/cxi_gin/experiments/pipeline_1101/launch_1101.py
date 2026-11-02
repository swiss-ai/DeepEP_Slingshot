#!/usr/bin/env python3
"""Stage one snapshot, install its runtime, run the transport preflight and the template preflight on the
login node, submit once, and start the read-only local monitor. Adapted from pipeline_v1/launch.py; the
submission record lives next to the snapshot so several snapshots can share one local root."""
import argparse, datetime, json, re, shlex, subprocess, sys
from pathlib import Path
HERE = Path(__file__).resolve().parent
CAMPAIGN = '/iopsstor/scratch/cscs/zyu/deepep-pipeline-20261030'
TESTED = '/iopsstor/scratch/cscs/zyu/deepep-direct-20261026/tenhour/releases/cxi-20261026-201823'
def remote(argv, **kw):
    return subprocess.run(['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=15', 'clariden', shlex.join(argv)], check=True, **kw)
p = argparse.ArgumentParser(); p.add_argument('snapshot', type=Path); p.add_argument('--variant', default='marker-zero')
p.add_argument('--template-preflight', action='store_true'); p.add_argument('--time', default='04:00:00')
p.add_argument('--template-args', nargs='*', default=[])
p.add_argument('--no-submit', action='store_true', help='install and preflight only; the gates are pushed into a running allocation')
a = p.parse_args(); snap = a.snapshot.resolve(); root = snap.parent
assert re.fullmatch(r'source-[A-Za-z0-9_-]+', snap.name)
submitted = root / (snap.name + '-submitted.json')
if submitted.exists(): raise SystemExit('Submission already recorded: ' + str(submitted))
remote(['true'], timeout=25)
source = CAMPAIGN + '/sources/' + snap.name; runtime = CAMPAIGN + '/runtime/' + snap.name
remote(['test', '!', '-e', source])
subprocess.run(['rsync', '-a', '--exclude=__pycache__', '--exclude=*.pyc', str(snap) + '/', 'clariden:' + source + '/'], check=True)
remote(['python3', source + '/runner/install.py', source, TESTED, runtime])
with (root / (snap.name + '-remote-preflight.log')).open('w') as f:
    remote(['env', 'CAMPAIGN=' + CAMPAIGN, 'INITIAL_SNAPSHOT=' + source, 'bash', source + '/runner/preflight.sh'], stdout=f, stderr=subprocess.STDOUT, timeout=1500)
if a.template_preflight:
    subprocess.run(['rsync', '-a', str(HERE / 'preflight_combine_templates.py'), 'clariden:' + CAMPAIGN + '/preflight_combine_templates_1101.py'], check=True)
    with (root / (snap.name + '-template-preflight.log')).open('w') as f:
        remote(["python3", CAMPAIGN + "/preflight_combine_templates_1101.py", source, a.variant] + a.template_args, stdout=f, stderr=subprocess.STDOUT, timeout=2400)
if a.no_submit:
    record = dict(job=None, utc=datetime.datetime.now(datetime.timezone.utc).isoformat(), campaign=CAMPAIGN, snapshot=source, local_snapshot=str(snap), state='INSTALLED_NOT_SUBMITTED')
    submitted.write_text(json.dumps(record, indent=2) + '\n'); print(json.dumps(record, indent=2)); raise SystemExit(0)
sbatch = source + '/runner/run.sbatch'
result = remote(['sbatch', '--parsable', '--time=' + a.time, '--export=ALL,CAMPAIGN=' + CAMPAIGN + ',INITIAL_SNAPSHOT=' + source, sbatch], capture_output=True, text=True)
raw = result.stdout.strip(); assert re.fullmatch(r'\d+(;[A-Za-z0-9_-]+)?', raw), raw; job = int(raw.split(';')[0])
record = dict(job=job, utc=datetime.datetime.now(datetime.timezone.utc).isoformat(), campaign=CAMPAIGN, snapshot=source, local_snapshot=str(snap), state='SUBMITTED', time=a.time)
submitted.write_text(json.dumps(record, indent=2) + '\n')
dest = root / ('job-' + str(job)); dest.mkdir()
with (dest / 'monitor.log').open('ab') as log:
    proc = subprocess.Popen([sys.executable, str(snap / 'runner/monitor.py'), str(job), str(dest)], stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
record['monitor_pid'] = proc.pid; submitted.write_text(json.dumps(record, indent=2) + '\n')
print(json.dumps(record, indent=2)); remote(['squeue', '-j', str(job), '-o', '%.18i %.10T %.30j %.10M %.20R'])
