#!/usr/bin/env python3
"""Untraced start-stagger timing slice (2026-11-03 midday). Parent: source-1103-ringdiag-v1 (lean-b
transport, dbuf DeepEP code, ring diagnostic). Applied: prepare_stagger_1103.prepare (both DeepEP archives,
nvcc wrapper, ep_benchmark). Arms: leanb (stagger 0), st400, st800 (CXI_EP_STAGGER_NS per channel), all
with the registered ring. A114-A116 are also staged into the holder 3835100's last minutes.

usage: package_stagger_dbg_1103.py results/deepep_pipeline_20261101/source-1103-stagger-dbg-v1
"""
import copy, hashlib, json, shutil, sys
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'pipeline_v1')); sys.path.insert(0, str(HERE))
from prepare_stagger_1103 import prepare  # noqa: E402
ROOT = HERE.parents[3]; NEW = ROOT / 'results/deepep_pipeline_20261101'
REMOTE = '/iopsstor/scratch/cscs/zyu/deepep-pipeline-20261030'
out = Path(sys.argv[1]).resolve(); assert not out.exists(), out
parent = NEW / 'source-1103-ringdiag-v1'
shutil.copytree(parent, out, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
prepare(out, archives=('DeepEP.tar.gz',))  # the dbuf lineage's trace archive predates the first-interval block and is unused here
changed = sorted(str(p.relative_to(out)) for p in out.rglob('*') if p.is_file() and p.name not in ('sequence.json', 'manifest.json')
                 and '__pycache__' not in p.parts and p.read_bytes() != (parent / p.relative_to(out)).read_bytes())
assert changed == ['DeepEP.tar.gz', 'backend/tests/ep_benchmark.py', 'backend/tests/nvcc_wrapper.py'], changed
T = {g['name']: g for g in json.loads((parent / 'sequence.json').read_text())}
snapshot = REMOTE + '/sources/' + out.name
ARMS = {'leanb': '0', 'st400': '400', 'st800': '800'}
FIRST, SHORT, EP_4K16K, EP_4K, SETUP, ALLOC = 175, 95, 95, 70, 10, 25 * 60
seq = []; budget = []
def add(name, tmpl, arm, requires, timeout, expected, tokens=None):
    g = copy.deepcopy(T[tmpl]); g['name'] = name; g['snapshot'] = snapshot; g['requires'] = list(requires)
    g['environment']['CXI_RING_ACCESS'] = 'register'; g['environment']['CXI_EP_STAGGER_NS'] = ARMS[arm]
    if tokens: g['environment']['CXI_EP_TOKENS'] = tokens
    g['timeout_seconds'] = timeout; g['environment']['CXI_TEST_TIMEOUT'] = str(timeout - 60)
    e = g['environment']
    assert e['CXI_VARIANT'] == 'lean-b' and e['CXI_EP_SKIP_COMBINE_FLUSH'] == '1' and e['CXI_EP_LOCAL_SELF_SIGNAL'] == '1'
    assert e['CXI_EP_SMS'] == '64' and e['CXI_EP_CONTEXTS'] == '129' and e['CXI_DEVICE_TRACE'] == '0' and g['qualification'] == 'ep'
    seq.append(g); budget.append(expected); return name
# The first gate of every knob value rebuilds the DeepEP kernels (the JIT keys the -D flags): 300 s each.
# (v1 gave A115/A116 150 s; the holder's A116 was killed by that budget during its rebuild, returncode 124.)
add('A114-st400-repeat2', '9A13-leanb-repeat2', 'st400', [], 300, FIRST, '4096')
add('A115-leanb-repeat2', '9A13-leanb-repeat2', 'leanb', [], 300, FIRST, '4096')
add('A116-st800-repeat2', '9A13-leanb-repeat2', 'st800', [], 300, FIRST, '4096')
c = add('A117-st400-4k-correctness', '9A10-leanb-ringdiag-4k-correctness', 'st400', [], 300, SHORT)
add('A118-st400-repeat1', '9A13-leanb-repeat2', 'st400', [c], 300, EP_4K16K, '4096 16384')
add('A119-leanb-repeat3', '9A13-leanb-repeat2', 'leanb', [], 150, EP_4K, '4096')
add('A11A-st400-repeat3', '9A13-leanb-repeat2', 'st400', [c], 150, EP_4K, '4096')
add('A11B-st800-repeat3', '9A13-leanb-repeat2', 'st800', [c], 150, EP_4K, '4096')
t = SETUP; known = set()
for g, expected in zip(seq, budget):
    assert g['name'] not in known and all(r in known for r in g['requires']), g['name']; known.add(g['name'])
    remaining = ALLOC - t; fits = g['timeout_seconds'] + 180 < remaining
    print('%-30s start %5.1f min  remaining %4d s  timeout %3d  %s' % (g['name'], t / 60, remaining, g['timeout_seconds'], 'ok' if fits else 'DOES NOT FIT'))
    assert fits, g['name']; t += expected
print('expected end of the last gate: %.1f min of %d' % (t / 60, ALLOC // 60))
(out / 'sequence.json').write_text(json.dumps(seq, indent=2) + '\n')
m = json.loads((parent / 'manifest.json').read_text())
m.update(source_parent=str(parent), scope='2026-11-03 untraced start-stagger timing: st400/st800 vs leanb 4K repeats, st400 4K correctness and 4K/16K repeat; registered ring; GPU unqualified')
m['files'] = {str(p.relative_to(out)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(out.rglob('*')) if p.is_file() and p.name != 'manifest.json'}
(out / 'manifest.json').write_text(json.dumps(m, indent=2) + '\n')
print(len(seq), 'gates'); print([g['name'] for g in seq]); print(out)
