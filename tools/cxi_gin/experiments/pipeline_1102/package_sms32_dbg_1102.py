#!/usr/bin/env python3
"""Third debug slice (2026-11-02 evening): fewer, larger PUTs. The traces of job 3837687 put the 4K
dispatch wire phase at 19.5-20 GB/s against the 22.5 GB/s NIC ceiling with receivers idle 86 % of
the time, i.e. the NIC path, not the kernel, paces the transfer, and half of the PUTs are 4-row
(17 KB) ones because 256 channels share 4096 remote rows. The elastic buffer takes 4 channels per
SM, so CXI_EP_SMS=32 gives 128 channels, 32 rows per channel (4 + 16 + 12 rows per channel at 4K),
one channel per context on 129 contexts. Code identical to source-1102-dbuf-v1 (knobs available,
defaults = candidate). Arms: leanb32 (lean-b + kernel knobs, 32 SMs) through the short ladder and
repeats, with cand and leanb at 64 SMs on the same pair as references.

usage: package_sms32_dbg_1102.py results/deepep_pipeline_20261101/source-1102-sms32-dbg-v1
"""
import copy, hashlib, json, shutil, sys
from pathlib import Path
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]; NEW = ROOT / 'results/deepep_pipeline_20261101'
REMOTE = '/iopsstor/scratch/cscs/zyu/deepep-pipeline-20261030'
out = Path(sys.argv[1]).resolve(); assert not out.exists(), out
parent = NEW / 'source-1102-dbuf-v1'
shutil.copytree(parent, out, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
for path in parent.rglob('*'):
    if path.is_file() and path.name not in ('sequence.json', 'manifest.json') and '__pycache__' not in path.parts:
        assert path.read_bytes() == (out / path.relative_to(parent)).read_bytes(), path
T = {g['name']: g for g in json.loads((parent / 'sequence.json').read_text())}
snapshot = REMOTE + '/sources/' + out.name
KERN = dict(CXI_EP_SKIP_COMBINE_FLUSH='1', CXI_EP_LOCAL_SELF_SIGNAL='1')
OFF = dict(CXI_EP_SKIP_COMBINE_FLUSH='0', CXI_EP_LOCAL_SELF_SIGNAL='0', CXI_EP_COMBINE_DOUBLE_TMA='0')
ARMS = {'cand': ('marker-zero', OFF, '64'), 'leanb': ('lean-b', dict(OFF, **KERN), '64'), 'leanb32': ('lean-b', dict(OFF, **KERN), '32')}
FIRST_STRESS, SHORT, FIRST_EP, EP_4K16K, EP_4K, SETUP, ALLOC = 175, 90, 165, 95, 70, 10, 25 * 60
seq = []; budget = []
def add(name, tmpl, arm, requires, timeout, expected, tokens=None):
    g = copy.deepcopy(T[tmpl]); g['name'] = name; g['snapshot'] = snapshot; g['requires'] = list(requires)
    variant, env, sms = ARMS[arm]; g['environment']['CXI_VARIANT'] = variant; g['environment'].update(env)
    g['environment']['CXI_EP_SMS'] = sms; g['environment']['CXI_EP_CONTEXTS'] = '129'
    if tokens: g['environment']['CXI_EP_TOKENS'] = tokens
    g['timeout_seconds'] = timeout; g['environment']['CXI_TEST_TIMEOUT'] = str(timeout - 60)
    assert g['environment']['CXI_DEVICE_TRACE'] == '0' and g['qualification'] == 'ep'
    seq.append(g); budget.append(expected); return name
s = add('9950-leanb32-irregular-stress', '9310-dbuf-irregular-stress', 'leanb32', [], 420, FIRST_STRESS)
c = add('9951-leanb32-4k-correctness', '9311-dbuf-4k-correctness', 'leanb32', [s], 300, SHORT)
d = add('9952-leanb32-dropped-correctness', '9312-dbuf-dropped-correctness', 'leanb32', [c], 300, SHORT)
add('9953-cand-repeat1', '9401-dbuf-repeat1', 'cand', [], 360, FIRST_EP)
add('9954-leanb32-repeat1', '9401-dbuf-repeat1', 'leanb32', [d], 300, EP_4K16K)
add('9955-leanb-repeat1', '9401-dbuf-repeat1', 'leanb', [], 240, EP_4K16K)
add('9956-leanb32-repeat2', '9401-dbuf-repeat1', 'leanb32', [d], 240, EP_4K16K)
add('9957-cand-repeat2', '9401-dbuf-repeat1', 'cand', [], 150, EP_4K, '4096')
add('9958-leanb32-repeat3', '9401-dbuf-repeat1', 'leanb32', [d], 150, EP_4K, '4096')
add('9959-leanb-repeat2', '9401-dbuf-repeat1', 'leanb', [], 150, EP_4K, '4096')
for g in seq:
    e = g['environment']
    assert 'repeat' not in g['name'] or (e['CXI_EP_ITERS'] == '100' and e['CXI_EP_NIC_ITERS'] == '600')
t = SETUP; known = set()
for g, expected in zip(seq, budget):
    assert g['name'] not in known and all(r in known for r in g['requires']), g['name']; known.add(g['name'])
    remaining = ALLOC - t; fits = g['timeout_seconds'] + 180 < remaining
    print('%-32s start %5.1f min  remaining %4d s  timeout %3d  %s' % (g['name'], t / 60, remaining, g['timeout_seconds'], 'ok' if fits else 'DOES NOT FIT'))
    assert fits, g['name']; t += expected
print('expected end of the last gate: %.1f min of %d' % (t / 60, ALLOC // 60))
(out / 'sequence.json').write_text(json.dumps(seq, indent=2) + '\n')
m = json.loads((parent / 'manifest.json').read_text())
m.update(source_parent=str(parent), scope='2026-11-02 debug slice 3: leanb at 32 SMs (128 channels, one per context, fewer and larger PUTs) through stress/4K/dropped and 4K/16K repeats, cand and leanb at 64 SMs as references; code identical to source-1102-dbuf-v1')
m['files'] = {str(p.relative_to(out)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(out.rglob('*')) if p.is_file() and p.name != 'manifest.json'}
(out / 'manifest.json').write_text(json.dumps(m, indent=2) + '\n')
print(len(seq), 'gates'); print([g['name'] for g in seq]); print(out)
