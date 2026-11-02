"""Prepare gated full qualification; this script does not submit GPU work."""
import hashlib,json
from pathlib import Path
from package import ROOT,REMOTE
r=ROOT/'results/deepep_pipeline_20261030';source=r/'source-marker-probe-v2'
base=json.loads((r/'source-hw-fence-v3/sequence.json').read_text())
named={x['name']:x for x in base}
seq=[]
def add(original,name,requires,updates=None,seconds=600):
 x=json.loads(json.dumps(original));x.update(name=name,snapshot=REMOTE+'/sources/'+source.name,requires=requires,timeout_seconds=seconds)
 x['environment'].update(CXI_VARIANT='marker-zero',CXI_TEST_TIMEOUT=str(seconds-60))
 if updates:x['environment'].update(updates)
 seq.append(x);return name
smoke=add(named['404-fence-dc-gin'],'1200-zero-marker-public-gin',['1112-marker-zero-notification-probe'],seconds=480)
wrap=add(named['405-fence-dc-wrap'],'1201-zero-marker-wrap',[smoke],seconds=420)
producer=add(named['406-fence-dc-producers'],'1202-zero-marker-producers',[wrap],seconds=480)
tiny=add(named['407-fence-dc-ep-correctness'],'1203-zero-marker-tiny-stress',[producer],dict(CXI_EP_TOKENS='32 257',CXI_EP_ROUTING='mixed uniform hot_rank local remote',CXI_EP_SEEDS='1 2 3',CXI_EP_WARMUP='20',CXI_EP_ITERS='100'),seconds=600)
correct=add(named['407-fence-dc-ep-correctness'],'1204-zero-marker-ep-correctness',[tiny],dict(CXI_EP_TOKENS='257 4096',CXI_EP_DTYPES='fp8 bf16',CXI_EP_SEEDS='1 2'),seconds=900)
large=add(named['407-fence-dc-ep-correctness'],'1205-zero-marker-sustained16k',[correct],dict(CXI_EP_TOKENS='16384',CXI_EP_ROUTING='mixed',CXI_EP_SEEDS='1 2 3',CXI_EP_WARMUP='20',CXI_EP_ITERS='100'),seconds=600)
for rep in range(1,4):
 add(named['413-fence-dc-repeat1'],'120%d-zero-marker-repeat%d'%(5+rep,rep),[large],seconds=480)
assert [(x['qualification'],x['environment']['CXI_TEST_KIND']) for x in seq]==[('gin','smoke'),('burst','burst'),('gin','producer')]+[('ep','ep')]*6
p=r/'prepared-zero-marker-checks-v3-sequence.json';p.write_text(json.dumps(seq,indent=2)+'\n')
plan=dict(requires=['1112-marker-zero-notification-probe'],resume_original=False,phases=[dict(snapshot=source.name,sequence=p.name,sequence_sha256=hashlib.sha256(p.read_bytes()).hexdigest())])
(r/'ready-plan-v14.json').write_text(json.dumps(plan,indent=2)+'\n')
print('Prepared',len(seq),'gates; zero-marker mutation probe must pass first')
