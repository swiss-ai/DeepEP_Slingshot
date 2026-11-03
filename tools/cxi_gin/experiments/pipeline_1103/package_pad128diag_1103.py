#!/usr/bin/env python3
"""Localise the padded-stride hang (2026-11-03 evening): code-identical to source-1103-pad128-v1, four
single-case correctness gates with their own 300 s budgets so that a hang costs one gate, not the job:
BF16 4K (no FP8 scale region: row 8320 B), FP8 32 tokens, FP8 257 tokens, BF16 32 tokens. Which of them
pass tells whether the hang is tied to the FP8 scale region, to the token count (capacity / channel
layout), or to every padded row.

usage: package_pad128diag_1103.py results/deepep_pipeline_20261101/source-1103-pad128-diag-v1
"""
import copy, hashlib, json, shutil, sys
from pathlib import Path
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]; NEW = ROOT / 'results/deepep_pipeline_20261101'
REMOTE = '/iopsstor/scratch/cscs/zyu/deepep-pipeline-20261030'
out = Path(sys.argv[1]).resolve(); assert not out.exists(), out
parent = NEW / 'source-1103-pad128-v1'
shutil.copytree(parent, out, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
C1 = {g['name']: g for g in json.loads((NEW / 'source-1103-combine-v1/sequence.json').read_text())}
snapshot = REMOTE + '/sources/' + out.name
SETUP, ALLOC = 10, 25 * 60
seq = []; budget = []
def add(name, tokens, dtypes, timeout, expected):
    g = copy.deepcopy(C1['C100-split-4k-correctness']); g['name'] = name; g['snapshot'] = snapshot; g['requires'] = []
    e = g['environment']; e['CXI_RING_ACCESS'] = 'register'
    e['CXI_EP_COMBINE_FIRST_TAIL'], e['CXI_EP_COMBINE_SPLIT_BARRIER'], e['CXI_EP_COMBINE_FIRST_BATCH'] = '0', '0', '4'
    e['CXI_EP_TOKENS'] = tokens; e['CXI_EP_DTYPES'] = dtypes; e['CXI_EP_ROUTING'] = 'mixed'; e['CXI_EP_SEEDS'] = '1'
    e['CXI_EP_WARMUP'] = '1'; e['CXI_EP_ITERS'] = '2'; e['CXI_EP_NIC_ITERS'] = '0'
    g['timeout_seconds'] = timeout; e['CXI_TEST_TIMEOUT'] = str(timeout - 60)
    assert e['CXI_VARIANT'] == 'lean-b' and e['CXI_EP_SKIP_COMBINE_FLUSH'] == '1' and e['CXI_EP_LOCAL_SELF_SIGNAL'] == '1'
    seq.append(g); budget.append(expected); return name
add('Q100-pad128-bf16-4k', '4096', 'bf16', 300, 300)
add('Q101-pad128-fp8-32', '32', 'fp8', 300, 300)
add('Q102-pad128-fp8-257', '257', 'fp8', 300, 300)
add('Q103-pad128-bf16-32', '32', 'bf16', 300, 300)
t = SETUP
for g, expected in zip(seq, budget):
    remaining = ALLOC - t; fits = g['timeout_seconds'] + 180 < remaining
    print('%-26s start %5.1f min  remaining %4d s  timeout %3d  %s' % (g['name'], t / 60, remaining, g['timeout_seconds'], 'ok' if fits else 'DOES NOT FIT'))
    assert fits, g['name']; t += expected
print('worst-case end of the last gate: %.1f min of %d' % (t / 60, ALLOC // 60))
(out / 'sequence.json').write_text(json.dumps(seq, indent=2) + '\n')
m = json.loads((parent / 'manifest.json').read_text())
m.update(source_parent=str(parent), scope='2026-11-03 padded-stride hang localisation: single-case correctness gates BF16 4K, FP8 32, FP8 257, BF16 32; code-identical to source-1103-pad128-v1')
m['files'] = {str(p.relative_to(out)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(out.rglob('*')) if p.is_file() and p.name != 'manifest.json'}
(out / 'manifest.json').write_text(json.dumps(m, indent=2) + '\n')
print(len(seq), 'gates'); print([g['name'] for g in seq]); print(out)
