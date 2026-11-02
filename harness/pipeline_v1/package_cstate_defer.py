"""Isolate CSTATE doorbell deferral on the zero-marker transport, ABI unchanged."""
import argparse
import copy
import hashlib
import json
import shutil
from pathlib import Path
from package import ROOT, REMOTE, replace


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('output', type=Path)
    parser.add_argument('--parent',default='source-marker-probe-v3')
    parser.add_argument('--qualification-sequence',default='newnode-marker-v3-zero-qualification-sequence.json')
    parser.add_argument('--gate-base',type=int,default=1500)
    args=parser.parse_args();out=args.output.resolve()
    assert Path(args.parent).name==args.parent
    parent = ROOT / 'results/deepep_pipeline_20261030'/args.parent
    shutil.copytree(parent, out, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    primitive = out / 'backend/device/cxi_primitives.cuh'
    replace(primitive, 'namespace cxi_gin {', '''#ifndef CXI_DEFER_CSTATE
#define CXI_DEFER_CSTATE 0
#endif
static_assert(CXI_DEFER_CSTATE == 0 || CXI_DEFER_CSTATE == 1, "boolean CSTATE publication policy");
namespace cxi_gin {''')
    replace(primitive, 'st->write_lac=dst->local_lac;return emit(c,words,false,abort);', '''st->write_lac=dst->local_lac;
  // Both callers hold the context lock and immediately append a nonaggregated
  // atomic or IDC PUT. That operation publishes the ordered CSTATE as well.
  // Capacity waits and the existing bounded batch limit still force publication.
  return emit(c,words,false,abort,default_timeout,CXI_DEFER_CSTATE);''')
    base = json.loads((parent / 'variants.json').read_text())['marker-zero']
    variants = {name:dict(base, CXI_DEFER_CSTATE=value)
                for name, value in [('cstate-control', 0), ('cstate-defer', 1)]}
    (out / 'variants.json').write_text(json.dumps(variants, indent=2) + '\n')
    (out / 'runner/preflight.sh').write_text('''#!/usr/bin/env bash
set -euo pipefail
: "${CAMPAIGN:?}" "${INITIAL_SNAPSHOT:?}"
src="$INITIAL_SNAPSHOT"
sdk=/iopsstor/scratch/cscs/zyu/deepep-direct-20261026/cuda-sdk/usr/local/cuda-13.0
out="$CAMPAIGN/preflight/$(basename "$src")"
mkdir -p "$out"
mkdir -p "$out/tmp"
export TMPDIR="$out/tmp"
g++ -std=c++17 -O2 -Wall -Wextra -Werror -I"$src/backend/device" "$src/runner/test_queue_credit.cc" -o "$out/queue-test"
"$out/queue-test"
g++ -std=c++17 -Wall -Wextra -Werror -Wno-misleading-indentation -I"$sdk/include" -I"$src/backend/include" -c "$src/backend/host/cxi_resources.cc" -o "$out/resources.o"
g++ -std=c++17 -Wall -Wextra -Werror -I"$src/backend/device" "$src/runner/test_fence_descriptor.cc" -o "$out/fence-descriptor"
"$out/fence-descriptor"
for variant in cstate-control cstate-defer; do
  prefix="$CAMPAIGN/runtime/$(basename "$src")/$variant"
  defer=0; if [[ "$variant" = cstate-defer ]]; then defer=1; fi
  for name in gin_smoke gin_bounds gin_producer_stress device_compile_probe; do
    "$sdk/bin/nvcc" -std=c++17 -arch=sm_90 -I"$prefix/include" -c "$src/backend/tests/$name.cu" -o "$out/$variant-$name.o"
  done
  "$sdk/bin/nvcc" -std=c++17 -arch=sm_90 -DCXI_DEFER_CSTATE="$defer" -DCXI_ZERO_DELIVERY_MARKER=1 -DCXI_HW_SIGNAL_FENCE=1 -DCXI_BATCH_DELIVERY=1 -DCXI_CT_THRESHOLD_FLUSH=1 -DCXI_TX_BATCH_LIMIT=8 -I"$src/backend/include" -I"$src/backend/device" -c "$src/runner/burst_probe.cu" -o "$out/$variant-burst.o"
done
date -Is > "$out/PASS"
''')
    campaign = ROOT / 'results/deepep_pipeline_20261030'
    parents = json.loads((campaign / args.qualification_sequence).read_text())
    def template(suffix):
        matches = [s for s in parents if s['name'].endswith('-'+suffix)]
        assert len(matches) == 1
        return matches[0]
    prereq=[template(s)['name'] for s in ['tiny-stress','ep-correctness','sustained16k','repeat1','repeat2','repeat3']]
    seq = []
    def add(label, variant, prefix, requires, env=None, seconds=900):
        step = copy.deepcopy(template(prefix))
        step.update(name='%d-%s' % (args.gate_base + len(seq), label),
                    snapshot=REMOTE + '/sources/' + out.name, requires=requires,
                    timeout_seconds=seconds)
        step['environment'].update(CXI_VARIANT=variant, CXI_TEST_TIMEOUT=str(seconds-60))
        step['environment'].update(env or {})
        seq.append(step); return step['name']
    ends = []
    for variant in variants:
        gate = add(variant+'-notification', variant, 'public-gin', prereq,
                   dict(CXI_SMOKE_CONTEXTS='2', CXI_SMOKE_ROUNDS='14', CXI_MUTATION_EXPECT='preserve'), 1200)
        gate = add(variant+'-wrap', variant, 'wrap', [gate], seconds=420)
        gate = add(variant+'-producers', variant, 'producers', [gate])
        gate = add(variant+'-tiny-stress', variant, 'tiny-stress', [gate], seconds=1200)
        gate = add(variant+'-ep-correctness', variant, 'ep-correctness', [gate], seconds=1200)
        gate = add(variant+'-sustained16k', variant, 'sustained16k', [gate])
        ends.append(gate)
    for rep, order in enumerate([list(variants), list(reversed(variants)), list(variants)], 1):
        for variant in order:
            add(variant+'-repeat'+str(rep), variant, 'repeat1', ends, seconds=600)
    known = {s['name'] for s in parents}
    for step in seq:
        assert set(step['requires']) <= known and step['name'] not in known
        known.add(step['name'])
    (out / 'sequence.json').write_text(json.dumps(seq, indent=2)+'\n')
    before = json.loads((parent / 'manifest.json').read_text())
    after = {str(p.relative_to(out)):hashlib.sha256(p.read_bytes()).hexdigest()
             for p in sorted(out.rglob('*')) if p.is_file() and p.name != 'manifest.json'}
    changed = {k for k in before['files'] if before['files'][k] != after[k]}
    assert changed == {'backend/device/cxi_primitives.cuh', 'variants.json', 'runner/preflight.sh', 'sequence.json'}
    assert set(before['files']) == set(after)
    before.update(source_parent=str(parent), files=after,
                  scope='Unqualified CSTATE publication deferral only; zero-byte marker, command order, credits, completion accounting, ABI and DeepEP archives unchanged')
    (out / 'manifest.json').write_text(json.dumps(before, indent=2)+'\n')
    print('PASS exact four-file delta; DeepEP/ABI/host/qualifier unchanged; GPU unqualified')


if __name__ == '__main__':
    main()
