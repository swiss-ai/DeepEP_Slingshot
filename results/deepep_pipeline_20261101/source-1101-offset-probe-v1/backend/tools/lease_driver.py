#!/usr/bin/env python3
"""Bounded two-node development allocation; serial, explicit requests only.

Not submitted automatically. The agent submits this after the current control
allocation terminates, then atomically publishes a request JSON for each gate.
An idle allocation exits after ten minutes; a STOP file ends it after the active
request. No recurring jobs, source edits, or tests are inferred by this driver.
"""
import datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

from validate_gate import qualify
from allocation_time import allocation_remaining

def within(path, parent):
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False

root = Path(os.environ['LEASE_ROOT'])
base = root.parents[1]
started = time.monotonic()
last_work = started
# The exported end time can reflect the backfill minimum even after Slurm
# grants the full limit. Query the actual allocation; never invent a deadline.
allocation = allocation_remaining(os.environ)
remaining = allocation['remaining_seconds']
reserve = 90 if remaining <= 600 else 150
budget = max(0, min(3600, remaining) - reserve)
deadline = started + budget
seen = set()
(root / 'READY').write_text(json.dumps({'start_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'budget_seconds': budget, 'cleanup_reserve_seconds': reserve, 'allocation': allocation}) + '\n')
while time.monotonic() < deadline and not (root / 'STOP').exists():
    requests = sorted(p for p in (root / 'requests').glob('*.json') if p.name not in seen)
    if not requests:
        if time.monotonic() - last_work > 600:
            break
        time.sleep(2)
        continue
    request = requests[0]
    seen.add(request.name)
    record = {'request': request.name, 'start_utc': datetime.datetime.now(datetime.timezone.utc).isoformat()}
    destination = root / 'results' / request.stem
    destination.mkdir()
    try:
        spec = json.loads(request.read_text())
        for dependency in spec.get('requires', []):
            if Path(dependency).name != dependency or not dependency:
                raise ValueError('dependency must name a local request result')
            prior = json.loads((root / 'results' / dependency / 'FINISHED.json').read_text())
            if prior.get('returncode') != 0 or prior.get('error') or prior.get('qualification', {}).get('status') != 'PASS':
                raise ValueError('dependency did not qualify: ' + dependency)
        source = Path(spec['snapshot']).resolve()
        script = (source / spec['node_script']).resolve()
        if not within(source, base / 'sources') or not within(script, source):
            raise ValueError('request must use an immutable source snapshot under this run')
        if not script.is_file():
            raise ValueError('missing node script')
        duration = int(spec.get('timeout_seconds', 600))
        if duration < 1 or duration > 900:
            raise ValueError('request timeout must be 1..900 seconds')
        allocation = allocation_remaining(os.environ)
        remaining = allocation['remaining_seconds']
        reserve = 90 if remaining <= 600 else 150
        deadline = min(started + 3600, time.monotonic() + max(0, remaining - reserve))
        record['allocation'] = allocation
        if time.monotonic() + duration + 30 > deadline:
            raise ValueError('insufficient allocation time for bounded request')
        env = os.environ.copy()
        overrides = spec.get('environment', {})
        for key, value in overrides.items():
            if not key.startswith(('NCCL_', 'CXI_', 'EP_', 'TEST_')) or not isinstance(value, str):
                raise ValueError('unexpected request environment field')
            env[key] = value
        env.update(OUT=str(destination), SNAPSHOT=str(source))
        record['spec'] = spec
        record['node_script_sha256'] = hashlib.sha256(script.read_bytes()).hexdigest()
        (destination / 'STARTED.json').write_text(json.dumps(record, indent=2) + '\n')
        command = ['timeout', '--signal=TERM', '--kill-after=15s', str(duration),
                   'srun', '--kill-on-bad-exit=1', '--cpu-bind=none',
                   '--environment=/iopsstor/scratch/cscs/zyu/deepep-v2-20261022/tools/deepep-v2-cxi.toml',
                   'bash', str(script)]
        with (destination / 'launch.log').open('w') as log:
            result = subprocess.run(command, env=env, stdout=log, stderr=subprocess.STDOUT)
        record['returncode'] = result.returncode
        if result.returncode == 0 and spec.get('qualification'):
            record['qualification'] = qualify(destination, spec)
        if result.returncode != 0:
            (root / 'STOP').write_text('Request failed: ' + request.name + '\n')
        elif spec.get('stop_after'):
            (root / 'STOP').write_text('Explicit bounded sequence complete: ' + request.name + '\n')
    except Exception as error:
        record['error'] = repr(error)
        # No dependent kernels run after failed validation or insufficient time.
        (root / 'STOP').write_text('Request stopped: ' + request.name + ': ' + str(error) + '\n')
    record['end_utc'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    (destination / 'FINISHED.json').write_text(json.dumps(record, indent=2) + '\n')
    last_work = time.monotonic()
(root / 'FINISHED').write_text(datetime.datetime.now(datetime.timezone.utc).isoformat() + '\n')
