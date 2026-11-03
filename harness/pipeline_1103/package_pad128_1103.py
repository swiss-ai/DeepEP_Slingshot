#!/usr/bin/env python3
"""EP8 demo, second job: the 128-byte padded row stride (prepare_pad128_1103) on top of the bank-routing
test code (parent source-1103-ep8bank-v1). Gates: P100 4K correctness FP8+BF16 (five routings, two seeds,
the standard correctness template), P101 bank cases FP8 (the X100 case list), P102 mixed 4K+16K repeat
(padding's wire cost on the synthetic routing, 16K correctness included), P103 bank cases BF16 dispatch.

usage: package_pad128_1103.py results/deepep_pipeline_20261101/source-1103-pad128-v1
"""
import copy, hashlib, json, shutil, sys
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'pipeline_v1')); sys.path.insert(0, str(HERE))
from prepare_pad128_1103 import prepare  # noqa: E402
ROOT = HERE.parents[3]; NEW = ROOT / 'results/deepep_pipeline_20261101'
REMOTE = '/iopsstor/scratch/cscs/zyu/deepep-pipeline-20261030'
out = Path(sys.argv[1]).resolve(); assert not out.exists(), out
parent = NEW / 'source-1103-ep8bank-v1'
shutil.copytree(parent, out, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
prepare(out)
changed = sorted(str(p.relative_to(out)) for p in out.rglob('*') if p.is_file() and p.name not in ('sequence.json', 'manifest.json')
                 and '__pycache__' not in p.parts and p.read_bytes() != (parent / p.relative_to(out)).read_bytes())
assert changed == ['DeepEP.tar.gz'], changed
C1 = {g['name']: g for g in json.loads((NEW / 'source-1103-combine-v1/sequence.json').read_text())}
X = {g['name']: g for g in json.loads((parent / 'sequence.json').read_text())}
snapshot = REMOTE + '/sources/' + out.name
SETUP, ALLOC = 10, 25 * 60
seq = []; budget = []
def add(name, tmpl, timeout, expected, requires=(), **env):
    g = copy.deepcopy(tmpl); g['name'] = name; g['snapshot'] = snapshot; g['requires'] = list(requires)
    e = g['environment']; e.update(env); e['CXI_RING_ACCESS'] = 'register'
    e['CXI_EP_COMBINE_FIRST_TAIL'], e['CXI_EP_COMBINE_SPLIT_BARRIER'], e['CXI_EP_COMBINE_FIRST_BATCH'] = '0', '0', '4'
    g['timeout_seconds'] = timeout; e['CXI_TEST_TIMEOUT'] = str(timeout - 60)
    assert e['CXI_VARIANT'] == 'lean-b' and e['CXI_EP_SKIP_COMBINE_FLUSH'] == '1' and e['CXI_EP_LOCAL_SELF_SIGNAL'] == '1'
    assert e['CXI_EP_SMS'] == '64' and e['CXI_EP_CONTEXTS'] == '129' and e['CXI_DEVICE_TRACE'] == '0' and g['qualification'] == 'ep'
    seq.append(g); budget.append(expected); return name
c = add('P100-pad128-4k-correctness', C1['C100-split-4k-correctness'], 300, 175)
add('P101-pad128-bank-fp8', X['X100-leanb-bank-fp8'], 480, 260, [c])
add('P102-pad128-mixed-repeat1', C1['C103-leanb-repeat2'], 300, 200, [c], CXI_EP_TOKENS='4096 16384')
add('P103-pad128-bank-bf16', X['X101-leanb-bank-bf16'], 420, 200, [c])
t = SETUP; known = set()
for g, expected in zip(seq, budget):
    assert g['name'] not in known and all(r in known for r in g['requires']), g['name']; known.add(g['name'])
    remaining = ALLOC - t; fits = g['timeout_seconds'] + 180 < remaining
    print('%-30s start %5.1f min  remaining %4d s  timeout %3d  %s' % (g['name'], t / 60, remaining, g['timeout_seconds'], 'ok' if fits else 'DOES NOT FIT'))
    assert fits, g['name']; t += expected
print('expected end of the last gate: %.1f min of %d' % (t / 60, ALLOC // 60))
(out / 'sequence.json').write_text(json.dumps(seq, indent=2) + '\n')
m = json.loads((parent / 'manifest.json').read_text())
m.update(source_parent=str(parent), scope='2026-11-03 EP8 demo job 2: DeepEP rows padded to 128-byte multiples (alignment-cliff fix), correctness then bank cases FP8/BF16 and mixed 4K+16K; GPU unqualified')
m['files'] = {str(p.relative_to(out)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(out.rglob('*')) if p.is_file() and p.name != 'manifest.json'}
(out / 'manifest.json').write_text(json.dumps(m, indent=2) + '\n')
print(len(seq), 'gates'); print([g['name'] for g in seq]); print(out)
