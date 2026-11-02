"""Immutable progress-batching experiments on the qualified CXI threshold backend."""
import argparse
import hashlib
import json
import shutil
import tarfile
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
REMOTE = '/iopsstor/scratch/cscs/zyu/deepep-pipeline-20261030'


def replace(path, old, new):
    text = path.read_text()
    assert text.count(old) == 1, (path, old[:80], text.count(old))
    path.write_text(text.replace(old, new))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('output', type=Path)
    out = parser.parse_args().output.resolve()
    base = ROOT / 'results/deepep_async_20261030/source-v6'
    shutil.copytree(base, out, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    for name in ['DeepEP.tar.gz', 'DeepEP-trace.tar.gz']:
        with tempfile.TemporaryDirectory() as tmp:
            ep = Path(tmp)
            with tarfile.open(out / name) as archive:
                archive.extractall(ep)
            header = ep / 'deep_ep/include/deep_ep/impls/hybrid_dispatch.cuh'
            replace(header, '          int kScaleoutUpdateInterval = 3,',
                    '          int kScaleoutUpdateInterval = CXI_EP_UPDATE_INTERVAL,')
            replace(header, '          int kNumSlotsPerForwardChunk = kScaleoutUpdateInterval,',
                    '          int kNumSlotsPerForwardChunk = CXI_EP_FORWARD_CHUNK,')
            header.write_text('''#ifndef CXI_EP_UPDATE_INTERVAL
#define CXI_EP_UPDATE_INTERVAL 3
#endif
#ifndef CXI_EP_FORWARD_CHUNK
#define CXI_EP_FORWARD_CHUNK CXI_EP_UPDATE_INTERVAL
#endif
static_assert(CXI_EP_UPDATE_INTERVAL >= 1 && CXI_EP_UPDATE_INTERVAL <= 64);
static_assert(CXI_EP_FORWARD_CHUNK >= 1 && CXI_EP_FORWARD_CHUNK <= 64);
''' + header.read_text())
            with tarfile.open(out / name, 'w:gz') as archive:
                archive.add(ep, arcname='.')
    # Each request has its own JIT cache; compiler command records the actual values.
    wrapper = out / 'backend/tests/nvcc_wrapper.py'
    replace(wrapper, "    args=['--ptxas-options=-v']+args", """    args=['--ptxas-options=-v']+args
    interval=int(os.environ.get('CXI_EP_UPDATE_INTERVAL','3'))
    forward=int(os.environ.get('CXI_EP_FORWARD_CHUNK',str(interval)))
    assert 1 <= interval <= 64 and 1 <= forward <= 64
    args=['-DCXI_EP_UPDATE_INTERVAL='+str(interval),'-DCXI_EP_FORWARD_CHUNK='+str(forward)]+args""")
    benchmark = out / 'backend/tests/ep_benchmark.py'
    replace(benchmark, '    owners=idx//(e//ep)', '''    case['progress_update_interval']=int(os.environ.get('CXI_EP_UPDATE_INTERVAL','3'))
    case['forward_chunk']=int(os.environ.get('CXI_EP_FORWARD_CHUNK',str(case['progress_update_interval'])))
    owners=idx//(e//ep)''')
    for name in ['monitor.py', 'run.sbatch']:
        p = out / 'runner' / name
        p.write_text(p.read_text().replace('deepep-async-20261030', 'deepep-pipeline-20261030')
                     .replace('deepep-cxi-waits-v2', 'deepep-cxi-pipeline'))
    # Only threshold and its instrumented build are exercised in this campaign.
    preflight = out / 'runner/preflight.sh'
    replace(preflight,
            'for variant in baseline async cap1 cap2 cap4 cap8 threshold threshold-cap4 baseline-trace async-trace cap4-trace threshold-trace; do',
            'for variant in threshold threshold-trace; do')
    source = REMOTE + '/sources/' + out.name
    common = dict(CXI_EP_SMS='64', CXI_EP_CONTEXTS='129', CXI_EP_DEBUG='0',
                  CXI_TRANSPORT='direct', CXI_QUEUE_INVENTORY='1', CXI_VARIANT='threshold')
    settings = dict(CXI_EP_MODELS='v4flash', CXI_EP_TOKENS='4096 16384',
                    CXI_EP_DTYPES='fp8', CXI_EP_ROUTING='mixed', CXI_EP_SEEDS='1',
                    CXI_EP_WARMUP='20', CXI_EP_ITERS='100', CXI_EP_NIC_ITERS='600',
                    CXI_EP_PROFILE_STEPS='0', CXI_DEVICE_TRACE='0')
    seq = []

    def add(label, kind, qualification, extra, requires=(), timeout=1200):
        name = '%02d-%s' % (len(seq) + 1, label)
        env = dict(common, CXI_TEST_KIND=kind, CXI_TEST_TIMEOUT=str(timeout - 60))
        env.update(extra)
        seq.append(dict(name=name, snapshot=source, node_script='runner/node.sh',
                        qualification=qualification, timeout_seconds=timeout,
                        environment=env, requires=list(requires)))
        return name

    gin = add('threshold-gin', 'smoke', 'gin', dict(CXI_SMOKE_CONTEXTS='1,4,129',
              CXI_SMOKE_RESET='1', CXI_SMOKE_SELF='1', CXI_SMOKE_NEGATIVE='1'), timeout=1500)
    gates = {}
    for interval in [3, 6, 8, 16]:
        gates[interval] = add('interval%d-correctness' % interval, 'ep', 'ep',
            dict(settings, CXI_EP_UPDATE_INTERVAL=str(interval), CXI_EP_TOKENS='257 4096',
                 CXI_EP_ROUTING='mixed uniform hot_rank local remote', CXI_EP_ITERS='3',
                 CXI_EP_WARMUP='2', CXI_EP_NIC_ITERS='0'), [gin], timeout=1500)
    for repeat, order in enumerate([[3, 6, 8, 16], [16, 8, 6, 3], [8, 3, 16, 6]], 1):
        for interval in order:
            add('interval%d-repeat%d' % (interval, repeat), 'ep', 'ep',
                dict(settings, CXI_EP_UPDATE_INTERVAL=str(interval)), [gates[interval]])
    # Trace baseline and larger batches separately; do not use these as ordinary timings.
    for interval in [3, 8, 16]:
        add('interval%d-trace' % interval, 'ep', 'ep_trace',
            dict(settings, CXI_VARIANT='threshold-trace', CXI_EP_UPDATE_INTERVAL=str(interval),
                 CXI_EP_TOKENS='4096', CXI_DEVICE_TRACE='1', CXI_TRACE_CAPTURES='3',
                 CXI_EP_NIC_ITERS='0', CXI_EP_ITERS='30', CXI_EP_PROFILE_STEPS='2'),
            [gates[interval]], timeout=1800)
    (out / 'sequence.json').write_text(json.dumps(seq, indent=2) + '\n')
    manifest = json.loads((base / 'manifest.json').read_text())
    manifest.update(scope='Progress batching: same threshold backend, intervals 3/6/8/16; correctness, three repeats, traces',
                    source_baseline=str(base),
                    files={str(p.relative_to(out)): hashlib.sha256(p.read_bytes()).hexdigest()
                           for p in sorted(out.rglob('*')) if p.is_file() and p.name != 'manifest.json'})
    (out / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(out)


if __name__ == '__main__':
    main()
