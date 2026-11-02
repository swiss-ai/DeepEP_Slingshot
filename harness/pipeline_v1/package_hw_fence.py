"""Compile and qualify NIC-ordered signals with matched GPU-wait controls."""
import argparse
import hashlib
import json
import shutil
from pathlib import Path
from package import ROOT, REMOTE, replace
from prepare_hw_fence import prepare
from prepare_probe_readiness import prepare as prepare_readiness


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('output', type=Path)
    out = parser.parse_args().output.resolve()
    base = ROOT / 'results/deepep_pipeline_20261030/source-delivery-v3'
    shutil.copytree(base, out, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    prepare(out)
    prepare_readiness(out)
    variants = {
        'fence-control': dict(CXI_HW_SIGNAL_FENCE=0, CXI_BATCH_DELIVERY=0),
        'fence-dc': dict(CXI_HW_SIGNAL_FENCE=1, CXI_BATCH_DELIVERY=0),
        'fence-batched': dict(CXI_HW_SIGNAL_FENCE=1, CXI_BATCH_DELIVERY=1)}
    for definitions in variants.values():
        definitions.update(CXI_CT_THRESHOLD_FLUSH=1, CXI_TX_BATCH_LIMIT=8)
    (out / 'variants.json').write_text(json.dumps(variants, indent=2) + '\n')
    preflight = out / 'runner/preflight.sh'
    replace(preflight, 'for variant in delivery-control delivery-batched; do',
            'for variant in fence-control fence-dc fence-batched; do')
    replace(preflight, 'for limit in 0 1; do', 'for limit in 0 1; do\nfor hw_fence in 0 1; do')
    replace(preflight, '-DCXI_TX_BATCH_LIMIT=8 -DCXI_BATCH_DELIVERY="$limit"',
            '-DCXI_HW_SIGNAL_FENCE="$hw_fence" -DCXI_TX_BATCH_LIMIT=8 -DCXI_BATCH_DELIVERY="$limit"')
    replace(preflight, '"$out/burst-$limit.o"', '"$out/burst-$limit-fence$hw_fence.o"')
    replace(preflight, 'date -Is > "$out/PASS"', '''done
g++ -std=c++17 -Wall -Wextra -Werror -I"$src/backend/device" \
  "$src/runner/test_fence_descriptor.cc" -o "$out/fence-descriptor"
"$out/fence-descriptor"
date -Is > "$out/PASS"''')
    sequence = []
    common = dict(CXI_EP_SMS='64', CXI_EP_CONTEXTS='129', CXI_EP_DEBUG='0',
        CXI_TRANSPORT='direct', CXI_QUEUE_INVENTORY='1', CXI_EP_UPDATE_INTERVAL='3', CXI_DEVICE_TRACE='0')
    settings = dict(CXI_EP_MODELS='v4flash', CXI_EP_TOKENS='4096 16384', CXI_EP_DTYPES='fp8',
        CXI_EP_ROUTING='mixed', CXI_EP_SEEDS='1', CXI_EP_WARMUP='20', CXI_EP_ITERS='100',
        CXI_EP_NIC_ITERS='600', CXI_EP_PROFILE_STEPS='0')
    def add(label, variant, kind, qualification, extra, requires, duration=1200):
        name = '%03d-%s' % (400+len(sequence), label)
        env = dict(common, CXI_VARIANT=variant, CXI_TEST_KIND=kind, CXI_TEST_TIMEOUT=str(duration-60))
        env.update(extra)
        sequence.append(dict(name=name, snapshot=REMOTE+'/sources/'+out.name, node_script='runner/node.sh',
            qualification=qualification, timeout_seconds=duration, environment=env, requires=requires))
        return name
    gates = {}
    for variant in variants:
        prerequisite = ('207-delivery-batched-ep-correctness' if variant == 'fence-batched'
                        else '203-delivery-control-ep-correctness')
        gate = add(variant+'-gin', variant, 'smoke', 'gin', dict(CXI_SMOKE_CONTEXTS='1,4,129',
            CXI_SMOKE_ROUNDS='28', CXI_SMOKE_RESET='1', CXI_SMOKE_SELF='1', CXI_SMOKE_NEGATIVE='1'),
            [prerequisite], duration=1500)
        gate = add(variant+'-wrap', variant, 'burst', 'burst', {}, [gate], duration=420)
        gate = add(variant+'-producers', variant, 'producer', 'gin',
            dict(CXI_PRODUCER_BLOCKS='1,2,8', CXI_PRODUCER_ROUNDS='256'), [gate], duration=900)
        gates[variant] = add(variant+'-ep-correctness', variant, 'ep', 'ep',
            dict(settings, CXI_EP_TOKENS='257 4096', CXI_EP_ROUTING='mixed uniform hot_rank local remote',
                 CXI_EP_ITERS='3', CXI_EP_WARMUP='2', CXI_EP_NIC_ITERS='0'), [gate], duration=1500)
    names = list(variants)
    for repeat, order in enumerate([names, list(reversed(names)), names[1:]+names[:1]], 1):
        for variant in order:
            add(variant+'-repeat'+str(repeat), variant, 'ep', 'ep', settings, [gates[variant]])
    (out / 'sequence.json').write_text(json.dumps(sequence, indent=2) + '\n')
    manifest = json.loads((base / 'manifest.json').read_text())
    manifest.update(scope='Unqualified NIC CQ_FENCE before strong signal; payload DC and explicit flush/counter completion retained',
        files={str(p.relative_to(out)): hashlib.sha256(p.read_bytes()).hexdigest()
               for p in sorted(out.rglob('*')) if p.is_file() and p.name != 'manifest.json'})
    (out / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(out)


if __name__ == '__main__':
    main()
