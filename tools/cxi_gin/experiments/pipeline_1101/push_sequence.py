#!/usr/bin/env python3
"""Push every gate of an installed snapshot's sequence.json into a running allocation's queue.

Runs on the Clariden login node (Python 3.6) via `ssh clariden 'env PUSH_SNAPSHOT=<name>
PUSH_JOB=<jobid> python3 -' < push_sequence.py`. Checks: the snapshot and its runtime are
installed under the campaign, the controller is alive, every request fits the remaining allocation
(timeout + 180 s), and no request name exists yet. Requests are written atomically in name order,
which is the order the controller executes them.
"""
import json, os
campaign = '/iopsstor/scratch/cscs/zyu/deepep-pipeline-20261030'
name = os.environ['PUSH_SNAPSHOT']; job = os.environ['PUSH_JOB']
variant = os.environ.get('PUSH_VARIANT', 'marker-zero')
root = os.path.join(campaign, 'jobs', job); source = os.path.join(campaign, 'sources', name)
assert os.path.isdir(os.path.join(campaign, 'runtime', name, variant)), 'runtime not installed for ' + name
status = json.load(open(os.path.join(root, 'status.json')))
remaining = status.get('remaining_seconds', 0)
print('controller:', status.get('state'), status.get('request', ''), 'remaining %.0f s' % remaining)
assert status.get('state') in ('RUNNING_STEP', 'IDLE_FOR_DEBUG', 'READY'), status
seq = json.load(open(os.path.join(source, 'sequence.json')))
for spec in seq:
    assert spec['snapshot'] == source, spec['snapshot']
    assert spec['timeout_seconds'] + 180 < remaining, ('insufficient allocation time', spec['name'])
    assert not os.path.exists(os.path.join(root, 'requests', spec['name'] + '.json')), spec['name']
for spec in sorted(seq, key=lambda s: s['name']):
    p = os.path.join(root, 'requests', spec['name'] + '.json')
    tmp = p + '.tmp'; json.dump(spec, open(tmp, 'w'), indent=2); os.rename(tmp, p)
print('queued', len(seq), 'requests:', seq[0]['name'], '...', seq[-1]['name'])
