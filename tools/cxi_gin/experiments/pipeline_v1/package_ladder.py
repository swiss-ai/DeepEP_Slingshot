"""Prepare a separate immutable transport-ladder snapshot for the held allocation."""
import argparse
import hashlib
import json
import shutil
from pathlib import Path
from package import ROOT, HERE, REMOTE, replace


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('output', type=Path)
    out = parser.parse_args().output.resolve()
    base = ROOT / 'results/deepep_pipeline_20261030/source-v1'
    shutil.copytree(base, out, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    shutil.copyfile(HERE / 'gin_stage_ladder.cu', out / 'backend/tests/gin_stage_ladder.cu')
    shutil.copyfile(HERE / 'run_ladder.py', out / 'runner/run_ladder.py')
    replace(out / 'runner/install.py', "for base in ['baseline','async','cap4','threshold']:variants[base+'-trace']=dict(variants[base])",
            "variants={'threshold':variants['threshold']}")
    replace(out / 'runner/preflight.sh', 'for variant in threshold threshold-trace; do',
            'for variant in threshold; do')
    replace(out / 'runner/preflight.sh', 'for name in gin_smoke gin_producer_stress device_compile_probe; do',
            'for name in gin_smoke gin_producer_stress device_compile_probe gin_stage_ladder; do')
    replace(out / 'backend/tools/direct_node.sh', '  producer) test_source=gin_producer_stress.cu;;',
            '  producer) test_source=gin_producer_stress.cu;;\n  ladder) test_source=gin_stage_ladder.cu;;')
    replace(out / 'backend/tests/gin_smoke.py', "    elif kind == 'producer':", """    elif kind == 'ladder':
        function = lib.gin_stage_ladder
        dimensions = os.getenv('CXI_LADDER_CONTEXTS', '129,257')
        rounds = int(os.getenv('CXI_LADDER_ROUNDS', '30'))
        dimension_name = 'contexts'
    elif kind == 'producer':""")
    replace(out / 'runner/validate_gate.py', "    if mode == 'gin':", """    if mode == 'ladder':
        require(transport == 'direct', 'ladder requires direct transport')
        contexts = [int(v) for v in env['CXI_LADDER_CONTEXTS'].split(',')]
        rounds = int(env['CXI_LADDER_ROUNDS'])
        for rank in range(8):
            record = json.loads((base/'smoke'/('rank%d.json' % rank)).read_text())
            require(record.get('rank') == rank and record.get('stage') == 'complete'
                    and record.get('gin_type') == '6' and record.get('kind') == 'ladder', 'wrong/incomplete ladder rank')
            require(len(record['cases']) == len(contexts), 'missing ladder dimensions')
            for cycle, case in enumerate(record['cases']):
                require(case.get('contexts') == contexts[cycle] and case.get('returncode') == 0, 'ladder context failed')
                require(Path(case['evidence']).name == case['evidence'], 'unsafe evidence path')
                rows = json_lines(base/'smoke'/case['evidence'])
                require(rows[-1].get('complete') is True and rows[-1].get('rc') == 0, 'ladder cleanup failed')
                times = [r for r in rows if 'cuda_ms' in r]
                stamps = [r for r in rows if 'channel' in r]
                require(len(times) == rounds and {r['iteration'] for r in times} == set(range(rounds)), 'missing ladder iterations')
                require(len(stamps) == rounds*256, 'missing producer timestamps')
                for r in times:
                    require(r['rank'] == rank and r['contexts'] == contexts[cycle]
                            and r['rows'] == int(env['CXI_LADDER_ROWS'])
                            and r['row_bytes'] == 4320 and r['errors'] == 0
                            and r['signal_interval'] == int(env['CXI_LADDER_SIGNAL_INTERVAL'])
                            and r['coalesce'] == bool(int(env['CXI_LADDER_COALESCE']))
                            and 0 < r['cuda_ms'] < 60000, 'ladder payload/dimensions failure')
                require({(r['iteration'],r['channel']) for r in stamps} ==
                        {(i,c) for i in range(rounds) for c in range(256)}, 'duplicate or missing channel')
                require(all(r['rank'] == rank and r['errors'] == 0 and
                            0 < r['ready_ns'] <= r['submitted_ns'] <= r['flushed_ns'] <= r['received_ns']
                            for r in stamps), 'invalid ladder timestamp')
        return {'status':'PASS', 'kind':'ladder', 'ranks':8, 'contexts':contexts, 'rounds':rounds,
                'scope':'prepacked public-GIN transport intervention; no NVLink forwarding or expert computation'}
    if mode == 'gin':""")
    seq = []
    for rows in [4096, 16384]:
        for label, interval, coalesce in [('coalesced', 0, 1), ('rows-final', 0, 0),
                                         ('signals3', 3, 0), ('signals8', 8, 0), ('signals16', 16, 0)]:
            env = dict(CXI_VARIANT='threshold', CXI_TRANSPORT='direct', CXI_TEST_KIND='ladder',
                       CXI_TEST_TIMEOUT='1140', CXI_QUEUE_INVENTORY='1',
                       CXI_LADDER_ROWS=str(rows), CXI_LADDER_SIGNAL_INTERVAL=str(interval),
                       CXI_LADDER_COALESCE=str(coalesce), CXI_LADDER_CONTEXTS='129,257',
                       CXI_LADDER_ROUNDS='30')
            seq.append(dict(name='%02d-ladder-%s-%d' % (21+len(seq), label, rows),
                            snapshot=REMOTE+'/sources/'+out.name, node_script='runner/node.sh',
                            qualification='ladder', timeout_seconds=1200, environment=env,
                            requires=['01-threshold-gin']))
    (out/'sequence.json').write_text(json.dumps(seq,indent=2)+'\n')
    manifest = json.loads((base/'manifest.json').read_text())
    manifest.update(scope='Public-GIN transport ladder, byte-identical threshold backend',
                    files={str(p.relative_to(out)):hashlib.sha256(p.read_bytes()).hexdigest()
                           for p in sorted(out.rglob('*')) if p.is_file() and p.name!='manifest.json'})
    (out/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print(out)


if __name__ == '__main__':
    main()
