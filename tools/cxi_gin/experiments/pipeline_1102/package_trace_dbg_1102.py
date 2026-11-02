#!/usr/bin/env python3
"""Debug-partition slice of the pending matrix (2026-11-02 evening). Code identical to
source-1102-lean-trace-v1 (the private device-trace snapshot of the lean round). Gates, in order:
the three trace gates (cand, kern, leanb at 4K; kind ep_trace) and then ordinary 4K/16K and 4K-only
repeats of cand, kern and leanb on source-1102-dbuf-v1 (a third node pair for the release table).
Timeouts are sized for the 25-minute debug allocation: the controller starts a gate only when
timeout + 180 s fit the remaining time, so the long gates come first and the 4K-only repeats close
the sequence; the budget below uses the durations measured in jobs 3835147/3835199/3835540.

usage: package_trace_dbg_1102.py results/deepep_pipeline_20261101/source-1102-trace-dbg-v1
"""
import copy, hashlib, json, shutil, sys
from pathlib import Path
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]; NEW = ROOT / 'results/deepep_pipeline_20261101'
REMOTE = '/iopsstor/scratch/cscs/zyu/deepep-pipeline-20261030'
out = Path(sys.argv[1]).resolve(); assert not out.exists(), out
parent = NEW / 'source-1102-lean-trace-v1'; ordinary = NEW / 'source-1102-dbuf-v1'
shutil.copytree(parent, out, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
for path in parent.rglob('*'):
    if path.is_file() and path.name not in ('sequence.json', 'manifest.json') and '__pycache__' not in path.parts:
        assert path.read_bytes() == (out / path.relative_to(parent)).read_bytes(), path
TR = {g['name']: g for g in json.loads((parent / 'sequence.json').read_text())}
T = {g['name']: g for g in json.loads((ordinary / 'sequence.json').read_text())}
snapshot = REMOTE + '/sources/' + out.name; ordinary_snapshot = REMOTE + '/sources/' + ordinary.name
KERN = dict(CXI_EP_SKIP_COMBINE_FLUSH='1', CXI_EP_LOCAL_SELF_SIGNAL='1')
OFF = dict(CXI_EP_SKIP_COMBINE_FLUSH='0', CXI_EP_LOCAL_SELF_SIGNAL='0', CXI_EP_COMBINE_DOUBLE_TMA='0')
ARMS = {'cand': ('marker-zero', OFF), 'kern': ('marker-zero', dict(OFF, **KERN)), 'leanb': ('lean-b', dict(OFF, **KERN))}
# Expected durations (s) from the debug jobs: first gate of a variant includes the DeepEP build.
FIRST_TRACE, TRACE, FIRST_EP, EP_4K16K, EP_4K, SETUP, ALLOC = 170, 95, 165, 95, 70, 10, 25 * 60
seq = []; budget = []
def trace(name, tmpl, timeout, expected):
    g = copy.deepcopy(TR[tmpl]); g['name'] = name; g['snapshot'] = snapshot; g['requires'] = []
    g['timeout_seconds'] = timeout; g['environment']['CXI_TEST_TIMEOUT'] = str(timeout - 60)
    assert g['qualification'] == 'ep_trace' and g['environment']['CXI_DEVICE_TRACE'] == '1'
    assert g['environment']['CXI_EP_ITERS'] == '30' and g['environment']['CXI_TRACE_CAPTURES'] == '3'
    seq.append(g); budget.append(expected)
def repeat(name, arm, timeout, expected, tokens='4096 16384'):
    g = copy.deepcopy(T['9401-dbuf-repeat1']); g['name'] = name; g['snapshot'] = ordinary_snapshot; g['requires'] = []
    variant, env = ARMS[arm]; g['environment']['CXI_VARIANT'] = variant; g['environment'].update(env)
    g['environment']['CXI_EP_TOKENS'] = tokens
    g['timeout_seconds'] = timeout; g['environment']['CXI_TEST_TIMEOUT'] = str(timeout - 60)
    e = g['environment']
    assert e['CXI_EP_SMS'] == '64' and e['CXI_EP_CONTEXTS'] == '129' and e['CXI_DEVICE_TRACE'] == '0'
    assert e['CXI_EP_ITERS'] == '100' and e['CXI_EP_NIC_ITERS'] == '600' and g['qualification'] == 'ep'
    seq.append(g); budget.append(expected)
trace('9900-trace-cand-4k', '9800-trace-cand-4k', 420, FIRST_TRACE)
trace('9901-trace-kern-4k', '9801-trace-kern-4k', 300, TRACE)
trace('9902-trace-leanb-4k', '9802-trace-leanb-4k', 420, FIRST_TRACE)
repeat('9903-cand-repeat1', 'cand', 360, FIRST_EP)
repeat('9904-kern-repeat1', 'kern', 300, EP_4K16K)
repeat('9905-leanb-repeat1', 'leanb', 360, FIRST_EP)
repeat('9906-leanb-repeat2', 'leanb', 240, EP_4K16K)
repeat('9907-cand-repeat2', 'cand', 150, EP_4K, '4096')
repeat('9908-kern-repeat2', 'kern', 150, EP_4K, '4096')
repeat('9909-leanb-repeat3', 'leanb', 150, EP_4K, '4096')
t = SETUP; known = set()
for g, expected in zip(seq, budget):
    assert g['name'] not in known; known.add(g['name'])
    remaining = ALLOC - t
    fits = g['timeout_seconds'] + 180 < remaining
    print('%-22s start %5.1f min  remaining %4d s  timeout %3d  %s' % (g['name'], t / 60, remaining, g['timeout_seconds'], 'ok' if fits else 'DOES NOT FIT'))
    assert fits, g['name']
    t += expected
print('expected end of the last gate: %.1f min of %d' % (t / 60, ALLOC // 60))
(out / 'sequence.json').write_text(json.dumps(seq, indent=2) + '\n')
m = json.loads((parent / 'manifest.json').read_text())
m.update(source_parent=str(parent), scope='2026-11-02 debug slice: trace gates cand/kern/leanb at 4K (own archive) and cand/kern/leanb repeats on source-1102-dbuf-v1; code identical to source-1102-lean-trace-v1')
m['files'] = {str(p.relative_to(out)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(out.rglob('*')) if p.is_file() and p.name != 'manifest.json'}
(out / 'manifest.json').write_text(json.dumps(m, indent=2) + '\n')
print(len(seq), 'gates'); print([g['name'] for g in seq]); print(out)
