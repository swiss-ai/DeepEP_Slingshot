"""Matched NIC TX writeback-policy tests; identical GPU code in both arms."""
import argparse
import hashlib
import json
import shutil
from pathlib import Path
from package import ROOT,REMOTE,replace
from prepare_cq_policy import prepare


def main():
    parser=argparse.ArgumentParser();parser.add_argument('output',type=Path)
    out=parser.parse_args().output.resolve()
    base=ROOT/'results/deepep_pipeline_20261030/source-hw-fence-v3'
    ladder=ROOT/'results/deepep_pipeline_20261030/source-delivery-ladder-v1'
    shutil.copytree(base,out,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    prepare(out)
    variants=json.loads((out/'variants.json').read_text())
    (out/'variants.json').write_text(json.dumps({'fence-batched':variants['fence-batched']},indent=2)+'\n')
    for name in ['backend/tests/gin_stage_ladder.cu','backend/tests/gin_smoke.py',
                 'backend/tools/direct_node.sh','runner/validate_gate.py']:
        shutil.copyfile(ladder/name,out/name)
    (out/'runner/validate_cq_policy.py').write_text('''import re
def validate_policy_log(text,policy,gpus):
    expected={'always':0,'high_empty':1,'low_empty':2}[policy]
    rows=[tuple(map(int,row)) for row in re.findall(r'CXI_QUEUE gpu=(\\d+)[^\\n]*? tx_policy=(\\d+) ct_policy=(\\d+)',text)]
    assert rows and {row[0] for row in rows}==set(gpus), 'missing per-GPU queue policy inventory'
    assert all(tx==expected and ct==0 for gpu,tx,ct in rows), 'requested TX/CT queue policy mismatch'
    return len(rows)
''')
    validator=out/'runner/validate_gate.py'
    replace(validator,"    base = Path(destination) / transport",'''    base = Path(destination) / transport
    if 'CXI_TX_CQ_POLICY' in env:
        from validate_cq_policy import validate_policy_log
        for node in range(2):
            validate_policy_log((base / ('node%d' % node) / 'smoke.log').read_text(),
                                env['CXI_TX_CQ_POLICY'], range(4))''')
    controller=out/'runner/controller.py'
    replace(controller,"        for gpu in range(4):\n            rows=",'''        for gpu in range(4):
            from validate_cq_policy import validate_policy_log
            validate_policy_log((p/('gpu%d.log'%gpu)).read_text(),spec['environment']['CXI_TX_CQ_POLICY'],[gpu])
            rows=''')
    preflight=out/'runner/preflight.sh'
    replace(preflight,'for variant in fence-control fence-dc fence-batched; do','for variant in fence-batched; do')
    replace(preflight,'for name in gin_smoke gin_producer_stress device_compile_probe; do',
            'for name in gin_smoke gin_producer_stress device_compile_probe gin_stage_ladder; do')
    replace(preflight,'date -Is > "$out/PASS"','''g++ -std=c++17 -O2 -Wall -Wextra -Werror -I"$src/backend/include" \
  "$src/runner/test_cq_policy.cc" -o "$out/cq-policy-test"
"$out/cq-policy-test"
date -Is > "$out/PASS"''')
    seq=[]
    common=dict(CXI_VARIANT='fence-batched',CXI_TRANSPORT='direct',CXI_EP_SMS='64',CXI_EP_CONTEXTS='129',
                CXI_EP_UPDATE_INTERVAL='3',CXI_EP_DEBUG='0',CXI_DEVICE_TRACE='0',CXI_QUEUE_INVENTORY='1')
    settings=dict(CXI_EP_MODELS='v4flash',CXI_EP_TOKENS='4096 16384',CXI_EP_DTYPES='fp8',CXI_EP_ROUTING='mixed',
                  CXI_EP_SEEDS='1',CXI_EP_WARMUP='20',CXI_EP_ITERS='100',CXI_EP_NIC_ITERS='600',CXI_EP_PROFILE_STEPS='0')
    def add(label,policy,kind,qualification,extra,requires,duration=1200):
        name='%03d-%s'%(600+len(seq),label)
        env=dict(common,CXI_TX_CQ_POLICY=policy,CXI_TEST_KIND=kind,CXI_TEST_TIMEOUT=str(duration-60));env.update(extra)
        seq.append(dict(name=name,snapshot=REMOTE+'/sources/'+out.name,node_script='runner/node.sh',
                        qualification=qualification,timeout_seconds=duration,environment=env,requires=requires))
        return name
    gates={}
    parent_specs=json.loads((base/'sequence.json').read_text())
    prerequisites=[s['name'] for s in parent_specs
                   if s['environment']['CXI_VARIANT']=='fence-batched' and
                   (s['name'].endswith('-ep-correctness') or
                    any(s['name'].endswith('-repeat'+str(n)) for n in [1,2,3]))]
    assert len(prerequisites)==4, 'Parent correctness and all three timing gates required'
    for policy in ['always','low_empty']:
        gate=add('policy-'+policy+'-gin',policy,'smoke','gin',dict(CXI_SMOKE_CONTEXTS='1,4,129',
            CXI_SMOKE_ROUNDS='28',CXI_SMOKE_RESET='1',CXI_SMOKE_SELF='1',CXI_SMOKE_NEGATIVE='1'),prerequisites,1500)
        gate=add('policy-'+policy+'-wrap',policy,'burst','burst',{},[gate],420)
        gate=add('policy-'+policy+'-producers',policy,'producer','gin',
                 dict(CXI_PRODUCER_BLOCKS='1,2,8',CXI_PRODUCER_ROUNDS='256'),[gate],900)
        gates[policy]=add('policy-'+policy+'-ep-correctness',policy,'ep','ep',dict(settings,
            CXI_EP_TOKENS='257 4096',CXI_EP_ROUTING='mixed uniform hot_rank local remote',CXI_EP_ITERS='3',
            CXI_EP_WARMUP='2',CXI_EP_NIC_ITERS='0'),[gate],1500)
    for label,interval,coalesce in [('coalesced',0,1),('rows-final',0,0),('signals3',3,0)]:
        for policy in ['always','low_empty']:
            add('policy-'+policy+'-'+label,policy,'ladder','ladder',dict(CXI_LADDER_ROWS='4096',
                CXI_LADDER_SIGNAL_INTERVAL=str(interval),CXI_LADDER_COALESCE=str(coalesce),
                CXI_LADDER_CONTEXTS='129',CXI_LADDER_ROUNDS='30'),[gates[policy]])
    for repeat,order in enumerate([['always','low_empty'],['low_empty','always'],['always','low_empty']],1):
        for policy in order:add('policy-'+policy+'-repeat'+str(repeat),policy,'ep','ep',settings,[gates[policy]])
    known={s['name'] for s in parent_specs}
    for spec in seq:
        assert set(spec['requires']) <= known, spec['name']
        assert spec['name'] not in known, 'Duplicate gate identity'
        known.add(spec['name'])
    (out/'sequence.json').write_text(json.dumps(seq,indent=2)+'\n')
    manifest=json.loads((base/'manifest.json').read_text())
    manifest.update(source_parent=str(base),scope='Host TX CQ status update policy only; same native-fence/batched-delivery GPU code; CT queue always unchanged',
                    files={str(p.relative_to(out)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(out.rglob('*')) if p.is_file() and p.name!='manifest.json'})
    (out/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n');print(out)


if __name__=='__main__':main()
