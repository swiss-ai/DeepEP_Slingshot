"""Prepare isolated packed tracing; never instrument the ordinary candidate."""
import argparse
import hashlib
import json
import shutil
import tarfile
import tempfile
from pathlib import Path
from package import ROOT, REMOTE, replace
from prepare_packed_trace import patched_generator, EVENTS


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('output', type=Path)
    parser.add_argument('--parent', default='source-zero-packed-v7')
    args = parser.parse_args()
    base = ROOT / 'results/deepep_pipeline_20261030' / args.parent
    out = args.output.resolve()
    assert not out.exists()
    shutil.copytree(base, out, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    generator = out / 'runner/prepare_trace.py'
    generator.write_text(patched_generator(generator.read_text()))
    scope = {'__file__': str(generator)}
    exec(compile(generator.read_text(), str(generator), 'exec'), scope)
    with tempfile.TemporaryDirectory() as directory:
        ep = Path(directory)
        with tarfile.open(base / 'DeepEP.tar.gz') as archive:
            archive.extractall(ep)
        scope['prepare_ep'](ep)
        with tarfile.open(out / 'DeepEP-trace.tar.gz', 'w:gz') as archive:
            archive.add(ep, arcname='.')
    assert (base / 'DeepEP.tar.gz').read_bytes() == (out / 'DeepEP.tar.gz').read_bytes()
    node = out / 'runner/node.sh'
    start = node.read_text().index('if [ "${CXI_DEVICE_TRACE:-0}" != 0 ]; then')
    end = node.read_text().index('\nfi', start) + 3
    text = node.read_text()
    text = text[:start] + '''if [ "${CXI_DEVICE_TRACE:-0}" != 1 ]; then
  printf 'Private trace snapshot requires CXI_DEVICE_TRACE=1\\n' >&2
  exit 2
fi''' + text[end:]
    node.write_text(text)
    definitions = json.loads((base / 'variants.json').read_text())['marker-zero']
    (out / 'variants.json').write_text(json.dumps({'marker-zero-trace': definitions}, indent=2)+'\n')
    for relative in ['runner/trace_capture.py', 'backend/tests/trace_capture.py']:
        replace(out / relative, 'TRACE=None', 'EVENTS.update('+repr(EVENTS)+')\nTRACE=None')
    shutil.copyfile(Path(__file__).with_name('validate_trace.py'), out / 'runner/validate_trace.py')
    validator = out / 'runner/validate_trace.py'
    replace(validator, "        required = {200, 201, 202, 204, 205, 206, 209}",
            """        required = {200, 201, 202, 204, 205, 206, 209, 212, 213, 214}
        if row['operation'] == 'dispatch_fresh':
            required |= {114, 115}
            if int(env.get('CXI_EP_PACK_ROWS', '0')):
                required.add(113)""")
    sequences = []
    for index, packed in enumerate([0, 1]):
        env = dict(CXI_VARIANT='marker-zero-trace', CXI_DEVICE_TRACE='1',
            CXI_TRANSPORT='direct', CXI_TEST_KIND='ep', CXI_EP_SMS='64',
            CXI_EP_CONTEXTS='129', CXI_EP_UPDATE_INTERVAL='3', CXI_EP_FORWARD_CHUNK='3',
            CXI_EP_PACK_ROWS=str(packed), CXI_EP_DEBUG='0', CXI_QUEUE_INVENTORY='1',
            CXI_LOCAL_JIT='1', CXI_LOCAL_RESULTS='1', CXI_LOCAL_LOGS='1',
            CXI_DIAGNOSTIC_WATCHDOG='0', CXI_EP_MODELS='v4flash', CXI_EP_TOKENS='4096',
            CXI_EP_DTYPES='fp8', CXI_EP_ROUTING='mixed', CXI_EP_SEEDS='1',
            CXI_EP_WARMUP='20', CXI_EP_ITERS='30', CXI_EP_NIC_ITERS='0',
            CXI_EP_PROFILE_STEPS='0', CXI_TRACE_CAPTURES='3', CXI_TEST_TIMEOUT='1740')
        sequences.append(dict(name=str(3600+index)+'-packed'+str(packed)+'-private-trace',
            snapshot=REMOTE+'/sources/'+out.name, node_script='runner/node.sh',
            qualification='ep_trace', timeout_seconds=1800, environment=env,
            requires=[str(3306+i)+'-'+('zero-rows' if i in [0,3,4] else 'zero-packed')+'-repeat'+str([1,1,2,2,3,3][i]) for i in range(6)]))
    (out / 'sequence.json').write_text(json.dumps(sequences, indent=2)+'\n')
    (out / 'trace-events.json').write_text(json.dumps(dict(events=EVENTS,
        scope='GPU observed submission/availability, not NIC wire timestamps; overlapping scopes; clock bounds required across ranks'), indent=2)+'\n')
    manifest = json.loads((base / 'manifest.json').read_text())
    manifest.update(source_parent=str(base), scope='Private packed trace; ordinary archive unchanged; GPU unqualified')
    manifest['files'] = {str(p.relative_to(out)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(out.rglob('*')) if p.is_file() and p.name != 'manifest.json'}
    (out / 'manifest.json').write_text(json.dumps(manifest, indent=2)+'\n')
    print(out)


if __name__ == '__main__':
    main()
