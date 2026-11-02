#!/usr/bin/env python3
"""Private device-trace snapshot of the lean round (2026-11-02): the G trace generator applied to the
lean archive (source-1102-lean-v1), runtime variants marker-zero-trace and lean-b-trace, with the
primitives' flush anchor adapted to the lean text. Gates (kind ep_trace; when pushed into a controller
that predates the trace qualification, rewrite the kind to 'ep' and validate offline with
runner/validate_trace.py): cand, kern (kernel knobs on marker-zero) and leanb at 4K, 30 iterations,
3 captures. Mirrors pipeline_1101/package_trace_g_1101.py.

usage: package_trace_lean_1102.py results/deepep_pipeline_20261101/source-1102-lean-trace-v1
"""
import hashlib, json, shutil, sys, tarfile, tempfile
from pathlib import Path
HERE = Path(__file__).resolve().parent; P1101 = HERE.parent / 'pipeline_1101'; PV1 = HERE.parent / 'pipeline_v1'
sys.path.insert(0, str(PV1))
from package import replace  # noqa: E402
from prepare_packed_trace import patched_generator, EVENTS  # noqa: E402
ROOT = HERE.parents[3]; NEW = ROOT / 'results/deepep_pipeline_20261101'
REMOTE = '/iopsstor/scratch/cscs/zyu/deepep-pipeline-20261030'
out = Path(sys.argv[1]).resolve(); assert not out.exists(), out
parent = NEW / 'source-1102-lean-v1'; traceg = NEW / 'source-1101-trace-g-v1'
shutil.copytree(parent, out, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
# The G snapshot's generator already carries the packed events (113-116, 135) and the trace runner pieces.
for rel in ['runner/prepare_trace.py', 'runner/validate_trace.py', 'runner/controller.py', 'runner/trace_capture.py', 'backend/tests/trace_capture.py']:
    shutil.copyfile(traceg / rel, out / rel)
generator = out / 'runner/prepare_trace.py'; text = generator.read_text()
# Lean primitives: the early return of flush_locked clears the fence flag; keep the trace scope in front of it.
old = "    edit(p,'  if(c.completed==c.posted)return true;', '  ep_trace::Scope trace_flush(203,(uint64_t)&c,c.posted-c.completed);\\n  if(c.completed==c.posted)return true;')"
assert text.count(old) == 1, 'flush anchor not found in the G generator'
text = text.replace(old, "    edit(p,'  if(c.completed==c.posted){c.lean_state&=~lean_fence_due;return true;}', '  ep_trace::Scope trace_flush(203,(uint64_t)&c,c.posted-c.completed);\\n  if(c.completed==c.posted){c.lean_state&=~lean_fence_due;return true;}')")
compile(text, 'trace_generator_lean', 'exec'); generator.write_text(text)
scope = {'__file__': str(generator)}; exec(compile(text, str(generator), 'exec'), scope)
with tempfile.TemporaryDirectory() as d:
    ep = Path(d)
    with tarfile.open(parent / 'DeepEP.tar.gz') as a: a.extractall(ep)
    hc0 = (ep / 'deep_ep/include/deep_ep/impls/hybrid_combine.cuh').read_text()
    assert 'CXI_EP_SKIP_COMBINE_FLUSH' in hc0, 'parent lacks the lean kernel knobs'
    scope['prepare_ep'](ep)
    hd = (ep / 'deep_ep/include/deep_ep/impls/hybrid_dispatch.cuh').read_text()
    hc = (ep / 'deep_ep/include/deep_ep/impls/hybrid_combine.cuh').read_text()
    cm = (ep / 'deep_ep/include/deep_ep/common/comm.cuh').read_text()
    assert hd.count('ep_trace::finish(114') == 1 and hc.count('ep_trace::Scope trace_packed_combine(116') == 1 and hc.count('ep_trace::finish(135') == 2
    assert 'if constexpr (!CXI_EP_SKIP_COMBINE_FLUSH)' in hc and 'CXI_EP_LOCAL_SELF_SIGNAL' in cm, 'lean knobs survive the trace edits'
    with tarfile.open(out / 'DeepEP-trace.tar.gz', 'w:gz') as a: a.add(ep, arcname='.')
assert (parent / 'DeepEP.tar.gz').read_bytes() == (out / 'DeepEP.tar.gz').read_bytes()
node = out / 'runner/node.sh'; t = node.read_text()
start = t.index('if [ "${CXI_DEVICE_TRACE:-0}" != 0 ]; then'); end = t.index('\nfi', start) + 3
node.write_text(t[:start] + '''if [ "${CXI_DEVICE_TRACE:-0}" != 1 ]; then
  printf 'Private trace snapshot requires CXI_DEVICE_TRACE=1\\n' >&2
  exit 2
fi''' + t[end:])
variants = json.loads((parent / 'variants.json').read_text())
(out / 'variants.json').write_text(json.dumps({'marker-zero-trace': variants['marker-zero'], 'lean-b-trace': variants['lean-b']}, indent=2) + '\n')
replace(out / 'runner/preflight.sh', 'for variant in marker-zero lean-a lean-b; do', 'for variant in marker-zero-trace lean-b-trace; do')
for rel in ['runner/trace_capture.py', 'backend/tests/trace_capture.py']:
    replace(out / rel, 'TRACE=None', 'EVENTS.update(' + repr(EVENTS) + ')\nTRACE=None')
snapshot = REMOTE + '/sources/' + out.name
common = dict(CXI_DEVICE_TRACE='1', CXI_TRANSPORT='direct', CXI_TEST_KIND='ep',
    CXI_EP_SMS='64', CXI_EP_CONTEXTS='129', CXI_EP_UPDATE_INTERVAL='16', CXI_EP_FIRST_INTERVAL='4', CXI_EP_FORWARD_CHUNK='3', CXI_EP_PACK_ROWS='1',
    CXI_EP_COMBINE_BATCH='16', CXI_EP_COMBINE_FIRST_BATCH='4', CXI_EP_PACK_COMBINE='1', CXI_EP_MERGE_FINAL_TAIL='1', CXI_EP_DEBUG='0',
    CXI_QUEUE_INVENTORY='1', CXI_LOCAL_JIT='1', CXI_LOCAL_RESULTS='1', CXI_LOCAL_LOGS='1', CXI_DIAGNOSTIC_WATCHDOG='0',
    CXI_EP_MODELS='v4flash', CXI_EP_TOKENS='4096', CXI_EP_DTYPES='fp8', CXI_EP_ROUTING='mixed', CXI_EP_SEEDS='1',
    CXI_EP_WARMUP='20', CXI_EP_ITERS='30', CXI_EP_NIC_ITERS='0', CXI_EP_PROFILE_STEPS='0', CXI_TRACE_CAPTURES='3',
    CXI_TEST_TIMEOUT='1740')
seq = []
def add(name, **env):
    e = dict(common); e.update(env)
    seq.append(dict(name=name, snapshot=snapshot, node_script='runner/node.sh', qualification='ep_trace',
                    timeout_seconds=1800, environment=e, requires=[]))
add('9800-trace-cand-4k', CXI_VARIANT='marker-zero-trace', CXI_EP_SKIP_COMBINE_FLUSH='0', CXI_EP_LOCAL_SELF_SIGNAL='0')
add('9801-trace-kern-4k', CXI_VARIANT='marker-zero-trace', CXI_EP_SKIP_COMBINE_FLUSH='1', CXI_EP_LOCAL_SELF_SIGNAL='1')
add('9802-trace-leanb-4k', CXI_VARIANT='lean-b-trace', CXI_EP_SKIP_COMBINE_FLUSH='1', CXI_EP_LOCAL_SELF_SIGNAL='1')
(out / 'sequence.json').write_text(json.dumps(seq, indent=2) + '\n')
(out / 'trace-events.json').write_text(json.dumps(dict(events=EVENTS, scope='GPU-observed submission/observation scopes; overlapping; not NIC wire timestamps'), indent=2) + '\n')
m = json.loads((parent / 'manifest.json').read_text())
m.update(source_parent=str(parent), scope='2026-11-02: private device traces of cand / kern / leanb at 4K on the lean archive; ordinary archive unchanged')
m['files'] = {str(p.relative_to(out)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(out.rglob('*')) if p.is_file() and p.name != 'manifest.json'}
(out / 'manifest.json').write_text(json.dumps(m, indent=2) + '\n')
print('trace snapshot ready:', out); print([g['name'] for g in seq])
