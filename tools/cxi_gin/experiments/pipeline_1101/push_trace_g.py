#!/usr/bin/env python3
"""Push the two trace gates of source-1101-trace-g-v1 into a running allocation's request queue.

Runs on the Clariden login node (Python 3.6): `ssh clariden 'python3 -' < push_trace_g.py JOBID`
is not possible with stdin scripts, so the job id is read from the TRACE_G_JOB environment
variable or defaults to allocation F (3830101). The allocation's controller predates the
configuration-aware trace qualification, so the kind is rewritten to 'ep' (ordinary exact
correctness of the traced run); the device traces are validated offline with
runner/validate_trace.py of the snapshot. Requests are written atomically and only if absent.
"""
import json, os
campaign = '/iopsstor/scratch/cscs/zyu/deepep-pipeline-20261030'
job = os.environ.get('TRACE_G_JOB', '3830101')
root = os.path.join(campaign, 'jobs', job)
source = os.path.join(campaign, 'sources', 'source-1101-trace-g-v1')
runtime = os.path.join(campaign, 'runtime', 'source-1101-trace-g-v1', 'marker-zero-trace')
assert os.path.isdir(runtime), 'runtime not installed: ' + runtime
status = json.load(open(os.path.join(root, 'status.json')))
print('controller:', status.get('state'), status.get('request', ''), 'remaining %.0f s' % status.get('remaining_seconds', 0))
seq = json.load(open(os.path.join(source, 'sequence.json')))
for spec in seq:
    assert spec['snapshot'] == source, spec['snapshot']
    spec = dict(spec, qualification='ep')
    assert spec['timeout_seconds'] + 180 < status.get('remaining_seconds', 0), 'insufficient allocation time'
    p = os.path.join(root, 'requests', spec['name'] + '.json'); assert not os.path.exists(p), p
    tmp = p + '.tmp'; json.dump(spec, open(tmp, 'w'), indent=2); os.rename(tmp, p)
    print('queued', spec['name'], 'kind', spec['qualification'], 'env knobs',
          {k: v for k, v in spec['environment'].items() if 'FIRST' in k or 'TRACE' in k})
