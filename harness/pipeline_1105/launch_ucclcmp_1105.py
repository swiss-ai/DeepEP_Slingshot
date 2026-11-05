#!/usr/bin/env python3
"""Install and submit the UCCL-comparison snapshot to the debug partition (2 nodes, 40 minutes): rsync, runtime
install (install.py), no login-node preflight because the compiled transport sources are identical to the parent
(asserted here: only backend/tests/ep_benchmark.py, runner/node.sh, runner/validate_gate.py and the new
runner/uccl_node.sh may differ), sbatch with partition/time overrides, submission record, local monitor.
Mirrors pipeline_1102/launch_debug_1102.py.

usage: launch_ucclcmp_1105.py results/deepep_pipeline_20261101/source-1105-ucclcmp-v1 [--time 00:40:00] [--submit-only]
"""
import argparse, datetime, json, re, shlex, subprocess, sys
from pathlib import Path
CAMPAIGN = '/iopsstor/scratch/cscs/zyu/deepep-pipeline-20261030'
TESTED = '/iopsstor/scratch/cscs/zyu/deepep-direct-20261026/tenhour/releases/cxi-20261026-201823'
ALLOWED = {'backend/tests/ep_benchmark.py', 'runner/node.sh', 'runner/validate_gate.py', 'runner/uccl_node.sh'}
def remote(argv, **kw):
    return subprocess.run(['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=15', 'clariden', shlex.join(argv)], check=True, **kw)
p = argparse.ArgumentParser(); p.add_argument('snapshot', type=Path)
p.add_argument('--time', default='00:40:00'); p.add_argument('--partition', default='debug')
p.add_argument('--submit-only', action='store_true', help='snapshot already installed; only sbatch, record and monitor')
a = p.parse_args(); snap = a.snapshot.resolve(); root = snap.parent
assert re.fullmatch(r'source-[A-Za-z0-9_-]+', snap.name)
submitted = root / (snap.name + '-submitted.json')
if submitted.exists(): raise SystemExit('Submission already recorded: ' + str(submitted))
manifest = json.loads((snap / 'manifest.json').read_text()); parent = Path(manifest['source_parent'])
parent_files = json.loads((parent / 'manifest.json').read_text())['files']
differs = [k for k, v in manifest['files'].items() if k != 'sequence.json' and parent_files.get(k) != v]
missing = [k for k in parent_files if k != 'sequence.json' and k not in manifest['files']]
assert set(differs) <= ALLOWED and not missing, ('unexpected differences against the parent', sorted(set(differs) - ALLOWED), missing)
compiled = [k for k in differs if k.split('.')[-1] in ('cu', 'cuh', 'cc', 'h', 'hpp', 'gz')]
assert not compiled, ('compiled sources differ; a preflight is required', compiled)
print('differs from', parent.name, ':', differs)
remote(['true'], timeout=25)
source = CAMPAIGN + '/sources/' + snap.name; runtime = CAMPAIGN + '/runtime/' + snap.name
if a.submit_only:
    remote(['test', '-e', runtime])
else:
    remote(['test', '!', '-e', source])
    subprocess.run(['rsync', '-a', '--exclude=__pycache__', '--exclude=*.pyc', str(snap) + '/', 'clariden:' + source + '/'], check=True)
    remote(['python3', source + '/runner/install.py', source, TESTED, runtime])
    remote(['bash', '-n', source + '/runner/node.sh']); remote(['bash', '-n', source + '/runner/uccl_node.sh'])
    uccl = manifest['uccl']
    remote(['test', '-f', uccl['build'] + '/python/uccl/ep.abi3.so']); remote(['test', '-f', uccl['build'] + '/source/ep/bench/buffer.py'])
    remote(['grep', '-q', uccl['extension_sha256'], uccl['build'] + '/binary.sha256'])
preflight = 'skipped: compiled sources identical to ' + parent.name + ' (its preflight passed); differing files: ' + ', '.join(differs)
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
