"""Pack EP8 dispatch rows using the zero-byte delivery-marker transport unchanged."""
import argparse,hashlib,json,shutil
from pathlib import Path
from package import ROOT,HERE,REMOTE,replace
from prepare_packed_rows import prepare

p=argparse.ArgumentParser();p.add_argument('output',type=Path)
p.add_argument('--parent',default='source-marker-probe-v3')
p.add_argument('--qualification-sequence',default='newnode-marker-v3-zero-qualification-sequence.json')
p.add_argument('--gate-base',type=int,default=1300)
args=p.parse_args();out=args.output.resolve()
assert Path(args.parent).name==args.parent
base=ROOT/'results/deepep_pipeline_20261030'/args.parent
shutil.copytree(base,out,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
prepare(out)
variants=json.loads((base/'variants.json').read_text());assert variants['marker-zero']['CXI_ZERO_DELIVERY_MARKER']==1
(out/'variants.json').write_text(json.dumps({'marker-zero':variants['marker-zero']},indent=2)+'\n')
shutil.copyfile(HERE/'test_packed_rows.cc',out/'runner/test_packed_rows.cc')
preflight=out/'runner/preflight.sh'
replace(preflight,'for variant in marker-control marker-replay marker-zero; do','for variant in marker-zero; do')
replace(preflight,'date -Is > "$out/PASS"','''g++ -std=c++17 -O2 -Wall -Wextra -Werror -I"$src/runner" "$src/runner/test_packed_rows.cc" -o "$out/packed-model"
"$out/packed-model"
date -Is > "$out/TRANSPORT_PREFLIGHT_PASS"
# Actual EP8 templates require preflight_packed_rows.py with the transport parent.
''')
parents=json.loads((ROOT/'results/deepep_pipeline_20261030'/args.qualification_sequence).read_text())
prereq=[]
for suffix in ['tiny-stress','ep-correctness','sustained16k','repeat1','repeat2','repeat3']:
 matches=[x['name'] for x in parents if x['name'].endswith('-'+suffix)]
 assert len(matches)==1,(suffix,matches)
 prereq+=matches
assert len(prereq)==6
common=dict(CXI_VARIANT='marker-zero',CXI_TRANSPORT='direct',CXI_EP_SMS='64',CXI_EP_CONTEXTS='129',CXI_EP_UPDATE_INTERVAL='3',CXI_EP_DEBUG='0',CXI_DEVICE_TRACE='0',CXI_QUEUE_INVENTORY='1',CXI_EP_DROP_EVERY='0',CXI_TEST_KIND='ep')
settings=dict(CXI_EP_MODELS='v4flash',CXI_EP_TOKENS='4096 16384',CXI_EP_DTYPES='fp8',CXI_EP_ROUTING='mixed',CXI_EP_SEEDS='1',CXI_EP_WARMUP='20',CXI_EP_ITERS='100',CXI_EP_NIC_ITERS='600',CXI_EP_PROFILE_STEPS='0')
seq=[]
def add(label,packed,updates,requires,seconds=900):
 name='%d-%s'%(args.gate_base+len(seq),label);env=dict(common,CXI_EP_PACK_ROWS=str(packed),CXI_TEST_TIMEOUT=str(seconds-60));env.update(settings);env.update(updates)
 seq.append(dict(name=name,snapshot=REMOTE+'/sources/'+out.name,node_script='runner/node.sh',qualification='ep',timeout_seconds=seconds,environment=env,requires=requires));return name
ends={}
for packed,label in [(0,'zero-rows'),(1,'zero-packed')]:
 gate=add(label+'-irregular-stress',packed,dict(CXI_EP_TOKENS='32 257',CXI_EP_ROUTING='mixed uniform hot_rank local remote',CXI_EP_SEEDS='1 2 3',CXI_EP_NIC_ITERS='0'),prereq)
 gate=add(label+'-4k-correctness',packed,dict(CXI_EP_TOKENS='4096',CXI_EP_DTYPES='fp8 bf16',CXI_EP_ROUTING='mixed uniform hot_rank local remote',CXI_EP_SEEDS='1 2',CXI_EP_WARMUP='2',CXI_EP_ITERS='3',CXI_EP_NIC_ITERS='0'),[gate])
 gate=add(label+'-dropped-correctness',packed,dict(CXI_EP_TOKENS='257',CXI_EP_DTYPES='fp8 bf16',CXI_EP_ROUTING='mixed local remote',CXI_EP_SEEDS='1 2',CXI_EP_DROP_EVERY='5',CXI_EP_WARMUP='2',CXI_EP_ITERS='3',CXI_EP_NIC_ITERS='0'),[gate]);ends[packed]=gate
for rep,order in enumerate([[0,1],[1,0],[0,1]],1):
 for packed in order:add(('zero-packed' if packed else 'zero-rows')+'-repeat'+str(rep),packed,{},[ends[0],ends[1]],seconds=600)
known={x['name'] for x in parents}
for x in seq:
 assert x['qualification']=='ep' and x['environment']['CXI_TEST_KIND']=='ep'
 assert set(x['requires'])<=known and x['name'] not in known
 known.add(x['name'])
(out/'sequence.json').write_text(json.dumps(seq,indent=2)+'\n')
for path in (base/'backend').rglob('*'):
 if path.is_file() and path.parent.name in ('device','host','include'):
  assert path.read_bytes()==(out/path.relative_to(base)).read_bytes(),path
# Combine and all other ordinary DeepEP files remain unchanged; only dispatch
# staging and its new capacity helper differ in the archive.
import tarfile,tempfile
with tempfile.TemporaryDirectory() as tmp:
 roots=[]
 for i,source in enumerate([base,out]):
  d=Path(tmp)/str(i);d.mkdir();roots.append(d)
  with tarfile.open(source/'DeepEP.tar.gz') as t:t.extractall(d)
 before={str(p.relative_to(roots[0])):hashlib.sha256(p.read_bytes()).hexdigest() for p in roots[0].rglob('*') if p.is_file()}
 after={str(p.relative_to(roots[1])):hashlib.sha256(p.read_bytes()).hexdigest() for p in roots[1].rglob('*') if p.is_file()}
 assert set(after)-set(before)=={'deep_ep/include/deep_ep/common/cxi_packed_channel.cuh'}
 assert {k for k in before if before[k]!=after[k]}=={'deep_ep/include/deep_ep/impls/hybrid_dispatch.cuh'}
m=json.loads((base/'manifest.json').read_text());m.update(source_parent=str(base),scope='Unqualified EP8 contiguous dispatch staging on byte-identical zero-byte-marker transport; combine and progress cadence unchanged; tracing explicitly rejected')
m['files']={str(p.relative_to(out)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(out.rglob('*')) if p.is_file() and p.name!='manifest.json'}
(out/'manifest.json').write_text(json.dumps(m,indent=2)+'\n')
print('PASS transport/combine identity, exact dispatch-only archive delta and named EP gate dependencies; GPU unqualified')
print(out)
