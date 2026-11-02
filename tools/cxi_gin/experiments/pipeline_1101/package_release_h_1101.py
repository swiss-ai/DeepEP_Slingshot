#!/usr/bin/env python3
"""Allocation H (2026-11-02): release/re-evaluation matrix of the final candidate
(marker-zero transport, packed rows with first interval 4 / regular 16 / forward chunk 3, packed
combine with first batch 4 / batch 16, final-tail merge, 129 contexts).

Parent: results/deepep_pipeline_20261101/source-1101-sglang-c2-v1 (serving harness with the
exec-capable node-local Triton cache; GPU archive identical to allocation B/C). Applied:
pipeline_1101/prepare_first_batch.prepare, so the DeepEP archive must equal the one qualified in
allocation F (source-1101-first-batch-v1); this is asserted file by file. The sequence is allocation
C's release matrix (8000-8033) renumbered to 8800-8833 with the two first-batch knobs added to every
gate. The gates are meant to be pushed into a running allocation (push_sequence.py); the snapshot can
also be launched on its own.

usage: package_release_h_1101.py results/deepep_pipeline_20261101/source-1101-release-h-v1
"""
import copy, hashlib, json, shutil, sys, tarfile, tempfile
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'pipeline_v1')); sys.path.insert(0, str(HERE))
from prepare_first_batch import prepare as prepare_first_batch  # noqa: E402
ROOT = HERE.parents[3]; NEW = ROOT / 'results/deepep_pipeline_20261101'
REMOTE = '/iopsstor/scratch/cscs/zyu/deepep-pipeline-20261030'
out = Path(sys.argv[1]).resolve(); assert not out.exists(), out
parent = NEW / 'source-1101-sglang-c2-v1'; qualified = NEW / 'source-1101-first-batch-v1'
shutil.copytree(parent, out, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
prepare_first_batch(out)

def digest_tree(archive):
    with tempfile.TemporaryDirectory() as tmp:
        with tarfile.open(archive) as a: a.extractall(tmp)
        return {str(p.relative_to(tmp)): hashlib.sha256(p.read_bytes()).hexdigest() for p in Path(tmp).rglob('*') if p.is_file()}
assert digest_tree(out / 'DeepEP.tar.gz') == digest_tree(qualified / 'DeepEP.tar.gz'), 'DeepEP archive differs from the F-qualified snapshot'
for path in (qualified / 'backend').rglob('*'):
    if path.is_file() and (path.parent.name in ('device', 'host', 'include') or path.name in ('nvcc_wrapper.py', 'ep_benchmark.py')):
        assert path.read_bytes() == (out / path.relative_to(qualified)).read_bytes(), path

release_c = NEW / 'source-1101-release-c-v1'
old_seq = json.loads((release_c / 'sequence.json').read_text())
snapshot = REMOTE + '/sources/' + out.name
CAND = dict(CXI_EP_PACK_ROWS='1', CXI_EP_UPDATE_INTERVAL='16', CXI_EP_FIRST_INTERVAL='4', CXI_EP_FORWARD_CHUNK='3',
            CXI_EP_PACK_COMBINE='1', CXI_EP_MERGE_FINAL_TAIL='1', CXI_EP_COMBINE_BATCH='16', CXI_EP_COMBINE_FIRST_BATCH='4',
            CXI_LOCAL_JIT='1', CXI_LOCAL_RESULTS='1', CXI_LOCAL_LOGS='1', CXI_DIAGNOSTIC_WATCHDOG='0')
seq = []; names = {}
for g in old_seq:
    n = copy.deepcopy(g); num = int(g['name'].split('-')[0]); n['name'] = '%d-%s' % (num + 800, g['name'].split('-', 1)[1])
    names[g['name']] = n['name']; n['snapshot'] = snapshot; n['environment'].update(CAND); seq.append(n)
for n in seq: n['requires'] = [names[r] for r in n['requires']]
known = set()
for g in seq:
    assert g['name'] not in known and all(r in known for r in g['requires']), g['name']; known.add(g['name'])
assert [g['name'] for g in seq] == sorted(g['name'] for g in seq)
(out / 'sequence.json').write_text(json.dumps(seq, indent=2) + '\n')
m = json.loads((parent / 'manifest.json').read_text())
m.update(source_parent=str(parent), scope='2026-11-02 allocation H: release/re-evaluation of the final candidate (first interval 4, combine first batch 4) on the serving harness; GPU archive identical to the F-qualified snapshot')
m['files'] = {str(p.relative_to(out)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(out.rglob('*')) if p.is_file() and p.name != 'manifest.json'}
(out / 'manifest.json').write_text(json.dumps(m, indent=2) + '\n')
print(len(seq), 'gates; sum of timeouts h =', round(sum(g['timeout_seconds'] for g in seq) / 3600, 2)); print(out)
