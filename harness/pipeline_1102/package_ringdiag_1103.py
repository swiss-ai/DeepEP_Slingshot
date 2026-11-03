#!/usr/bin/env python3
"""Ring registration diagnostic + ATS ring access slice (2026-11-03 morning).
prepare_ringdiag_1103.prepare on source-1102-dbuf-v1 (lean-b transport, ABI 3, dbuf DeepEP code); host
code only. Arms: leanb (lean-b + kernel knobs, CXI_RING_ACCESS=register; prints the diagnostic) and
ats (same + CXI_RING_ACCESS=ats). Gates 9A10–9A12 are also staged into the idle holder 3835100.

usage: package_ringdiag_1103.py results/deepep_pipeline_20261101/source-1103-ringdiag-v1
"""
import copy, hashlib, json, shutil, sys
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'pipeline_v1')); sys.path.insert(0, str(HERE))
from prepare_ringdiag_1103 import prepare  # noqa: E402
ROOT = HERE.parents[3]; NEW = ROOT / 'results/deepep_pipeline_20261101'
REMOTE = '/iopsstor/scratch/cscs/zyu/deepep-pipeline-20261030'
out = Path(sys.argv[1]).resolve(); assert not out.exists(), out
parent = NEW / 'source-1102-dbuf-v1'
shutil.copytree(parent, out, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
prepare(out)
changed = sorted(str(p.relative_to(out)) for p in out.rglob('*') if p.is_file() and p.name not in ('sequence.json', 'manifest.json')
                 and '__pycache__' not in p.parts and p.read_bytes() != (parent / p.relative_to(out)).read_bytes())
assert changed == ['backend/host/cxi_resources.cc'], changed
t = (out / 'backend/host/cxi_resources.cc').read_text()
assert t.count('CXI_MAP gpu=') == 1 and t.count('CXI_GPU_ADDRESSING') == 1 and t.count('ring_access_name()') == 4 and 'iomem_fallbacks=%u' in t
T = {g['name']: g for g in json.loads((parent / 'sequence.json').read_text())}
snapshot = REMOTE + '/sources/' + out.name
KERN = dict(CXI_EP_SKIP_COMBINE_FLUSH='1', CXI_EP_LOCAL_SELF_SIGNAL='1')
OFF = dict(CXI_EP_SKIP_COMBINE_FLUSH='0', CXI_EP_LOCAL_SELF_SIGNAL='0', CXI_EP_COMBINE_DOUBLE_TMA='0')
ARMS = {'leanb': ('lean-b', dict(OFF, **KERN, CXI_RING_ACCESS='register')), 'ats': ('lean-b', dict(OFF, **KERN, CXI_RING_ACCESS='ats'))}
FIRST, SHORT, EP_4K16K, EP_4K, SETUP, ALLOC = 175, 95, 95, 70, 10, 25 * 60
seq = []; budget = []
def add(name, tmpl, arm, requires, timeout, expected, tokens=None):
    g = copy.deepcopy(T[tmpl]); g['name'] = name; g['snapshot'] = snapshot; g['requires'] = list(requires)
    variant, env = ARMS[arm]; g['environment']['CXI_VARIANT'] = variant; g['environment'].update(env)
    if tokens: g['environment']['CXI_EP_TOKENS'] = tokens
    g['timeout_seconds'] = timeout; g['environment']['CXI_TEST_TIMEOUT'] = str(timeout - 60)
    e = g['environment']
    assert e['CXI_EP_SMS'] == '64' and e['CXI_EP_CONTEXTS'] == '129' and e['CXI_DEVICE_TRACE'] == '0' and g['qualification'] == 'ep' and e['CXI_QUEUE_INVENTORY'] == '1'
    assert 'repeat' not in name or (e['CXI_EP_ITERS'] == '100' and e['CXI_EP_NIC_ITERS'] == '600')
    seq.append(g); budget.append(expected); return name
d = add('9A10-leanb-ringdiag-4k-correctness', '9311-dbuf-4k-correctness', 'leanb', [], 420, FIRST)
a = add('9A11-ats-4k-correctness', '9311-dbuf-4k-correctness', 'ats', [d], 300, SHORT)
add('9A12-ats-repeat2', '9401-dbuf-repeat1', 'ats', [a], 150, EP_4K, '4096')
add('9A13-leanb-repeat2', '9401-dbuf-repeat1', 'leanb', [], 150, EP_4K, '4096')
add('9A14-ats-repeat1', '9401-dbuf-repeat1', 'ats', [a], 300, EP_4K16K)
add('9A15-ats-irregular-stress', '9310-dbuf-irregular-stress', 'ats', [a], 420, SHORT)
add('9A16-ats-repeat3', '9401-dbuf-repeat1', 'ats', [a], 150, EP_4K, '4096')
add('9A17-leanb-repeat3', '9401-dbuf-repeat1', 'leanb', [], 150, EP_4K, '4096')
t = SETUP; known = set()
for g, expected in zip(seq, budget):
    assert g['name'] not in known and all(r in known for r in g['requires']), g['name']; known.add(g['name'])
    remaining = ALLOC - t; fits = g['timeout_seconds'] + 180 < remaining
    print('%-36s start %5.1f min  remaining %4d s  timeout %3d  %s' % (g['name'], t / 60, remaining, g['timeout_seconds'], 'ok' if fits else 'DOES NOT FIT'))
    assert fits, g['name']; t += expected
print('expected end of the last gate: %.1f min of %d' % (t / 60, ALLOC // 60))
(out / 'sequence.json').write_text(json.dumps(seq, indent=2) + '\n')
m = json.loads((parent / 'manifest.json').read_text())
m.update(source_parent=str(parent), scope='2026-11-03 ring registration diagnostic (CXI_MAP, CXI_GPU_ADDRESSING, pool map counts) and CXI_RING_ACCESS=ats on lean-b; leanb vs ats correctness, stress and 4K/16K repeats; host code only; GPU unqualified')
m['files'] = {str(p.relative_to(out)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(out.rglob('*')) if p.is_file() and p.name != 'manifest.json'}
(out / 'manifest.json').write_text(json.dumps(m, indent=2) + '\n')
print(len(seq), 'gates'); print([g['name'] for g in seq]); print(out)
