"""Same-allocation, interleaved marker control/zero ordinary EP8 comparisons.

No source/runtime changes. Schedule only after the corrected marker probes and
the full zero-marker qualification sequence pass in this allocation.
"""
import argparse
import copy
import hashlib
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('campaign', type=Path)
    parser.add_argument('--qualification-sequence',default='newnode-marker-v3-zero-qualification-sequence.json')
    parser.add_argument('--gate-base',type=int,default=1400)
    parser.add_argument('--version',default='v1')
    args = parser.parse_args()
    root = args.campaign
    parents = json.loads((root / args.qualification_sequence).read_text())
    probes = json.loads((root / 'newnode-marker-v3-probes-sequence.json').read_text())
    source = Path(parents[0]['snapshot']).name
    prereq = ['1120-marker-control-notification-probe', '1122-marker-zero-notification-probe']
    for suffix in ['tiny-stress','ep-correctness','sustained16k','repeat1','repeat2','repeat3']:
        matches=[s for s in parents if s['name'].endswith('-'+suffix)]
        assert len(matches)==1,(suffix,matches)
        prereq.append(matches[0]['name'])
    assert len(prereq) == 8
    template = next(s for s in parents if s['name'].endswith('-repeat1'))
    assert Path(template['snapshot']).name == source
    seq = []

    def add(label, variant, extra, requires, seconds):
        step = copy.deepcopy(template)
        step.update(name='%d-%s' % (args.gate_base + len(seq), label), requires=requires,
                    timeout_seconds=seconds)
        step['environment'].update(CXI_VARIANT=variant, CXI_TEST_TIMEOUT=str(seconds - 60))
        step['environment'].update(extra)
        assert step['qualification'] == 'ep' and step['environment']['CXI_TEST_KIND'] == 'ep'
        seq.append(step)
        return step['name']

    control = add('marker-matched-control-tiny-stress', 'marker-control', dict(
        CXI_EP_TOKENS='32 257', CXI_EP_ROUTING='mixed uniform hot_rank local remote',
        CXI_EP_SEEDS='1 2 3', CXI_EP_NIC_ITERS='0',CXI_REQUIRE_REUSE='1'), prereq, 1200)
    control = add('marker-matched-control-sustained16k', 'marker-control', dict(
        CXI_EP_TOKENS='16384', CXI_EP_SEEDS='1 2 3', CXI_EP_NIC_ITERS='0'), [control], 900)
    for rep, order in enumerate([['control', 'zero'], ['zero', 'control'], ['control', 'zero']], 1):
        for variant in order:
            add('marker-matched-%s-repeat%d' % (variant, rep), 'marker-' + variant,
                {}, [control] + prereq, 600)
    known = {s['name'] for s in parents + probes}
    for s in seq:
        assert set(s['requires']) <= known and s['name'] not in known
        known.add(s['name'])
    name = 'marker-matched-'+args.version+'-sequence.json'
    payload = (json.dumps(seq, indent=2) + '\n').encode()
    (root / name).write_bytes(payload)
    plan = dict(requires=prereq, resume_original=False, phases=[dict(
        snapshot=source, sequence=name, sequence_sha256=hashlib.sha256(payload).hexdigest())])
    (root / ('ready-plan-marker-matched-'+args.version+'.json')).write_text(json.dumps(plan, indent=2) + '\n')
    print('Prepared eight gates; transport/source unchanged, GPU execution gated and not launched')


if __name__ == '__main__':
    main()
