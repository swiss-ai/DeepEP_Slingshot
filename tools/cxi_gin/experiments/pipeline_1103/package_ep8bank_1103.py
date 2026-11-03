#!/usr/bin/env python3
"""EP8 demo: DeepSeek V4 Flash with bank-consistent OpenSWE routing over the direct-CXI path (2026-11-03
evening). Parent: source-1103-combine-v1 (lean-b transport, kernel knobs available, DeepEP code of the
release candidate). Applied: prepare_ep8bank_1103.prepare (test code and the bank subset only; compiled
sources unchanged, so launch_debug_1102.py needs --new-code only for the file-identity check).

Gates (all 4096 tokens per rank, 20 warm-up + 100 timed iterations + 600 NIC-loop iterations, exact
correctness per case before timing): X100 FP8, release-candidate knobs (first batch 4), 19 cases =
mixed + {forward 300, 301} x {layer 3, 20, 37} x {vanilla, greedy, random}; X101 same with BF16 dispatch;
X102 same with the afternoon's combine knobs (first tail 1, first batch 2); X103 repeat of X100.

usage: package_ep8bank_1103.py results/deepep_pipeline_20261101/source-1103-ep8bank-v1
"""
import copy, hashlib, json, shutil, sys
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'pipeline_v1')); sys.path.insert(0, str(HERE))
from prepare_ep8bank_1103 import prepare  # noqa: E402
ROOT = HERE.parents[3]; NEW = ROOT / 'results/deepep_pipeline_20261101'
REMOTE = '/iopsstor/scratch/cscs/zyu/deepep-pipeline-20261030'
out = Path(sys.argv[1]).resolve(); assert not out.exists(), out
parent = NEW / 'source-1103-combine-v1'
shutil.copytree(parent, out, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
prepare(out)
changed = sorted(str(p.relative_to(out)) for p in out.rglob('*') if p.is_file() and p.name not in ('sequence.json', 'manifest.json')
                 and '__pycache__' not in p.parts and (not (parent / p.relative_to(out)).exists() or p.read_bytes() != (parent / p.relative_to(out)).read_bytes()))
assert changed == ['backend/tests/bank_routing.py', 'backend/tests/bank_v4flash_openswe_ep8.npz', 'backend/tests/ep_benchmark.py'], changed
T = {g['name']: g for g in json.loads((parent / 'sequence.json').read_text())}
snapshot = REMOTE + '/sources/' + out.name
CASES = ['mixed'] + ['bank_f%d_l%d_%s' % (f, l, p) for f in (300, 301) for l in (3, 20, 37) for p in ('vanilla', 'greedy', 'random')]
SETUP, ALLOC = 10, 25 * 60
seq = []; budget = []
def add(name, arm, dtypes, timeout, expected):
    g = copy.deepcopy(T['C103-leanb-repeat2']); g['name'] = name; g['snapshot'] = snapshot; g['requires'] = []
    e = g['environment']; e['CXI_RING_ACCESS'] = 'register'; e['CXI_EP_TOKENS'] = '4096'; e['CXI_EP_DTYPES'] = dtypes
    e['CXI_EP_ROUTING'] = ' '.join(CASES); e['CXI_EP_SEEDS'] = '1'
    e['CXI_EP_COMBINE_FIRST_TAIL'], e['CXI_EP_COMBINE_SPLIT_BARRIER'], e['CXI_EP_COMBINE_FIRST_BATCH'] = arm
    g['timeout_seconds'] = timeout; e['CXI_TEST_TIMEOUT'] = str(timeout - 60)
    assert e['CXI_VARIANT'] == 'lean-b' and e['CXI_EP_SKIP_COMBINE_FLUSH'] == '1' and e['CXI_EP_LOCAL_SELF_SIGNAL'] == '1'
    assert e['CXI_EP_SMS'] == '64' and e['CXI_EP_CONTEXTS'] == '129' and e['CXI_DEVICE_TRACE'] == '0' and g['qualification'] == 'ep'
    assert e['CXI_EP_ITERS'] == '100' and e['CXI_EP_WARMUP'] == '20' and e['CXI_EP_NIC_ITERS'] == '600' and e['CXI_EP_MODELS'] == 'v4flash'
    seq.append(g); budget.append(expected); return name
RELEASE, KNOBS = ('0', '0', '4'), ('1', '0', '2')
add('X100-leanb-bank-fp8', RELEASE, 'fp8', 480, 260)
add('X101-leanb-bank-bf16', RELEASE, 'bf16', 420, 200)
add('X102-tail1fb2-bank-fp8', KNOBS, 'fp8', 480, 260)
add('X103-leanb-bank-fp8-repeat', RELEASE, 'fp8', 300, 170)
t = SETUP
for g, expected in zip(seq, budget):
    remaining = ALLOC - t; fits = g['timeout_seconds'] + 180 < remaining
    print('%-30s start %5.1f min  remaining %4d s  timeout %3d  %s' % (g['name'], t / 60, remaining, g['timeout_seconds'], 'ok' if fits else 'DOES NOT FIT'))
    assert fits, g['name']; t += expected
print('expected end of the last gate: %.1f min of %d' % (t / 60, ALLOC // 60))
(out / 'sequence.json').write_text(json.dumps(seq, indent=2) + '\n')
m = json.loads((parent / 'manifest.json').read_text())
m.update(source_parent=str(parent), scope='2026-11-03 EP8 demo: V4 Flash with bank-consistent OpenSWE routing (forwards 300/301, layers 3/20/37, vanilla/greedy/random placements) vs mixed, FP8 and BF16 dispatch, release knobs and the early-tail/two-row knobs; test code and bank subset only')
m['files'] = {str(p.relative_to(out)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(out.rglob('*')) if p.is_file() and p.name != 'manifest.json'}
(out / 'manifest.json').write_text(json.dumps(m, indent=2) + '\n')
print(len(seq), 'gates'); print([g['name'] for g in seq]); print(len(CASES), 'cases per gate'); print(out)
