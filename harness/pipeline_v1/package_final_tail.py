"""Prepare an isolated dispatch finish-notification coalescing experiment."""
import argparse
import copy
import hashlib
import json
import shutil
import tarfile
from pathlib import Path
from package import ROOT, REMOTE
from prepare_final_tail import prepare

p = argparse.ArgumentParser(); p.add_argument('output', type=Path); a = p.parse_args()
base = ROOT/'results/deepep_pipeline_20261030/source-zero-packed-v7'
out = a.output.resolve(); assert not out.exists()
shutil.copytree(base, out, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
prepare(out)
templates = json.loads((base/'sequence.json').read_text())
requires = [x['name'] for x in json.loads((base.parent/'prepared-packed-i16-v1-sequence.json').read_text())]
rows = []; gates = []
def add(label, template, merge, updates=None):
    gate = copy.deepcopy(template)
    gate.update(name=str(4200+len(rows))+'-'+label, snapshot=REMOTE+'/sources/'+out.name,
                requires=requires+gates)
    gate['environment'].update(CXI_EP_MERGE_FINAL_TAIL=str(merge), CXI_EP_PACK_ROWS='1',
        CXI_EP_UPDATE_INTERVAL='16', CXI_EP_FORWARD_CHUNK='3')
    gate['environment'].update(updates or {})
    rows.append(gate); return gate['name']
for merge in [0, 1]:
    for i, label in [(3, 'irregular-stress'), (4, '4k-correctness'), (5, 'dropped-correctness')]:
        gates.append(add('final-tail%d-' % merge+label, templates[i], merge))
    gates.append(add('final-tail%d-sustained16k' % merge, templates[7], merge,
        dict(CXI_EP_TOKENS='16384', CXI_EP_DTYPES='fp8 bf16', CXI_EP_SEEDS='1 2 3', CXI_EP_NIC_ITERS='0')))
for repeat, order in enumerate([[0, 1], [1, 0], [0, 1]], 1):
    for merge in order:
        add('final-tail%d-repeat%d' % (merge, repeat), templates[7], merge)
(out/'sequence.json').write_text(json.dumps(rows, indent=2)+'\n')
manifest = json.loads((base/'manifest.json').read_text())
after = {str(f.relative_to(out)):hashlib.sha256(f.read_bytes()).hexdigest()
         for f in out.rglob('*') if f.is_file() and f.name != 'manifest.json'}
changed = {k for k in after if after[k] != manifest['files'][k]}
assert changed == {'DeepEP.tar.gz', 'backend/tests/nvcc_wrapper.py', 'backend/tests/ep_benchmark.py',
                   'runner/validate_gate.py', 'sequence.json'}
manifest.update(files=after, source_parent=str(base),
    scope='Final full dispatch batch shares mandatory finish notification; default flag0; combine and transport unchanged; GPU unqualified')
(out/'manifest.json').write_text(json.dumps(manifest, indent=2)+'\n')
with tarfile.open(out.parent/(out.name+'-overlay.tar.gz'), 'w:gz') as archive:
    for name in sorted(changed | {'manifest.json'}):
        archive.add(out/name, arcname=name)
print(out)
