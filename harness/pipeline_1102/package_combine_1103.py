#!/usr/bin/env python3
"""Combine levers, untraced timing slice (2026-11-03 afternoon). Parent: source-1103-ringdiag-v1 (lean-b
transport, dbuf DeepEP code, ring diagnostic). Applied: prepare_combine_1103.prepare on DeepEP.tar.gz (the
lineage's trace archive is stale and unused here), nvcc wrapper, ep_benchmark.

Arms (CXI_EP_COMBINE_FIRST_TAIL / CXI_EP_COMBINE_SPLIT_BARRIER / CXI_EP_COMBINE_FIRST_BATCH): leanb 0/0/4
(release candidate), tail1 1/0/4, split 0/1/4, both 1/1/4; registered ring. Every new-code arm passes the
4K correctness gate (fp8+bf16, five routings, two seeds) before its timing gates run. The first gate of
every knob set rebuilds the DeepEP kernels (the JIT keys the -D flags): 300 s timeouts there.

usage: package_combine_1103.py results/deepep_pipeline_20261101/source-1103-combine-v1
"""
import copy, hashlib, json, shutil, sys
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'pipeline_v1')); sys.path.insert(0, str(HERE))
from prepare_combine_1103 import prepare  # noqa: E402
ROOT = HERE.parents[3]; NEW = ROOT / 'results/deepep_pipeline_20261101'
REMOTE = '/iopsstor/scratch/cscs/zyu/deepep-pipeline-20261030'
out = Path(sys.argv[1]).resolve(); assert not out.exists(), out
parent = NEW / 'source-1103-ringdiag-v1'
shutil.copytree(parent, out, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
prepare(out, archives=('DeepEP.tar.gz',))
changed = sorted(str(p.relative_to(out)) for p in out.rglob('*') if p.is_file() and p.name not in ('sequence.json', 'manifest.json')
                 and '__pycache__' not in p.parts and p.read_bytes() != (parent / p.relative_to(out)).read_bytes())
assert changed == ['DeepEP.tar.gz', 'backend/tests/ep_benchmark.py', 'backend/tests/nvcc_wrapper.py'], changed
T = {g['name']: g for g in json.loads((parent / 'sequence.json').read_text())}
snapshot = REMOTE + '/sources/' + out.name
ARMS = {'leanb': ('0', '0', '4'), 'tail1': ('1', '0', '4'), 'split': ('0', '1', '4'), 'both': ('1', '1', '4')}
FIRST, EP_4K, SETUP, ALLOC = 175, 70, 10, 25 * 60
seq = []; budget = []
def add(name, tmpl, arm, requires, timeout, expected, tokens=None):
    g = copy.deepcopy(T[tmpl]); g['name'] = name; g['snapshot'] = snapshot; g['requires'] = list(requires)
    e = g['environment']; tail, split, first_batch = ARMS[arm]
    e['CXI_RING_ACCESS'] = 'register'; e['CXI_EP_COMBINE_FIRST_TAIL'] = tail; e['CXI_EP_COMBINE_SPLIT_BARRIER'] = split
    e['CXI_EP_COMBINE_FIRST_BATCH'] = first_batch
    if tokens: e['CXI_EP_TOKENS'] = tokens
    g['timeout_seconds'] = timeout; e['CXI_TEST_TIMEOUT'] = str(timeout - 60)
    assert e['CXI_VARIANT'] == 'lean-b' and e['CXI_EP_SKIP_COMBINE_FLUSH'] == '1' and e['CXI_EP_LOCAL_SELF_SIGNAL'] == '1'
    assert e['CXI_EP_SMS'] == '64' and e['CXI_EP_CONTEXTS'] == '129' and e['CXI_DEVICE_TRACE'] == '0' and g['qualification'] == 'ep'
    assert 'CXI_EP_STAGGER_NS' not in e and e['CXI_EP_PACK_COMBINE'] == '1' and e['CXI_EP_COMBINE_BATCH'] == '16'
    seq.append(g); budget.append(expected); return name
CORR, REP = '9A10-leanb-ringdiag-4k-correctness', '9A13-leanb-repeat2'
c_split = add('C100-split-4k-correctness', CORR, 'split', [], 300, FIRST)
c_both = add('C101-both-4k-correctness', CORR, 'both', [], 300, FIRST)
c_tail = add('C102-tail1-4k-correctness', CORR, 'tail1', [], 300, FIRST)
add('C103-leanb-repeat2', REP, 'leanb', [], 300, FIRST, '4096')
add('C104-split-repeat2', REP, 'split', [c_split], 150, EP_4K, '4096')
add('C105-both-repeat2', REP, 'both', [c_both], 150, EP_4K, '4096')
add('C106-tail1-repeat2', REP, 'tail1', [c_tail], 150, EP_4K, '4096')
add('C107-both-repeat3', REP, 'both', [c_both], 150, EP_4K, '4096')
add('C108-leanb-repeat3', REP, 'leanb', [], 150, EP_4K, '4096')
add('C109-split-repeat3', REP, 'split', [c_split], 150, EP_4K, '4096')
add('C10A-tail1-repeat3', REP, 'tail1', [c_tail], 150, EP_4K, '4096')
t = SETUP; known = set()
for g, expected in zip(seq, budget):
    assert g['name'] not in known and all(r in known for r in g['requires']), g['name']; known.add(g['name'])
    remaining = ALLOC - t; fits = g['timeout_seconds'] + 180 < remaining
    print('%-30s start %5.1f min  remaining %4d s  timeout %3d  %s' % (g['name'], t / 60, remaining, g['timeout_seconds'], 'ok' if fits else 'DOES NOT FIT'))
    assert fits, g['name']; t += expected
print('expected end of the last gate: %.1f min of %d' % (t / 60, ALLOC // 60))
(out / 'sequence.json').write_text(json.dumps(seq, indent=2) + '\n')
m = json.loads((parent / 'manifest.json').read_text())
m.update(source_parent=str(parent), scope='2026-11-03 combine pre-wire levers, untraced: first scale-up tail after one round (CXI_EP_COMBINE_FIRST_TAIL) and split entry barrier (CXI_EP_COMBINE_SPLIT_BARRIER) vs lean-b at 4K; correctness before timing; registered ring; GPU unqualified')
m['files'] = {str(p.relative_to(out)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(out.rglob('*')) if p.is_file() and p.name != 'manifest.json'}
(out / 'manifest.json').write_text(json.dumps(m, indent=2) + '\n')
print(len(seq), 'gates'); print([g['name'] for g in seq]); print(out)
