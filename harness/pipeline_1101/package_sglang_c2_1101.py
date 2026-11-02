#!/usr/bin/env python3
"""Allocation D: SGLang release gates of the packed-combine + final-tail candidate with the Triton cache
on an executable node-local path. Parent: source-1101-release-c-v1 (identical GPU code/archive).
Only backend/tools/direct_node.sh (Triton cache placement), sequence.json and manifest.json change."""
import copy, hashlib, json, shutil, sys
from pathlib import Path
HERE = Path(__file__).resolve().parent; sys.path.insert(0, str(HERE.parent / 'pipeline_v1'))
from package import replace  # noqa: E402
ROOT = HERE.parents[3]; NEW = ROOT / 'results/deepep_pipeline_20261101'
REMOTE = '/iopsstor/scratch/cscs/zyu/deepep-pipeline-20261030'
out = Path(sys.argv[1]).resolve(); assert not out.exists(), out
parent = NEW / 'source-1101-release-c-v1'
shutil.copytree(parent, out, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
replace(out / 'backend/tools/direct_node.sh', '''if [ "${CXI_LOCAL_JIT:-0}" = 1 ]; then
  export TRITON_CACHE_DIR="$EP_JIT_CACHE_DIR/triton"
  printf '%s\\n' "$TRITON_CACHE_DIR" > "$base/triton-cache-path.txt"
fi''', '''if [ "${CXI_LOCAL_JIT:-0}" = 1 ]; then
  # Triton dlopens compiled .so files, so its cache must not live on a noexec mount (/dev/shm is
  # noexec inside the container). Use the container-local /tmp when it allows exec; otherwise keep
  # Triton's default cache location.
  tcache="/tmp/deepep-triton-${SLURM_JOB_ID}-n${SLURM_PROCID}"; mkdir -p "$tcache"
  tmount=$(stat -c %m "$tcache" 2>/dev/null || echo /)
  if awk -v m="$tmount" '$2==m {print $4}' /proc/mounts | grep -q noexec; then
    rm -rf "$tcache"; tcache=""
  fi
  if [ -n "$tcache" ]; then export TRITON_CACHE_DIR="$tcache"; fi
  printf '%s\\n' "${TRITON_CACHE_DIR:-default}" > "$base/triton-cache-path.txt"
fi''')
seq0 = json.loads((parent / 'sequence.json').read_text()); T = {g['name']: g for g in seq0}
snapshot = REMOTE + '/sources/' + out.name
def mk(name, template, requires):
    g = copy.deepcopy(template); g['name'] = name; g['snapshot'] = snapshot; g['requires'] = list(requires); return g
seq = []
seq.append(mk('8200-fresh-irregular-stress', T['8000-fresh-irregular-stress'], []))
seq.append(mk('8201-fresh-4k-correctness', T['8001-fresh-4k-correctness'], ['8200-fresh-irregular-stress']))
pairs = [('8210', '8028-marker-zero-v4flash-sglang-scatter-gather', '8211', '8029-marker-zero-v4flash-sglang-expert-smoke'),
         ('8212', '8030-marker-zero-qwen3-sglang-scatter-gather', '8213', '8031-marker-zero-qwen3-sglang-expert-smoke'),
         ('8214', '8032-marker-zero-minimax-sglang-scatter-gather', '8215', '8033-marker-zero-minimax-sglang-expert-smoke')]
for a, sg, b, ex in pairs:
    g1 = mk(a + '-' + sg.split('-', 1)[1], T[sg], ['8201-fresh-4k-correctness']); seq.append(g1)
    seq.append(mk(b + '-' + ex.split('-', 1)[1], T[ex], [g1['name']]))
known = set()
for g in seq:
    assert g['name'] not in known and all(r in known for r in g['requires']); known.add(g['name'])
(out / 'sequence.json').write_text(json.dumps(seq, indent=2) + '\n')
m = json.loads((parent / 'manifest.json').read_text())
m.update(source_parent=str(parent), scope='2026-11-02 allocation D: SGLang release gates of the packed-combine + final-tail candidate with an exec-capable node-local Triton cache; GPU code identical to source-1101-release-c-v1')
m['files'] = {str(p.relative_to(out)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(out.rglob('*')) if p.is_file() and p.name != 'manifest.json'}
(out / 'manifest.json').write_text(json.dumps(m, indent=2) + '\n')
assert hashlib.sha256((out / 'DeepEP.tar.gz').read_bytes()).hexdigest() == hashlib.sha256((parent / 'DeepEP.tar.gz').read_bytes()).hexdigest()
print(len(seq), 'gates'); print([g['name'] for g in seq]); print(out)
