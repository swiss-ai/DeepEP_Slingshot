"""Audit physical-resource reuse separately from successful GPU payload tests.

Runs after collection; does not mutate submitted jobs or their immutable gates.
"""
import argparse
import json
from pathlib import Path
import re
from validate_gate import qualify, require

PATTERN = re.compile(
    r'CXI pool phase=([a-z-]+) gpu=(\d+) created=(\d+) reused=(\d+) '
    r'allocated=(\d+) idle=(\d+) ct_in_use=(-?\d+) usage_rc=(-?\d+)')
FIELDS = ('gpu', 'created', 'reused', 'allocated', 'idle', 'ct_in_use', 'usage_rc')


def audit_rank(log, gpu, cycles, contexts, persistent):
    events = [dict(phase=m[0], **dict(zip(FIELDS, map(int, m[1:]))))
              for m in PATTERN.findall(log) if int(m[1]) == gpu]
    created = [e for e in events if e['phase'] == 'context-created']
    closed = [e for e in events if e['phase'] == 'context-closed']
    idle = [e for e in events if e['phase'] == 'idle-lni-close']
    # The observed NCCL bootstrap creates a separate four-context bank before
    # the test bank and releases it after the final test cycle. Validate its
    # complete lifetime rather than counting it as one of the requested cycles.
    extra = 0
    if persistent and len(created) == cycles + 1:
        extra = 4
        require(created[0]['created'] == created[0]['allocated'] == extra and
                created[0]['reused'] == created[0]['idle'] == 0,
                'unexpected initial context bank')
        require(len(closed) == cycles + 1 and
                closed[-1]['allocated'] == closed[-1]['idle'] == contexts + extra,
                'initial context bank not released')
        created = created[1:]
        closed = closed[:-1]
    require(len(created) == len(closed) == cycles, 'missing or extra context lifecycle events')
    require(all(e['usage_rc'] == 0 and e['ct_in_use'] >= 0 for e in events),
            'physical resource usage unavailable')
    require(all(e['created'] == e['allocated'] == contexts + extra and e['idle'] == 0 for e in created),
            'physical allocation differs from one context bank')
    require(all(e['allocated'] == contexts + extra and e['idle'] == contexts for e in closed),
            'channels were not all returned to pool')
    if persistent:
        require([e['reused'] for e in created] == [i*contexts for i in range(cycles)],
                'persistent LNI did not reuse each complete channel bank')
        require(all(e['ct_in_use'] <= created[0]['ct_in_use'] for e in created),
                'physical CT usage grows under persistent LNI')
        require(len(idle) == 1, 'persistent window did not span cycles or final LNI was not released')
    else:
        require(all(e['reused'] == 0 for e in created), 'idle LNI was retained across cycles')
        require(len(idle) == cycles, 'idle LNI cleanup did not execute after each cycle')
    return dict(status='PASS', gpu=gpu, cycles=cycles, contexts=contexts,
                persistent_window=persistent, physical_channels_per_lni=contexts + extra,
                initial_context_bank=extra,
                reuse_count=created[-1]['reused'], idle_lni_closes=len(idle),
                ct_in_use_min=min(e['ct_in_use'] for e in created),
                ct_in_use_max=max(e['ct_in_use'] for e in created),
                ct_in_use_last=created[-1]['ct_in_use'])


def analyze(root):
    root = Path(root)
    done = json.loads((root/'FINISHED.json').read_text())
    require(done.get('returncode') == 0 and not done.get('error'), 'request did not finish successfully')
    verdict = qualify(root, done['spec'])
    env = done['spec']['environment']
    dims = list(map(int, env['CXI_SMOKE_CONTEXTS'].split(',')))
    require(len(dims) >= 20 and len(set(dims)) == 1, 'requires repeated, fixed-size lifecycle stress')
    persistent = env.get('CXI_LIFECYCLE_HOLD_WINDOW') == '1'
    rows = []
    for node in range(2):
        log = (root/'direct'/('node%d' % node)/'smoke.log').read_text()
        for gpu in range(4):
            rows.append(dict(rank=node*4+gpu, **audit_rank(log, gpu, len(dims), dims[0], persistent)))
    return dict(status='PASS', qualification=verdict, ranks=rows,
                scope='Payload/teardown qualification plus physical-channel reuse or idle-LNI cleanup; no bandwidth claim')


if __name__ == '__main__':
    p = argparse.ArgumentParser(); p.add_argument('result', type=Path); args = p.parse_args()
    result = analyze(args.result)
    (args.result/'lifecycle-resource-validation.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(result, indent=2))
