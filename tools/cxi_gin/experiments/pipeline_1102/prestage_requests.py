#!/usr/bin/env python3
"""Pre-stage gate requests of installed snapshots into a (possibly not yet running) allocation's queue.

usage: prestage_requests.py JOBID SNAPSHOT_DIR [SNAPSHOT_DIR ...] [--only REGEX] [--exclude REGEX] [--dry-run]

The controller creates jobs/<id>/requests at start (mkdir -p), enqueues its own sequence, then runs
every request file in name order, so files placed there beforehand run after the initial sequence
without needing SSH at that time. Each request must name an installed snapshot (checked here against
the campaign's sources/runtime listing) and the names must not collide across the staged snapshots.
"""
import json, re, subprocess, sys, tempfile
from pathlib import Path
CAMPAIGN = '/iopsstor/scratch/cscs/zyu/deepep-pipeline-20261030'
args = sys.argv[1:]; dry = '--dry-run' in args; only = None; exclude = None
if '--only' in args: only = re.compile(args[args.index('--only') + 1]); del args[args.index('--only'):args.index('--only') + 2]
if '--exclude' in args: exclude = re.compile(args[args.index('--exclude') + 1]); del args[args.index('--exclude'):args.index('--exclude') + 2]
args = [a for a in args if a != '--dry-run']; job = int(args[0]); snaps = [Path(a).resolve() for a in args[1:]]
installed = subprocess.run(['ssh', '-o', 'BatchMode=yes', 'clariden', 'ls %s/sources; echo ---; ls %s/runtime' % (CAMPAIGN, CAMPAIGN)], check=True, capture_output=True, text=True).stdout
sources, runtimes = (set(part.split()) for part in installed.split('---'))
specs = []
for snap in snaps:
    assert snap.name in sources and snap.name in runtimes, ('not installed', snap.name)
    for spec in json.loads((snap / 'sequence.json').read_text()):
        assert spec['snapshot'] == CAMPAIGN + '/sources/' + snap.name, spec['snapshot']
        if only and not only.search(spec['name']): continue
        if exclude and exclude.search(spec['name']): continue
        specs.append(spec)
names = [s['name'] for s in specs]; assert len(names) == len(set(names)), 'duplicate gate names across snapshots'
for s in specs:
    s['requires'] = [r for r in s['requires'] if not (exclude and exclude.search(r))]
    for r in s['requires']: assert r in names or re.match(r'^900\d-', r), ('requirement not staged', s['name'], r)
print(len(specs), 'requests:', names[0], '...', names[-1]) if specs else print('nothing selected')
if dry or not specs: sys.exit(0)
with tempfile.TemporaryDirectory() as tmp:
    for s in specs: (Path(tmp) / (s['name'] + '.json')).write_text(json.dumps(s, indent=2) + '\n')
    dest = 'clariden:%s/jobs/%d/requests/' % (CAMPAIGN, job)
    subprocess.run(['ssh', '-o', 'BatchMode=yes', 'clariden', 'mkdir -p %s/jobs/%d/requests' % (CAMPAIGN, job)], check=True)
    subprocess.run(['rsync', '-a', '--ignore-existing', tmp + '/', dest], check=True)
print('staged into jobs/%d/requests' % job)
