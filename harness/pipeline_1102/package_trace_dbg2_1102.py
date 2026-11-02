#!/usr/bin/env python3
"""Second debug slice (2026-11-02 evening), after job 3837687 paused on gate 9901: the trace validator
required the combine flush scopes (events 203/207) that CXI_EP_SKIP_COMBINE_FLUSH removes; it would
likewise have required the CSTATE submission (212) that CXI_LEAN_CSTATE caches and the NIC fence (211)
that CXI_LEAN_FENCE elides. Code identical to source-1102-trace-dbg-v1 except runner/validate_trace.py,
which now follows the kernel knob and the lean variant definitions and reports the observed counts of
those events instead. Gates: the nine that did not run (9901-9909) plus 9910-cand-repeat3; timeouts as
before, budget re-checked against the 25-minute allocation.

usage: package_trace_dbg2_1102.py results/deepep_pipeline_20261101/source-1102-trace-dbg-v2
"""
import copy, hashlib, json, shutil, sys
from pathlib import Path
HERE = Path(__file__).resolve().parent; PV1 = HERE.parent / 'pipeline_v1'
sys.path.insert(0, str(PV1))
from package import replace  # noqa: E402
ROOT = HERE.parents[3]; NEW = ROOT / 'results/deepep_pipeline_20261101'
REMOTE = '/iopsstor/scratch/cscs/zyu/deepep-pipeline-20261030'
out = Path(sys.argv[1]).resolve(); assert not out.exists(), out
parent = NEW / 'source-1102-trace-dbg-v1'
shutil.copytree(parent, out, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
for path in parent.rglob('*'):
    if path.is_file() and path.name not in ('sequence.json', 'manifest.json') and '__pycache__' not in path.parts:
        assert path.read_bytes() == (out / path.relative_to(parent)).read_bytes(), path
v = out / 'runner/validate_trace.py'
replace(v, "    native = bool(definitions.get('CXI_HW_SIGNAL_FENCE', 0))\n    batch = bool(definitions.get('CXI_BATCH_DELIVERY', 0))\n",
           "    native = bool(definitions.get('CXI_HW_SIGNAL_FENCE', 0))\n    batch = bool(definitions.get('CXI_BATCH_DELIVERY', 0))\n"
           "    lean_fence = bool(definitions.get('CXI_LEAN_FENCE', 0)); lean_cstate = bool(definitions.get('CXI_LEAN_CSTATE', 0))\n"
           "    skip_combine_flush = bool(int(env.get('CXI_EP_SKIP_COMBINE_FLUSH', '0')))\n"
           "    counts = {'combine_flush_scopes': 0, 'cstate_submissions': 0, 'fence_submissions': 0}\n")
replace(v, "        required = {200, 201, 202, 204, 205, 206, 209, 212, 213, 214}\n",
           "        required = {200, 201, 202, 204, 205, 206, 209, 213, 214}\n"
           "        # CXI_LEAN_CSTATE re-emits CSTATE only when the (index_ext, write_lac) key changes.\n"
           "        if not lean_cstate:\n"
           "            required.add(212)\n"
           "        counts['cstate_submissions'] += sum(e['event'] == 212 for e in events)\n"
           "        counts['fence_submissions'] += sum(e['event'] == 211 for e in events)\n"
           "        if row['operation'] == 'combine':\n"
           "            counts['combine_flush_scopes'] += sum(e['event'] == 203 for e in events)\n")
replace(v, "        if not native or row['operation'] == 'combine':\n            required |= {203, 207}\n        if native:\n            required.add(211)\n",
           "        # CXI_EP_SKIP_COMBINE_FLUSH removes the combine's only GPU flush before its end signal.\n"
           "        if not native or (row['operation'] == 'combine' and not skip_combine_flush):\n"
           "            required |= {203, 207}\n"
           "        # CXI_LEAN_FENCE elides the CQ fence when nothing was posted since the last fence.\n"
           "        if native and not lean_fence:\n"
           "            required.add(211)\n")
replace(v, "    result.update(device_traces='PASS', trace_validation='configuration-aware', native_fence=native,\n                  batched_delivery=batch, ",
           "    result.update(device_traces='PASS', trace_validation='configuration-aware', native_fence=native,\n"
           "                  batched_delivery=batch, lean_fence=lean_fence, lean_cstate=lean_cstate,\n"
           "                  skip_combine_flush=skip_combine_flush, **counts, ")
compile(v.read_text(), str(v), 'exec')
snapshot = REMOTE + '/sources/' + out.name
seq = [g for g in json.loads((parent / 'sequence.json').read_text()) if g['name'] != '9900-trace-cand-4k']
assert len(seq) == 9 and seq[0]['name'] == '9901-trace-kern-4k'
for g in seq:
    if g['qualification'] == 'ep_trace':
        assert g['snapshot'].endswith('/' + parent.name); g['snapshot'] = snapshot
    else:
        assert g['snapshot'].endswith('/source-1102-dbuf-v1')
cand3 = copy.deepcopy(next(g for g in seq if g['name'] == '9907-cand-repeat2')); cand3['name'] = '9910-cand-repeat3'; seq.append(cand3)
FIRST_TRACE, FIRST_EP, EP_4K16K, EP_4K, SETUP, ALLOC = 170, 165, 95, 70, 10, 25 * 60
expected = {'9901-trace-kern-4k': FIRST_TRACE, '9902-trace-leanb-4k': FIRST_TRACE, '9903-cand-repeat1': FIRST_EP, '9904-kern-repeat1': EP_4K16K,
            '9905-leanb-repeat1': FIRST_EP, '9906-leanb-repeat2': EP_4K16K, '9907-cand-repeat2': EP_4K, '9908-kern-repeat2': EP_4K,
            '9909-leanb-repeat3': EP_4K, '9910-cand-repeat3': EP_4K}
t = SETUP; known = set()
for g in seq:
    assert g['name'] not in known and g['requires'] == []; known.add(g['name'])
    remaining = ALLOC - t; fits = g['timeout_seconds'] + 180 < remaining
    print('%-22s start %5.1f min  remaining %4d s  timeout %3d  %s' % (g['name'], t / 60, remaining, g['timeout_seconds'], 'ok' if fits else 'DOES NOT FIT'))
    assert fits, g['name']; t += expected[g['name']]
print('expected end of the last gate: %.1f min of %d' % (t / 60, ALLOC // 60))
(out / 'sequence.json').write_text(json.dumps(seq, indent=2) + '\n')
m = json.loads((parent / 'manifest.json').read_text())
m.update(source_parent=str(parent), allowed_differences=['runner/validate_trace.py'],
         scope='2026-11-02 debug slice 2: trace validator follows CXI_EP_SKIP_COMBINE_FLUSH / CXI_LEAN_CSTATE / CXI_LEAN_FENCE; gates 9901-9910; compiled sources identical to source-1102-trace-dbg-v1')
m['files'] = {str(p.relative_to(out)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(out.rglob('*')) if p.is_file() and p.name != 'manifest.json'}
(out / 'manifest.json').write_text(json.dumps(m, indent=2) + '\n')
print(len(seq), 'gates'); print([g['name'] for g in seq]); print(out)
