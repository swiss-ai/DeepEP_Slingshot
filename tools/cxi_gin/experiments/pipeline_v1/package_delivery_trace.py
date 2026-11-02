"""Private tracing of qualified delivery candidates; ordinary code stays intact."""
import argparse
import hashlib
import json
import shutil
from pathlib import Path
from package import ROOT, REMOTE, replace


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('output', type=Path)
    parser.add_argument('--base', type=Path, default=ROOT / 'results/deepep_pipeline_20261030/source-delivery-v2')
    args = parser.parse_args()
    out, base = args.output.resolve(), args.base.resolve()
    shutil.copytree(base, out, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    original_variants = json.loads((base / 'variants.json').read_text())
    variants = {name + '-trace': definitions for name, definitions in original_variants.items()}
    (out / 'variants.json').write_text(json.dumps(variants, indent=2) + '\n')
    replace(out / 'runner/preflight.sh', 'for variant ' + 'in ' + ' '.join(original_variants) + '; do',
            'for variant in ' + ' '.join(variants) + '; do')
    trace = out / 'runner/prepare_trace.py'
    with trace.open('a') as file:
        # This is inside prepare_headers; source primitives are unchanged.
        file.write('''
    p=d/'cxi_primitives.cuh'
    edit(p,'  if(!c.tx_unpublished)return;',
         '  if(!c.tx_unpublished)return;\\n  ep_trace::Scope trace_publish(209,(uint64_t)&c,c.tx_unpublished);')
    edit(p,'  if(!w)return true;',
         '  if(!w)return true;\\n  ep_trace::Scope trace_delivery(210,(uint64_t)&c,c.pending_peer);')
''')
    hardware_fence = 'cxi_build_fence_command(words)' in (base / 'backend/device/cxi_primitives.cuh').read_text()
    if hardware_fence:
        with trace.open('a') as file:
            file.write('''
    edit(p,'  uint64_t words[8];cxi_build_fence_command(words);',
         '  ep_trace::Scope trace_hw_fence(211,(uint64_t)&c,c.posted);\\n  uint64_t words[8];cxi_build_fence_command(words);')
''')
    replace(out / 'runner/trace_capture.py', 'TRACE=None',
            "EVENTS.update({209:'TX_publication',210:'delivery_marker_enqueue',211:'NIC_fence_enqueue'})\nTRACE=None")
    # direct_node.sh executes backend/tests/ep_benchmark.py, which imports its
    # sibling decoder. Updating only the runner copy leaves active imports stale.
    shutil.copyfile(out / 'runner/trace_capture.py', out / 'backend/tests/trace_capture.py')
    shutil.copyfile(Path(__file__).with_name('validate_trace.py'), out / 'runner/validate_trace.py')
    controller = out / 'runner/controller.py'
    text = controller.read_text()
    start = text.index("            if spec['qualification']=='ep_trace':")
    end = text.index('            else:\n', start)
    text = text[:start] + '''            if spec['qualification']=='ep_trace':
                from validate_trace import qualify_trace
                record['qualification']=qualify_trace(out,spec,qualify)
                subprocess.check_call(['python3',str(source/'runner/analyze.py'),str(out)])
''' + text[end:]
    compile(text, str(controller), 'exec')
    controller.write_text(text)
    sequence = []
    prerequisites = {s['environment']['CXI_VARIANT']: s['name']
                     for s in json.loads((base / 'sequence.json').read_text())
                     if s['name'].endswith('-ep-correctness')}
    for number, variant in enumerate(variants, 120):
        candidate = variant.removesuffix('-trace')
        prerequisite = prerequisites[candidate]
        env = dict(CXI_VARIANT=variant, CXI_TRANSPORT='direct', CXI_TEST_KIND='ep',
            CXI_TEST_TIMEOUT='1740', CXI_EP_SMS='64', CXI_EP_CONTEXTS='129', CXI_EP_DEBUG='0',
            CXI_QUEUE_INVENTORY='1', CXI_EP_UPDATE_INTERVAL='3', CXI_DEVICE_TRACE='1',
            CXI_EP_MODELS='v4flash', CXI_EP_TOKENS='4096', CXI_EP_DTYPES='fp8',
            CXI_EP_ROUTING='mixed', CXI_EP_SEEDS='1', CXI_EP_WARMUP='20', CXI_EP_ITERS='30',
            CXI_EP_NIC_ITERS='0', CXI_EP_PROFILE_STEPS='2', CXI_TRACE_CAPTURES='3')
        sequence.append(dict(name='%03d-%s' % (number, variant),
            snapshot=REMOTE + '/sources/' + out.name, node_script='runner/node.sh',
            qualification='ep_trace', timeout_seconds=1800, environment=env, requires=[prerequisite]))
    (out / 'sequence.json').write_text(json.dumps(sequence, indent=2) + '\n')
    (out / 'trace-events.json').write_text(json.dumps({
        '209': 'publish pending TX commands: system fence and GPU MMIO doorbell',
        '210': 'enqueue same-endpoint delivery-completion marker (completion wait is event 207)',
        '211': 'enqueue native NIC CQ fence; does not timestamp its execution in the NIC',
        'scope': 'local GPU durations; overlapping nested scopes; not wire-transfer timestamps'
    }, indent=2) + '\n')
    manifest = json.loads((base / 'manifest.json').read_text())
    manifest.update(scope='Private delivery trace, matched ABI-v3 control/candidate; ordinary sources unchanged',
        files={str(p.relative_to(out)): hashlib.sha256(p.read_bytes()).hexdigest()
               for p in sorted(out.rglob('*')) if p.is_file() and p.name != 'manifest.json'})
    (out / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(out)


if __name__ == '__main__':
    main()
