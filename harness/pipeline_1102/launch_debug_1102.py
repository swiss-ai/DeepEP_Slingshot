#!/usr/bin/env python3
"""Install one snapshot and submit it to the debug partition (2 nodes, 25 minutes by default): rsync,
runtime install, login-node transport preflight, sbatch with --partition/--time overriding run.sbatch,
submission record next to the snapshot, local read-only monitor. Mirrors pipeline_1101/launch_1101.py.
The EP8 template preflight is skipped: the snapshot must be code-identical to its manifest's
source_parent (every hashed file except sequence.json and manifest.json), which is asserted here, and
that parent's templates were already preflighted.

usage: launch_debug_1102.py results/deepep_pipeline_20261101/source-1102-trace-dbg-v1 [--time 00:25:00] [--partition debug]
"""
import argparse, datetime, json, re, shlex, subprocess, sys
from pathlib import Path
CAMPAIGN = '/iopsstor/scratch/cscs/zyu/deepep-pipeline-20261030'
TESTED = '/iopsstor/scratch/cscs/zyu/deepep-direct-20261026/tenhour/releases/cxi-20261026-201823'
def remote(argv, **kw):
    return subprocess.run(['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=15', 'clariden', shlex.join(argv)], check=True, **kw)
p = argparse.ArgumentParser(); p.add_argument('snapshot', type=Path)
p.add_argument('--time', default='00:25:00'); p.add_argument('--partition', default='debug')
p.add_argument('--allow-diff', nargs='*', default=[], help='runner-side files that may differ from the parent (never compiled sources)')
p.add_argument('--skip-preflight', action='store_true', help='compiled sources are identical to the parent whose preflight passed')
p.add_argument('--submit-only', action='store_true', help='snapshot already installed and preflighted; only sbatch, record and monitor')
p.add_argument('--new-code', action='store_true', help='compiled sources differ from the parent on purpose; full preflight required')
a = p.parse_args(); snap = a.snapshot.resolve(); root = snap.parent
assert re.fullmatch(r'source-[A-Za-z0-9_-]+', snap.name)
submitted = root / (snap.name + '-submitted.json')
if submitted.exists(): raise SystemExit('Submission already recorded: ' + str(submitted))
manifest = json.loads((snap / 'manifest.json').read_text()); parent = Path(manifest['source_parent'])
parent_files = json.loads((parent / 'manifest.json').read_text())['files']
assert all(k.startswith('runner/') and k.endswith('.py') for k in a.allow_diff), a.allow_diff
differs = [k for k, v in manifest['files'].items() if k != 'sequence.json' and k not in a.allow_diff and parent_files.get(k) != v]
missing = [k for k in parent_files if k != 'sequence.json' and k not in manifest['files']]
if a.new_code:
    assert not a.skip_preflight, 'new transport code needs the preflight'
    print('new code against', parent.name, ':', differs, missing)
else:
    assert not differs and not missing, ('snapshot is not code-identical to its parent', differs, missing)
remote(['true'], timeout=25)
source = CAMPAIGN + '/sources/' + snap.name; runtime = CAMPAIGN + '/runtime/' + snap.name
if a.submit_only:
    # Installed and preflighted by an earlier run whose sbatch was refused (e.g. the debug submit limit).
    remote(['test', '-e', runtime]); remote(['test', '-f', CAMPAIGN + '/preflight/' + snap.name + '/TRANSPORT_PREFLIGHT_PASS'])
    preflight = 'TRANSPORT_PREFLIGHT_PASS (earlier run)'
else:
  remote(['test', '!', '-e', source])
  subprocess.run(['rsync', '-a', '--exclude=__pycache__', '--exclude=*.pyc', str(snap) + '/', 'clariden:' + source + '/'], check=True)
  remote(['python3', source + '/runner/install.py', source, TESTED, runtime])
if a.submit_only:
    pass
elif a.skip_preflight:
    preflight = 'skipped: compiled sources identical to ' + parent.name + ' (preflight passed there); differing files: ' + ', '.join(a.allow_diff)
else:
    with (root / (snap.name + '-remote-preflight.log')).open('w') as f:
        remote(['env', 'CAMPAIGN=' + CAMPAIGN, 'INITIAL_SNAPSHOT=' + source, 'bash', source + '/runner/preflight.sh'], stdout=f, stderr=subprocess.STDOUT, timeout=1500)
    remote(['test', '-f', CAMPAIGN + '/preflight/' + snap.name + '/TRANSPORT_PREFLIGHT_PASS']); preflight = 'TRANSPORT_PREFLIGHT_PASS'
sbatch = source + '/runner/run.sbatch'
result = remote(['sbatch', '--parsable', '--partition=' + a.partition, '--time=' + a.time,
                 '--export=ALL,CAMPAIGN=' + CAMPAIGN + ',INITIAL_SNAPSHOT=' + source, sbatch], capture_output=True, text=True)
raw = result.stdout.strip(); assert re.fullmatch(r'\d+(;[A-Za-z0-9_-]+)?', raw), raw; job = int(raw.split(';')[0])
record = dict(job=job, utc=datetime.datetime.now(datetime.timezone.utc).isoformat(), campaign=CAMPAIGN, snapshot=source,
              local_snapshot=str(snap), state='SUBMITTED', time=a.time, partition=a.partition, preflight=preflight)
submitted.write_text(json.dumps(record, indent=2) + '\n')
dest = root / ('job-' + str(job)); dest.mkdir()
with (dest / 'monitor.log').open('ab') as log:
    proc = subprocess.Popen([sys.executable, str(snap / 'runner/monitor.py'), str(job), str(dest)], stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
record['monitor_pid'] = proc.pid; submitted.write_text(json.dumps(record, indent=2) + '\n')
print(json.dumps(record, indent=2)); remote(['squeue', '-j', str(job), '-o', '%.18i %.10T %.30j %.10M %.20R'])
