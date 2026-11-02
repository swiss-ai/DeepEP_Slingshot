#!/usr/bin/env python3
"""Collect the isolated ten-hour run without modifying shared workloads."""
import argparse
import datetime
import json
import subprocess
from pathlib import Path

REMOTE = '/iopsstor/scratch/cscs/zyu/deepep-direct-20261026/tenhour'
LOCAL = Path(__file__).resolve().parents[4] / 'results/deepep_direct_10_26/tenhour'

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--job', type=int, action='append', default=[])
    args = parser.parse_args()
    LOCAL.mkdir(parents=True, exist_ok=True)
    status = {'collected_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'errors': []}
    for folder in ['results', 'sources', 'build-logs', 'leases']:
        target = LOCAL / ('attempts' if folder == 'results' else folder)
        target.mkdir(exist_ok=True)
        result = subprocess.run(['rsync', '-a', '--exclude=*.o', '--exclude=*.so',
                                 f'clariden:{REMOTE}/{folder}/', str(target) + '/'],
                                capture_output=True, text=True, timeout=120)
        if result.returncode:
            status['errors'].append({'folder': folder, 'error': result.stderr})
    command = ['rsync', '-a', '--include=control-*.log', '--include=control-*-job.txt',
               '--include=lease-*.log', '--include=lease-*-job.txt',
               '--include=*-build.PASS', '--include=*-build.FAIL', '--exclude=*',
               f'clariden:{REMOTE}/', str(LOCAL) + '/']
    result = subprocess.run(command, capture_output=True, text=True, timeout=60)
    if result.returncode:
        status['errors'].append({'folder': 'metadata', 'error': result.stderr})
    jobs = set(args.job)
    for path in list(LOCAL.glob('control-*-job.txt')) + list(LOCAL.glob('lease-*-job.txt')):
        try:
            jobs.add(int(path.read_text().strip().split(';')[0]))
        except ValueError:
            pass
    if jobs:
        result = subprocess.run(['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=15',
                                 'clariden', 'sacct', '-n', '-P', '-j', ','.join(map(str, sorted(jobs))),
                                 '-o', 'JobID,JobName,State,ExitCode,Elapsed,NodeList'],
                                capture_output=True, text=True, timeout=30)
        status['accounting'] = result.stdout.splitlines()
        if result.returncode:
            status['errors'].append({'sacct': result.stderr})
    status['lease_steps'] = {str(p.relative_to(LOCAL)): json.loads(p.read_text())
                             for p in (LOCAL / 'leases').glob('*/results/*/FINISHED.json')}
    status['attempts'] = {}
    for attempt in sorted((LOCAL / 'attempts').glob('p01-*')):
        entry = {'control_node_pass': len(list(attempt.glob('node*/PASS'))),
                 'direct_node_pass': len(list(attempt.glob('direct/node*/PASS'))),
                 'batch_complete': (attempt / 'JOB_COMPLETED').exists()}
        entry['dynamic_exit_codes'] = {str(p.relative_to(attempt)): p.read_text().splitlines()
                                       for p in attempt.glob('dynamic/node*/status.tsv')}
        entry['direct_ranks'] = {}
        for path in attempt.glob('direct/smoke/rank*.json'):
            try:
                data = json.loads(path.read_text())
                entry['direct_ranks'][path.name] = {k: data.get(k) for k in ['stage', 'contexts', 'cases', 'error']}
            except json.JSONDecodeError:
                entry['direct_ranks'][path.name] = {'incomplete_json': True}
        status['attempts'][attempt.name] = entry
    (LOCAL / 'checkpoint.json').write_text(json.dumps(status, indent=2) + '\n')
    print(json.dumps({'collected_utc': status['collected_utc'],
                      'errors': status['errors'], 'accounting': status.get('accounting', []),
                      'lease_steps': {name: {key: data.get(key) for key in ('returncode', 'error')}
                                      for name, data in status['lease_steps'].items()},
                      'checkpoint': str(LOCAL / 'checkpoint.json')}, indent=2))

if __name__ == '__main__':
    main()
