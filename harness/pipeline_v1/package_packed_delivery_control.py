"""Prepare a matched delivery-policy comparison after zero-marker packing passes."""
import argparse
import copy
import hashlib
import json
import shutil
import tarfile
from pathlib import Path
from package import ROOT, REMOTE

p = argparse.ArgumentParser(); p.add_argument('output', type=Path)
a = p.parse_args(); out = a.output.resolve()
base = ROOT/'results/deepep_pipeline_20261030/source-zero-packed-v7'
assert not out.exists()
shutil.copytree(base, out, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
definitions = json.loads((base/'variants.json').read_text())['marker-zero']
variants = {'marker-zero': definitions,
            'marker-control': dict(definitions, CXI_BATCH_DELIVERY=0, CXI_ZERO_DELIVERY_MARKER=0)}
(out/'variants.json').write_text(json.dumps(variants, indent=2)+'\n')
parent_sequence = json.loads((base/'sequence.json').read_text())
prerequisites = [g['name'] for g in parent_sequence]
requests = []
def add(label, template, variant, requires, updates=None):
    gate = copy.deepcopy(template)
    gate.update(name=str(3700+len(requests))+'-'+label,
                snapshot=REMOTE+'/sources/'+out.name, requires=requires)
    gate['environment'].update(CXI_VARIANT=variant, CXI_EP_PACK_ROWS='1', CXI_EP_FORWARD_CHUNK='3')
    gate['environment'].update(updates or {})
    requests.append(gate)
    return gate['name']
gates = []
for index in [3, 4, 5]:
    label = parent_sequence[index]['name'].split('zero-packed-', 1)[1]
    gates.append(add('packed-delivery-control-'+label, parent_sequence[index],
                     'marker-control', prerequisites if not gates else [gates[-1]]))
gates.append(add('packed-delivery-control-sustained16k', parent_sequence[7], 'marker-control',
                 [gates[-1]], dict(CXI_EP_TOKENS='16384', CXI_EP_SEEDS='1 2 3', CXI_EP_NIC_ITERS='0')))
for repeat, order in enumerate([['marker-zero','marker-control'], ['marker-control','marker-zero'], ['marker-zero','marker-control']], 1):
    for variant in order:
        add('packed-delivery-'+variant+'-repeat'+str(repeat), parent_sequence[7], variant, gates)
known = set(prerequisites)
for gate in requests:
    assert set(gate['requires']) <= known and gate['name'] not in known
    known.add(gate['name'])
(out/'sequence.json').write_text(json.dumps(requests, indent=2)+'\n')
manifest = json.loads((base/'manifest.json').read_text())
after = {str(f.relative_to(out)):hashlib.sha256(f.read_bytes()).hexdigest()
         for f in out.rglob('*') if f.is_file() and f.name != 'manifest.json'}
assert set(after) == set(manifest['files'])
assert {x for x in after if after[x] != manifest['files'][x]} == {'variants.json', 'sequence.json'}
manifest.update(files=after, source_parent=str(base),
    scope='Same packed source/ABI/host/library; compare payload delivery ACK against send completion plus zero-byte marker; GPU unqualified')
(out/'manifest.json').write_text(json.dumps(manifest, indent=2)+'\n')
with tarfile.open(out.parent/(out.name+'-overlay.tar.gz'), 'w:gz') as archive:
    for name in ['variants.json','sequence.json','manifest.json']:
        archive.add(out/name, arcname=name)
print('Prepared matched packed delivery comparison; no source changes or GPU submission', out)
