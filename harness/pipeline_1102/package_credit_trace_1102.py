#!/usr/bin/env python3
"""Traced cached-credit transport (2026-11-02 late evening). Job 3837957 showed the cache working (4.6 k
status reads for 4.6 M commands, every ladder gate PASS incl. sustained 16K) with no change in wall time,
so the first-PUT convoy is not the status read. This snapshot traces lean-c (lean-b + cache), cache-a
(marker-zero + cache) and lean-b on one pair to see where the first PUT's 100 us sits without the reads.

Parent: source-1102-trace-dbg-v2 (lean trace code, G generator, knob-aware validator). Applied:
prepare_credit_1102.prepare(variants=False, preflight=False) on the backend; the generator's capacity
scope anchor moves from `while(true) {` (now present in both branches of emit) to the `#if CXI_CREDIT_CACHE`
line; variants lean-c-trace and cache-a-trace; preflight compiles all three trace variants.

usage: package_credit_trace_1102.py results/deepep_pipeline_20261101/source-1102-credit-trace-v1
"""
import copy, hashlib, json, shutil, sys
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'pipeline_v1')); sys.path.insert(0, str(HERE))
from package import replace  # noqa: E402
from prepare_credit_1102 import prepare  # noqa: E402
ROOT = HERE.parents[3]; NEW = ROOT / 'results/deepep_pipeline_20261101'
REMOTE = '/iopsstor/scratch/cscs/zyu/deepep-pipeline-20261030'
out = Path(sys.argv[1]).resolve(); assert not out.exists(), out
parent = NEW / 'source-1102-trace-dbg-v2'; credit = NEW / 'source-1102-credit-dbg-v1'
shutil.copytree(parent, out, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
prepare(out, variants=False, preflight=False)
for rel in ['backend/device/cxi_primitives.cuh', 'backend/host/cxi_resources.cc', 'backend/host/gin_plugin.cc', 'backend/include/cxi_gin_abi.h', 'runner/test_queue_credit.cc']:
    assert (out / rel).read_bytes() == (credit / rel).read_bytes(), rel  # same transport as the qualified credit slice
gen = out / 'runner/prepare_trace.py'
replace(gen, """        edit(p,'  while(true) {','  const auto trace_capacity=ep_trace::begin();\\n  while(true) {')""",
             """        edit(p,'#if CXI_CREDIT_CACHE\\n  // The NIC','  const auto trace_capacity=ep_trace::begin();\\n#if CXI_CREDIT_CACHE\\n  // The NIC')""")
compile(gen.read_text(), str(gen), 'exec')
# Dry-run the header instrumentation on a copy of the runtime headers to catch anchor mismatches locally.
import tempfile
with tempfile.TemporaryDirectory() as d:
    hd = Path(d) / 'include'; shutil.copytree(out / 'backend/device', hd); shutil.copyfile(out / 'backend/include/cxi_gin_abi.h', hd / 'cxi_gin_abi.h')
    scope = {'__file__': str(gen)}; exec(compile(gen.read_text(), str(gen), 'exec'), scope); scope['prepare_headers'](hd)
    t = (hd / 'cxi_primitives.cuh').read_text()
    assert t.count('trace_capacity=ep_trace::begin()') == 1 and t.count('ep_trace::finish(202') == 1 and 'trace_rp32=rp32' in t
variants = json.loads((out / 'variants.json').read_text())
variants['lean-c-trace'] = dict(variants['lean-b-trace'], CXI_CREDIT_CACHE=1)
variants['cache-a-trace'] = dict(variants['marker-zero-trace'], CXI_CREDIT_CACHE=1)
(out / 'variants.json').write_text(json.dumps(variants, indent=2) + '\n')
pf = out / 'runner/preflight.sh'
replace(pf, 'for variant in marker-zero-trace lean-b-trace; do', 'for variant in marker-zero-trace lean-b-trace lean-c-trace cache-a-trace; do')
replace(pf, '''  -I"$src/backend/include" -I"$src/backend/device" -c "$src/runner/burst_probe.cu" -o "$out/burst-lean.o"
''', '''  -I"$src/backend/include" -I"$src/backend/device" -c "$src/runner/burst_probe.cu" -o "$out/burst-lean.o"
"$sdk/bin/nvcc" -std=c++17 -arch=sm_90 -DCXI_CREDIT_CACHE=1 -DCXI_LEAN_FENCE=1 -DCXI_LEAN_CSTATE=1 -DCXI_LEAN_FOLD_MARKER=1 -DCXI_ZERO_DELIVERY_MARKER=1 -DCXI_HW_SIGNAL_FENCE=1 -DCXI_TX_BATCH_LIMIT=8 -DCXI_BATCH_DELIVERY=1 -DCXI_CT_THRESHOLD_FLUSH=1 \\
  -I"$src/backend/include" -I"$src/backend/device" -c "$src/runner/burst_probe.cu" -o "$out/burst-credit.o"
''')
T = {g['name']: g for g in json.loads((parent / 'sequence.json').read_text())}
snapshot = REMOTE + '/sources/' + out.name
seq = []
def trace(name, tmpl, variant, timeout, **env):
    g = copy.deepcopy(T[tmpl]); g['name'] = name; g['snapshot'] = snapshot; g['requires'] = []
    g['environment']['CXI_VARIANT'] = variant; g['environment'].update(env)
    g['timeout_seconds'] = timeout; g['environment']['CXI_TEST_TIMEOUT'] = str(timeout - 60)
    assert g['qualification'] == 'ep_trace' and g['environment']['CXI_DEVICE_TRACE'] == '1'
    seq.append(g)
trace('9980-trace-leanc-4k', '9902-trace-leanb-4k', 'lean-c-trace', 420)
trace('9981-trace-leanb-4k', '9902-trace-leanb-4k', 'lean-b-trace', 420)
trace('9982-trace-cachea-4k', '9901-trace-kern-4k', 'cache-a-trace', 420, CXI_EP_SKIP_COMBINE_FLUSH='0', CXI_EP_LOCAL_SELF_SIGNAL='0')
trace('9983-trace-leanc-4k-repeat', '9902-trace-leanb-4k', 'lean-c-trace', 300)
t = 10
for g, expected in zip(seq, [170, 170, 170, 95]):
    remaining = 1500 - t; assert g['timeout_seconds'] + 180 < remaining, g['name']; t += expected
print('expected end %.1f min' % (t / 60))
(out / 'sequence.json').write_text(json.dumps(seq, indent=2) + '\n')
m = json.loads((parent / 'manifest.json').read_text())
m.update(source_parent=str(parent), scope='2026-11-02 traced cached-credit transport: lean-c-trace, cache-a-trace, lean-b-trace at 4K on one pair; transport identical to source-1102-credit-dbg-v1')
m['files'] = {str(p.relative_to(out)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(out.rglob('*')) if p.is_file() and p.name != 'manifest.json'}
(out / 'manifest.json').write_text(json.dumps(m, indent=2) + '\n')
print(len(seq), 'gates'); print([g['name'] for g in seq]); print(out)
