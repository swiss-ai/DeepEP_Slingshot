"""Prepare matched ordinary EP8 row/packed dispatch; no transport patch."""
import argparse
import hashlib
import json
import shutil
from pathlib import Path
from package import HERE, ROOT, REMOTE, replace
from prepare_packed_rows import prepare


def main():
    parser=argparse.ArgumentParser();parser.add_argument('output',type=Path)
    out=parser.parse_args().output.resolve()
    base=ROOT/'results/deepep_pipeline_20261030/source-hw-fence-v3'
    shutil.copytree(base,out,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    prepare(out)
    variants=json.loads((base/'variants.json').read_text())
    (out/'variants.json').write_text(json.dumps({'fence-batched':variants['fence-batched']},indent=2)+'\n')
    shutil.copyfile(HERE/'test_packed_rows.cc',out/'runner/test_packed_rows.cc')
    preflight=out/'runner/preflight.sh'
    replace(preflight,'for variant in fence-control fence-dc fence-batched; do','for variant in fence-batched; do')
    replace(preflight,'date -Is > "$out/PASS"','''g++ -std=c++17 -O2 -Wall -Wextra -Werror -I"$src/runner" \
  "$src/runner/test_packed_rows.cc" -o "$out/packed-model"
"$out/packed-model"
date -Is > "$out/TRANSPORT_PREFLIGHT_PASS"
# DeepEP template compilation is a separate mandatory preflight step.
''')
    parent_specs=json.loads((base/'sequence.json').read_text())
    prereq=[s['name'] for s in parent_specs if s['environment']['CXI_VARIANT']=='fence-batched' and
            (s['name'].endswith('-ep-correctness') or any(s['name'].endswith('-repeat'+str(n)) for n in [1,2,3]))]
    assert len(prereq)==4
    seq=[]
    common=dict(CXI_VARIANT='fence-batched',CXI_TRANSPORT='direct',CXI_EP_SMS='64',CXI_EP_CONTEXTS='129',
                CXI_EP_UPDATE_INTERVAL='3',CXI_EP_DEBUG='0',CXI_DEVICE_TRACE='0',CXI_QUEUE_INVENTORY='1',CXI_EP_DROP_EVERY='0')
    settings=dict(CXI_EP_MODELS='v4flash',CXI_EP_TOKENS='4096 16384',CXI_EP_DTYPES='fp8',CXI_EP_ROUTING='mixed',
                  CXI_EP_SEEDS='1',CXI_EP_WARMUP='20',CXI_EP_ITERS='100',CXI_EP_NIC_ITERS='600',CXI_EP_PROFILE_STEPS='0')
    def add(label,packed,extra,requires,duration=1500):
        name='%03d-%s'%(800+len(seq),label)
        env=dict(common,CXI_EP_PACK_ROWS=str(packed),CXI_TEST_KIND='ep',CXI_TEST_TIMEOUT=str(duration-60))
        env.update(settings);env.update(extra)
        seq.append(dict(name=name,snapshot=REMOTE+'/sources/'+out.name,node_script='runner/node.sh',
                        qualification='ep',timeout_seconds=duration,environment=env,requires=requires))
        return name
    gates={}
    for packed in [0,1]:
        label='rows' if packed==0 else 'packed'
        gate=add(label+'-irregular-correctness',packed,dict(CXI_EP_TOKENS='32 257',CXI_EP_DTYPES='fp8',
            CXI_EP_ROUTING='mixed uniform hot_rank local remote',CXI_EP_ITERS='3',CXI_EP_WARMUP='2',CXI_EP_NIC_ITERS='0'),prereq)
        # Separate processes keep CT allocation lifetime bounded for each matrix.
        gate=add(label+'-4k-correctness',packed,dict(CXI_EP_TOKENS='4096',CXI_EP_DTYPES='fp8 bf16',
            CXI_EP_ROUTING='mixed uniform hot_rank local remote',CXI_EP_ITERS='3',CXI_EP_WARMUP='2',CXI_EP_NIC_ITERS='0'),[gate])
        gate=add(label+'-dropped-token-correctness',packed,dict(CXI_EP_TOKENS='257',CXI_EP_DTYPES='fp8 bf16',
            CXI_EP_ROUTING='mixed local remote',CXI_EP_DROP_EVERY='5',CXI_EP_ITERS='3',CXI_EP_WARMUP='2',CXI_EP_NIC_ITERS='0'),[gate])
        gates[packed]=gate
    for repeat,order in enumerate([[0,1],[1,0],[0,1]],1):
        for packed in order:
            add(('rows' if packed==0 else 'packed')+'-repeat'+str(repeat),packed,{},[gates[packed]])
    known={s['name'] for s in parent_specs}
    for spec in seq:
        assert set(spec['requires'])<=known and spec['name'] not in known,spec['name'];known.add(spec['name'])
    (out/'sequence.json').write_text(json.dumps(seq,indent=2)+'\n')
    manifest=json.loads((base/'manifest.json').read_text())
    manifest.update(source_parent=str(base),scope='EP8-only ordinary dispatch source packing and PUT coalescing at unchanged progress boundaries; transport/ABI/combine unchanged; GPU unqualified',
                    files={str(p.relative_to(out)):hashlib.sha256(p.read_bytes()).hexdigest()
                           for p in sorted(out.rglob('*')) if p.is_file() and p.name!='manifest.json'})
    (out/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n');print(out)


if __name__=='__main__':main()
