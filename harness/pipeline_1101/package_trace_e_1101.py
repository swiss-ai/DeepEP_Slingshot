#!/usr/bin/env python3
"""Allocation E: private device traces of the packed-combine + final-tail candidate (and its control arm).

Parent: results/deepep_pipeline_20261101/source-1101-combine-pack-v2 (ordinary archive unchanged).
Trace archive = pipeline_v1 packed-trace generator (events 113/114/115, 209-214) applied to the parent
archive, plus two combine additions: event 116 around each packed batch PUT and a balanced finish of
the per-token reduce scope (135) on the packed path. The standalone controller's trace qualification is
replaced by the configuration-aware validate_trace (native fence => no GPU flush events on dispatch)."""
import hashlib, json, shutil, sys, tarfile, tempfile
from pathlib import Path
HERE = Path(__file__).resolve().parent; sys.path.insert(0, str(HERE.parent / 'pipeline_v1'))
from package import replace  # noqa: E402
from prepare_packed_trace import patched_generator, EVENTS  # noqa: E402
ROOT = HERE.parents[3]; NEW = ROOT / 'results/deepep_pipeline_20261101'
REMOTE = '/iopsstor/scratch/cscs/zyu/deepep-pipeline-20261030'
out = Path(sys.argv[1]).resolve(); assert not out.exists(), out
parent = NEW / 'source-1101-combine-pack-v2'
shutil.copytree(parent, out, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
EVENTS = dict(EVENTS); EVENTS[116] = 'packed_combine_batch_submission'
generator = out / 'runner/prepare_trace.py'
text = patched_generator(generator.read_text())
# Combine additions: trace the packed batch PUT and close the per-token reduce scope on the packed path.
anchor = "    p=base/'combine_reduce_epilogue.cuh'\n"
assert text.count(anchor) == 1
text = text.replace(anchor, r'''    pc=base/'hybrid_combine.cuh'
    edit(pc,'                if (packed_first_j >= 0 and ptx::elect_one_sync()) {\n                    ptx::tma_store_wait();\n                    gin.put<ncclTeamTagRail>(',
         '                if (packed_first_j >= 0 and ptx::elect_one_sync()) {\n                    ptx::tma_store_wait();\n'
         '                    ep_trace::Scope trace_packed_combine(116,\n'
         '                        (uint64_t(channel_idx) << 32) | uint32_t(packed_peer),\n'
         '                        (uint64_t(packed_first_j) << 32) | uint32_t(packed_last_j));\n'
         '                    gin.put<ncclTeamTagRail>(')
    edit(pc,'                    // Record only for the (now unused) single-row path bookkeeping.\n                    last_src_scaleout_rank_idx = -1;\n                    continue;',
         '                    ep_trace::finish(135,trace_reduce,channel_idx,src_token_global_idx);\n'
         '                    last_src_scaleout_rank_idx = -1;\n                    continue;')
''' + anchor)
compile(text, 'trace_generator_e', 'exec'); generator.write_text(text)
scope = {'__file__': str(generator)}; exec(compile(text, str(generator), 'exec'), scope)
with tempfile.TemporaryDirectory() as d:
    ep = Path(d)
    with tarfile.open(parent / 'DeepEP.tar.gz') as a: a.extractall(ep)
    scope['prepare_ep'](ep)
    hc = (ep / 'deep_ep/include/deep_ep/impls/hybrid_combine.cuh').read_text()
    assert hc.count('ep_trace::Scope trace_packed_combine(116') == 1 and hc.count('ep_trace::finish(135') == 2, 'combine trace hooks'
    with tarfile.open(out / 'DeepEP-trace.tar.gz', 'w:gz') as a: a.add(ep, arcname='.')
assert (parent / 'DeepEP.tar.gz').read_bytes() == (out / 'DeepEP.tar.gz').read_bytes()
# node.sh: this snapshot exists only for tracing.
node = out / 'runner/node.sh'; t = node.read_text()
start = t.index('if [ "${CXI_DEVICE_TRACE:-0}" != 0 ]; then'); end = t.index('\nfi', start) + 3
node.write_text(t[:start] + '''if [ "${CXI_DEVICE_TRACE:-0}" != 1 ]; then
  printf 'Private trace snapshot requires CXI_DEVICE_TRACE=1\\n' >&2
  exit 2
fi''' + t[end:])
defs = json.loads((parent / 'variants.json').read_text())['marker-zero']
replace(out / 'runner/preflight.sh', 'for variant in marker-zero; do', 'for variant in marker-zero-trace; do')
(out / 'variants.json').write_text(json.dumps({'marker-zero-trace': defs}, indent=2) + '\n')
for rel in ['runner/trace_capture.py', 'backend/tests/trace_capture.py']:
    replace(out / rel, 'TRACE=None', 'EVENTS.update(' + repr(EVENTS) + ')\nTRACE=None')
shutil.copyfile(HERE.parent / 'pipeline_v1/validate_trace.py', out / 'runner/validate_trace.py')
replace(out / 'runner/validate_trace.py', "        required = {200, 201, 202, 204, 205, 206, 209}",
        """        required = {200, 201, 202, 204, 205, 206, 209, 212, 213, 214}
        if row['operation'] == 'dispatch_fresh':
            required |= {114, 115}
            if int(env.get('CXI_EP_PACK_ROWS', '0')):
                required.add(113)
        if row['operation'] == 'combine' and int(env.get('CXI_EP_PACK_COMBINE', '0')):
            required.add(116)""")
# Controller: configuration-aware trace qualification instead of the fixed event sets.
ctrl = out / 'runner/controller.py'; c = ctrl.read_text()
s = c.index("            if spec['qualification']=='ep_trace':"); e = c.index("            else:", s)
c = c[:s] + """            if spec['qualification']=='ep_trace':
                import sys as _sys; _sys.path.insert(0,str(source/'runner'))
                from validate_trace import qualify_trace
                record['qualification']=qualify_trace(out,spec,qualify)
""" + c[e:]
ctrl.write_text(c)
# Sequence: three ep_trace gates.
snapshot = REMOTE + '/sources/' + out.name
common = dict(CXI_VARIANT='marker-zero-trace', CXI_DEVICE_TRACE='1', CXI_TRANSPORT='direct', CXI_TEST_KIND='ep',
    CXI_EP_SMS='64', CXI_EP_CONTEXTS='129', CXI_EP_UPDATE_INTERVAL='16', CXI_EP_FORWARD_CHUNK='3', CXI_EP_PACK_ROWS='1',
    CXI_EP_COMBINE_BATCH='16', CXI_EP_DEBUG='0', CXI_QUEUE_INVENTORY='1', CXI_LOCAL_JIT='1', CXI_LOCAL_RESULTS='1',
    CXI_LOCAL_LOGS='1', CXI_DIAGNOSTIC_WATCHDOG='0', CXI_EP_MODELS='v4flash', CXI_EP_TOKENS='4096', CXI_EP_DTYPES='fp8',
    CXI_EP_ROUTING='mixed', CXI_EP_SEEDS='1', CXI_EP_WARMUP='20', CXI_EP_ITERS='30', CXI_EP_NIC_ITERS='0',
    CXI_EP_PROFILE_STEPS='0', CXI_TRACE_CAPTURES='3', CXI_TEST_TIMEOUT='1740')
seq = []
def add(name, **env):
    e = dict(common); e.update(env)
    seq.append(dict(name=name, snapshot=snapshot, node_script='runner/node.sh', qualification='ep_trace',
                    timeout_seconds=1800, environment=e, requires=[]))
add('8400-trace-candidate-4k', CXI_EP_PACK_COMBINE='1', CXI_EP_MERGE_FINAL_TAIL='1')
add('8401-trace-control-4k', CXI_EP_PACK_COMBINE='0', CXI_EP_MERGE_FINAL_TAIL='0')
add('8402-trace-candidate-16k', CXI_EP_PACK_COMBINE='1', CXI_EP_MERGE_FINAL_TAIL='1', CXI_EP_TOKENS='16384')
(out / 'sequence.json').write_text(json.dumps(seq, indent=2) + '\n')
(out / 'trace-events.json').write_text(json.dumps(dict(events=EVENTS, scope='GPU-observed submission/observation scopes; overlapping; not NIC wire timestamps'), indent=2) + '\n')
m = json.loads((parent / 'manifest.json').read_text())
m.update(source_parent=str(parent), scope='2026-11-02 allocation E: private device traces of packed combine + final-tail candidate and control; ordinary archive unchanged')
m['files'] = {str(p.relative_to(out)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(out.rglob('*')) if p.is_file() and p.name != 'manifest.json'}
(out / 'manifest.json').write_text(json.dumps(m, indent=2) + '\n')
print('trace snapshot ready:', out); print([g['name'] for g in seq])
