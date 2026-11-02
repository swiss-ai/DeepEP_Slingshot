#!/usr/bin/env python3
"""Allocation C (2026-11-02): release/re-evaluation matrix of the packed-combine + final-tail candidate.

Parent: results/deepep_pipeline_20261101/source-1101-release-v1 (serving harness; GPU code = v7).
Applied: pipeline_v1/prepare_final_tail.prepare, pipeline_1101/prepare_packed_combine.prepare (same
patches as allocation B's qualified `both` arm), plus a harness-only change: when CXI_LOCAL_JIT=1 the
Triton kernel cache also moves to the node-local JIT directory (the shared-filesystem Triton cache
raced between ranks in A's Qwen3 SGLang gate). Every gate runs with CXI_EP_PACK_COMBINE=1,
CXI_EP_MERGE_FINAL_TAIL=1, CXI_EP_COMBINE_BATCH=16, packed rows, interval 16, 129 contexts."""
import copy, hashlib, json, shutil, sys
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'pipeline_v1')); sys.path.insert(0, str(HERE))
from package import replace  # noqa: E402
from prepare_final_tail import prepare as prepare_final_tail  # noqa: E402
from prepare_packed_combine import prepare as prepare_packed_combine  # noqa: E402
ROOT = HERE.parents[3]
NEW = ROOT / 'results/deepep_pipeline_20261101'; OLD = ROOT / 'results/deepep_pipeline_20261030'
REMOTE = '/iopsstor/scratch/cscs/zyu/deepep-pipeline-20261030'
out = Path(sys.argv[1]).resolve(); assert not out.exists(), out
parent = NEW / 'source-1101-release-v1'
shutil.copytree(parent, out, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
prepare_final_tail(out); prepare_packed_combine(out)
shutil.copyfile(HERE / 'test_packed_combine.cc', out / 'runner/test_packed_combine.cc')
pre = out / 'runner/preflight.sh'
replace(pre, 'date -Is > "$out/TRANSPORT_PREFLIGHT_PASS"', '''g++ -std=c++17 -O2 -Wall -Wextra -Werror -I"$src/runner" "$src/runner/test_packed_combine.cc" -o "$out/packed-combine-model"
"$out/packed-combine-model"
date -Is > "$out/TRANSPORT_PREFLIGHT_PASS"''')
# Harness: node-local Triton cache under local JIT (both EP and SGLang kinds; EP_JIT_CACHE_DIR is final here).
replace(out / 'backend/tools/direct_node.sh', 'runtime_log="$base/smoke.log"', '''if [ "${CXI_LOCAL_JIT:-0}" = 1 ]; then
  export TRITON_CACHE_DIR="$EP_JIT_CACHE_DIR/triton"
  printf '%s\\n' "$TRITON_CACHE_DIR" > "$base/triton-cache-path.txt"
fi
runtime_log="$base/smoke.log"''')
old_seq = json.loads((parent / 'sequence.json').read_text())
snapshot = REMOTE + '/sources/' + out.name
CAND = dict(CXI_EP_PACK_ROWS='1', CXI_EP_UPDATE_INTERVAL='16', CXI_EP_FORWARD_CHUNK='3',
            CXI_EP_PACK_COMBINE='1', CXI_EP_MERGE_FINAL_TAIL='1', CXI_EP_COMBINE_BATCH='16',
            CXI_LOCAL_JIT='1', CXI_LOCAL_RESULTS='1', CXI_LOCAL_LOGS='1', CXI_DIAGNOSTIC_WATCHDOG='0')
seq = []; names = {}
for g in old_seq:
    n = copy.deepcopy(g); num = int(g['name'].split('-')[0]); n['name'] = '%d-%s' % (num + 2000, g['name'].split('-', 1)[1])
    names[g['name']] = n['name']; n['snapshot'] = snapshot; n['environment'].update(CAND); seq.append(n)
for n in seq: n['requires'] = [names[r] for r in n['requires']]
known = set()
for g in seq:
    assert g['name'] not in known and all(r in known for r in g['requires']), g['name']; known.add(g['name'])
(out / 'sequence.json').write_text(json.dumps(seq, indent=2) + '\n')
m = json.loads((parent / 'manifest.json').read_text())
m.update(source_parent=str(parent), scope='2026-11-02 allocation C: release/re-evaluation of packed dispatch I16 + packed combine + final-tail merge on the marker-zero transport; node-local Triton cache; GPU unqualified until its own gates pass')
m['files'] = {str(p.relative_to(out)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(out.rglob('*')) if p.is_file() and p.name != 'manifest.json'}
(out / 'manifest.json').write_text(json.dumps(m, indent=2) + '\n')
# Archive delta audit against B's qualified snapshot: identical DeepEP archive.
b = NEW / 'source-1101-combine-pack-v2'
assert hashlib.sha256((b / 'DeepEP.tar.gz').read_bytes()).hexdigest() != '' 
import tarfile, tempfile
def digest_tree(archive):
    with tempfile.TemporaryDirectory() as tmp:
        with tarfile.open(archive) as a: a.extractall(tmp)
        return {str(p.relative_to(tmp)): hashlib.sha256(p.read_bytes()).hexdigest() for p in Path(tmp).rglob('*') if p.is_file()}
assert digest_tree(out / 'DeepEP.tar.gz') == digest_tree(b / 'DeepEP.tar.gz'), 'DeepEP archive differs from allocation B snapshot'
for path in (b / 'backend').rglob('*'):
    if path.is_file() and path.parent.name in ('device', 'host', 'include'):
        assert path.read_bytes() == (out / path.relative_to(b)).read_bytes(), path
print(len(seq), 'gates; total timeout h =', round(sum(g['timeout_seconds'] for g in seq) / 3600, 2)); print(out)
