"""Match transport granularity probes across the two delivery-completion modes."""
import argparse
import hashlib
import json
import shutil
from pathlib import Path
from package import ROOT, REMOTE, replace


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('output', type=Path)
    out = parser.parse_args().output.resolve()
    base = ROOT / 'results/deepep_pipeline_20261030/source-delivery-v3'
    ladder = ROOT / 'results/deepep_pipeline_20261030/source-ladder-v2'
    shutil.copytree(base, out, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    # Reuse the already qualified probe/frontend/validator. Only transport changes.
    for name in ['backend/tests/gin_stage_ladder.cu', 'backend/tests/gin_smoke.py',
                 'backend/tools/direct_node.sh', 'runner/validate_gate.py']:
        shutil.copyfile(ladder / name, out / name)
    replace(out / 'runner/preflight.sh', 'for name in gin_smoke gin_producer_stress device_compile_probe; do',
            'for name in gin_smoke gin_producer_stress device_compile_probe gin_stage_ladder; do')
    sequence = []
    prerequisites = {s['environment']['CXI_VARIANT']: s['name']
                     for s in json.loads((base / 'sequence.json').read_text())
                     if s['name'].endswith('-ep-correctness')}
    for tokens in [4096, 16384]:
        for label, interval, coalesce in [('coalesced', 0, 1), ('rows-final', 0, 0), ('signals3', 3, 0)]:
            for variant in ['delivery-control', 'delivery-batched']:
                env = dict(CXI_VARIANT=variant, CXI_TRANSPORT='direct', CXI_TEST_KIND='ladder',
                    CXI_TEST_TIMEOUT='1140', CXI_QUEUE_INVENTORY='1', CXI_LADDER_ROWS=str(tokens),
                    CXI_LADDER_SIGNAL_INTERVAL=str(interval), CXI_LADDER_COALESCE=str(coalesce),
                    CXI_LADDER_CONTEXTS='129', CXI_LADDER_ROUNDS='30')
                sequence.append(dict(name='%03d-ladder-%s-%s-%d' %
                    (300 + len(sequence), variant, label, tokens), snapshot=REMOTE+'/sources/'+out.name,
                    node_script='runner/node.sh', qualification='ladder', timeout_seconds=1200,
                    environment=env, requires=[prerequisites[variant]]))
    (out / 'sequence.json').write_text(json.dumps(sequence, indent=2) + '\n')
    manifest = json.loads((base / 'manifest.json').read_text())
    manifest.update(scope='Matched delivery control/batching public-GIN ladder; no NVLink relay',
        files={str(p.relative_to(out)): hashlib.sha256(p.read_bytes()).hexdigest()
               for p in sorted(out.rglob('*')) if p.is_file() and p.name != 'manifest.json'})
    (out / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(out)


if __name__ == '__main__':
    main()
