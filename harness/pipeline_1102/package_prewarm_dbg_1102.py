#!/usr/bin/env python3
"""Fifth debug slice (2026-11-02 late evening): context prewarm in the entry barrier
(prepare_prewarm_1102.prepare on source-1102-dbuf-v1; transport lean-b, ABI 3). Arms: leanb (control)
and leanbw (CXI_EP_PREWARM_CONTEXTS=1) through irregular stress and 4K correctness, then interleaved
4K/16K and 4K-only repeats, with a cand reference at the end.

usage: package_prewarm_dbg_1102.py results/deepep_pipeline_20261101/source-1102-prewarm-dbg-v1
"""
import copy, hashlib, json, shutil, sys
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'pipeline_v1')); sys.path.insert(0, str(HERE))
from prepare_prewarm_1102 import prepare  # noqa: E402
ROOT = HERE.parents[3]; NEW = ROOT / 'results/deepep_pipeline_20261101'
REMOTE = '/iopsstor/scratch/cscs/zyu/deepep-pipeline-20261030'
out = Path(sys.argv[1]).resolve(); assert not out.exists(), out
parent = NEW / 'source-1102-dbuf-v1'
shutil.copytree(parent, out, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
prepare(out)
changed = sorted(str(p.relative_to(out)) for p in out.rglob('*') if p.is_file() and p.name not in ('sequence.json', 'manifest.json')
                 and '__pycache__' not in p.parts and p.read_bytes() != (parent / p.relative_to(out)).read_bytes())
assert changed == ['DeepEP.tar.gz', 'backend/device/gin_cxi.cuh', 'backend/tests/ep_benchmark.py', 'backend/tests/nvcc_wrapper.py'], changed
T = {g['name']: g for g in json.loads((parent / 'sequence.json').read_text())}
snapshot = REMOTE + '/sources/' + out.name
KERN = dict(CXI_EP_SKIP_COMBINE_FLUSH='1', CXI_EP_LOCAL_SELF_SIGNAL='1')
OFF = dict(CXI_EP_SKIP_COMBINE_FLUSH='0', CXI_EP_LOCAL_SELF_SIGNAL='0', CXI_EP_COMBINE_DOUBLE_TMA='0', CXI_EP_PREWARM_CONTEXTS='0')
ARMS = {'cand': ('marker-zero', OFF), 'leanb': ('lean-b', dict(OFF, **KERN)), 'leanbw': ('lean-b', dict(OFF, **KERN, CXI_EP_PREWARM_CONTEXTS='1'))}
FIRST_STRESS, SHORT, FIRST_EP, EP_4K16K, EP_4K, SETUP, ALLOC = 175, 90, 165, 95, 70, 10, 25 * 60
seq = []; budget = []
def add(name, tmpl, arm, requires, timeout, expected, tokens=None):
    g = copy.deepcopy(T[tmpl]); g['name'] = name; g['snapshot'] = snapshot; g['requires'] = list(requires)
    variant, env = ARMS[arm]; g['environment']['CXI_VARIANT'] = variant; g['environment'].update(env)
    if tokens: g['environment']['CXI_EP_TOKENS'] = tokens
    g['timeout_seconds'] = timeout; g['environment']['CXI_TEST_TIMEOUT'] = str(timeout - 60)
    e = g['environment']
    assert e['CXI_EP_SMS'] == '64' and e['CXI_EP_CONTEXTS'] == '129' and e['CXI_DEVICE_TRACE'] == '0' and g['qualification'] == 'ep'
    assert 'repeat' not in name or (e['CXI_EP_ITERS'] == '100' and e['CXI_EP_NIC_ITERS'] == '600')
    seq.append(g); budget.append(expected); return name
s = add('9990-leanbw-irregular-stress', '9310-dbuf-irregular-stress', 'leanbw', [], 420, FIRST_STRESS)
c = add('9991-leanbw-4k-correctness', '9311-dbuf-4k-correctness', 'leanbw', [s], 300, SHORT)
add('9992-leanb-repeat1', '9401-dbuf-repeat1', 'leanb', [], 300, EP_4K16K)
add('9993-leanbw-repeat1', '9401-dbuf-repeat1', 'leanbw', [c], 300, EP_4K16K)
add('9994-leanb-repeat2', '9401-dbuf-repeat1', 'leanb', [], 150, EP_4K, '4096')
add('9995-leanbw-repeat2', '9401-dbuf-repeat1', 'leanbw', [c], 150, EP_4K, '4096')
add('9996-leanbw-repeat3', '9401-dbuf-repeat1', 'leanbw', [c], 150, EP_4K, '4096')
add('9997-leanb-repeat3', '9401-dbuf-repeat1', 'leanb', [], 150, EP_4K, '4096')
add('9998-cand-repeat1', '9401-dbuf-repeat1', 'cand', [], 360, FIRST_EP)
add('9999-leanbw-repeat4', '9401-dbuf-repeat1', 'leanbw', [c], 150, EP_4K, '4096')
t = SETUP; known = set()
for g, expected in zip(seq, budget):
    assert g['name'] not in known and all(r in known for r in g['requires']), g['name']; known.add(g['name'])
    remaining = ALLOC - t; fits = g['timeout_seconds'] + 180 < remaining
    print('%-32s start %5.1f min  remaining %4d s  timeout %3d  %s' % (g['name'], t / 60, remaining, g['timeout_seconds'], 'ok' if fits else 'DOES NOT FIT'))
    assert fits, g['name']; t += expected
print('expected end of the last gate: %.1f min of %d' % (t / 60, ALLOC // 60))
(out / 'sequence.json').write_text(json.dumps(seq, indent=2) + '\n')
m = json.loads((parent / 'manifest.json').read_text())
m.update(source_parent=str(parent), scope='2026-11-02 debug slice 5: context prewarm in the GIN barrier (CXI_EP_PREWARM_CONTEXTS) on lean-b; leanbw stress/4K ladder, leanb vs leanbw repeats, cand reference; GPU unqualified')
m['files'] = {str(p.relative_to(out)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(out.rglob('*')) if p.is_file() and p.name != 'manifest.json'}
(out / 'manifest.json').write_text(json.dumps(m, indent=2) + '\n')
print(len(seq), 'gates'); print([g['name'] for g in seq]); print(out)
