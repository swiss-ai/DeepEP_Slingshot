#!/usr/bin/env python3
"""Allocation I (2026-11-02): raw PUT offset/length probe on the private CXI device primitives.

Parent: results/deepep_pipeline_20261101/source-1101-first-batch-v1 (GPU archive untouched; the probe
does not use DeepEP). Added: runner/offset_probe.cu (derived from runner/burst_probe.cu), a
CXI_TEST_KIND=offset branch in runner/node.sh (compile + run on the four GPUs of each node, like the
burst kind), a `qualify_offset` qualification in runner/controller.py, and the probe's compilation in
runner/preflight.sh. Two gates (9000, 9001) run the probe twice on the marker-zero transport flags.

usage: package_offset_probe_1101.py results/deepep_pipeline_20261101/source-1101-offset-probe-v1
"""
import hashlib, json, shutil, sys
from pathlib import Path
HERE = Path(__file__).resolve().parent; sys.path.insert(0, str(HERE.parent / 'pipeline_v1'))
from package import replace  # noqa: E402
ROOT = HERE.parents[3]; NEW = ROOT / 'results/deepep_pipeline_20261101'
REMOTE = '/iopsstor/scratch/cscs/zyu/deepep-pipeline-20261030'
out = Path(sys.argv[1]).resolve(); assert not out.exists(), out
parent = NEW / 'source-1101-first-batch-v1'
shutil.copytree(parent, out, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
shutil.copyfile(HERE / 'offset_probe.cu', out / 'runner/offset_probe.cu')

# node.sh: an `offset` kind next to the `burst` kind (same compile/run shape, own output directory).
node = out / 'runner/node.sh'; t = node.read_text()
anchor = 'if [ "${CXI_TEST_KIND:-smoke}" = burst ]; then'
assert t.count(anchor) == 1
block_start = t.index(anchor); block_end = t.index('\n  exit "$failed"\nfi\n', block_start) + len('\n  exit "$failed"\nfi\n')
burst_block = t[block_start:block_end]
offset_block = (burst_block.replace('= burst ]', '= offset ]').replace('$OUT/dynamic', '$OUT/offset')
                .replace('runner/burst_probe.cu', 'runner/offset_probe.cu')
                .replace("printf 'burst queue-wrap/source-reuse probe\\n'", "printf 'raw PUT offset/length probe\\n'")
                .replace('240s "$base/probe"', '600s "$base/probe"'))
assert offset_block != burst_block and 'offset_probe.cu' in offset_block and '$OUT/offset' in offset_block
node.write_text(t[:block_start] + offset_block + t[block_start:])

# preflight.sh: compile the probe on the login node with every transport flag combination.
replace(out / 'runner/preflight.sh',
        '    -I"$src/backend/include" -I"$src/backend/device" -c "$src/runner/burst_probe.cu" -o "$out/burst-$limit-fence$hw_fence-zero$zero.o"\n',
        '    -I"$src/backend/include" -I"$src/backend/device" -c "$src/runner/burst_probe.cu" -o "$out/burst-$limit-fence$hw_fence-zero$zero.o"\n'
        '  "$sdk/bin/nvcc" -std=c++17 -arch=sm_90 -DCXI_ZERO_DELIVERY_MARKER="$zero" -DCXI_HW_SIGNAL_FENCE="$hw_fence" -DCXI_TX_BATCH_LIMIT=8 -DCXI_BATCH_DELIVERY="$limit" -DCXI_CT_THRESHOLD_FLUSH=1 \\\n'
        '    -I"$src/backend/include" -I"$src/backend/device" -c "$src/runner/offset_probe.cu" -o "$out/offset-$limit-fence$hw_fence-zero$zero.o"\n')

# controller.py: qualification for the offset kind.
ctrl = out / 'runner/controller.py'; c = ctrl.read_text()
replace(ctrl, "def main():", '''def qualify_offset(out):
    import statistics
    summary={}
    for node in range(2):
        p=out/'offset'/('node%d'%node)
        assert sorted(x.split() for x in (p/'status.tsv').read_text().splitlines())==[[str(i),'0'] for i in range(4)]
        for gpu in range(4):
            rows=[json.loads(x) for x in (p/('gpu%d.log'%gpu)).read_text().splitlines() if x.startswith('{')]
            cases=[r for r in rows if r['stage']=='offset_case']; res=[r for r in rows if r['stage']=='offset_result']; proc=[r for r in rows if r['stage']=='process_result']
            assert len(res)==1 and len(proc)==1 and res[0]['rank']==node*4+gpu
            assert res[0]['cases']==res[0]['expected']==len(cases) and res[0]['errors']==0 and res[0]['diagnostic']==0
            assert res[0]['posted']==res[0]['completed'] and proc[0]['rc']==0 and proc[0]['is_nccl_gin'] is False
            for r in cases:
                assert r['ns']>0
                summary.setdefault('%d/%d/%d'%(r['row'],r['len_rows'],r['off_rows']),[]).append(r['gbps'])
    return {'status':'PASS','kind':'offset_probe','ranks':8,'cases':len(summary),
            'median_gbps_by_row_len_off':{k:round(statistics.median(v),3) for k,v in sorted(summary.items())}}

def main():''')
replace(ctrl, "record['qualification']=qualify_burst(out) if spec['qualification']=='burst' else qualify(out,spec)",
        "record['qualification']=qualify_burst(out) if spec['qualification']=='burst' else qualify_offset(out) if spec['qualification']=='offset' else qualify(out,spec)")

snapshot = REMOTE + '/sources/' + out.name
env = dict(CXI_EP_SMS='64', CXI_EP_CONTEXTS='129', CXI_EP_DEBUG='0', CXI_TRANSPORT='direct', CXI_QUEUE_INVENTORY='1',
           CXI_EP_UPDATE_INTERVAL='16', CXI_DEVICE_TRACE='0', CXI_VARIANT='marker-zero', CXI_TEST_KIND='offset', CXI_TEST_TIMEOUT='840')
seq = [dict(name='9000-offset-probe-run1', snapshot=snapshot, node_script='runner/node.sh', qualification='offset', timeout_seconds=900, environment=env, requires=[]),
       dict(name='9001-offset-probe-run2', snapshot=snapshot, node_script='runner/node.sh', qualification='offset', timeout_seconds=900, environment=env, requires=['9000-offset-probe-run1'])]
(out / 'sequence.json').write_text(json.dumps(seq, indent=2) + '\n')
m = json.loads((parent / 'manifest.json').read_text())
m.update(source_parent=str(parent), scope='2026-11-02 allocation I: raw PUT offset/length probe (phase of packed PUT boundaries vs NIC rate); GPU archive unchanged and unused')
m['files'] = {str(p.relative_to(out)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(out.rglob('*')) if p.is_file() and p.name != 'manifest.json'}
(out / 'manifest.json').write_text(json.dumps(m, indent=2) + '\n')
compile(c, 'controller', 'exec'); compile(ctrl.read_text(), 'controller-new', 'exec')
print('offset probe snapshot ready:', out); print([g['name'] for g in seq])
