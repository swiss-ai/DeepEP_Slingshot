"""Compile private EP8 trace templates for the 129/257-context comparison.

Keep the qualified source immutable. A separate evidence directory records the
exact checker, source, interval and compilation arguments.
"""
import argparse
import hashlib
import json
import os
import subprocess
import tarfile
from pathlib import Path

p = argparse.ArgumentParser()
p.add_argument('source', type=Path)
p.add_argument('--interval', type=int, choices=[3, 8, 16], default=16)
a = p.parse_args()
s = a.source.resolve(); campaign = s.parent.parent
assert (campaign/'preflight'/s.name/'PASS').is_file()
manifest = json.loads((s/'manifest.json').read_text())
for name, digest in manifest['files'].items():
    assert hashlib.sha256((s/name).read_bytes()).hexdigest() == digest, name
checker = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
out = campaign/'preflight'/s.name/('trace-contexts-i%d-%s' % (a.interval, checker[:12]))
out.mkdir()
ep = out/'source'; ep.mkdir()
with tarfile.open(str(s/'DeepEP-trace.tar.gz')) as archive:
    for member in archive:
        name = Path(member.name)
        assert not name.is_absolute() and '..' not in name.parts
        target = ep/name
        if member.isdir():
            target.mkdir(parents=True, exist_ok=True)
        else:
            assert member.isfile(), member.name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.extractfile(member).read())
sdk = Path('/iopsstor/scratch/cscs/zyu/deepep-direct-20261026/cuda-sdk/usr/local/cuda-13.0')
runtime = campaign/'runtime'/s.name/'marker-zero-trace'
env = os.environ.copy(); env['TMPDIR'] = str(out)
records = []
for qps in [129, 257]:
    tokens = 4096
    instances = []
    for dtype, hidden, scales in [('fp8', 4096, 32)]:
        for mode, cpu, reuse, notify in [('fresh', 'true', 'false', 4), ('cached', 'false', 'true', 0)]:
            instances.append((mode+'-'+dtype, 'dispatch',
                'hybrid_dispatch_impl<%s,%s,64,%d,4,4,2,4,%d,%d,%d,256,6,128,257,118800000000>'
                % (cpu, reuse, notify, hidden, scales, tokens)))
    instances.append(('combine', 'combine',
        'hybrid_combine_impl<false,true,64,4,4,2,4,4096,%d,256,6,257,118800000000>' % tokens))
    for label, header, instance in instances:
        instance = instance.replace(',257,', ','+str(qps)+',')
        name = '%s-%d-packed1-i%d-q%d' % (label, tokens, a.interval, qps)
        unit = out/(name+'.cu'); binary = out/(name+'.cubin')
        unit.write_text('#include <deep_ep/impls/hybrid_%s.cuh>\n'
                        'using namespace deep_ep::elastic;\n'
                        'static void __instantiate_kernel() { auto ptr = reinterpret_cast<void*>(&%s); }\n'
                        % (header, instance))
        cmd = [str(sdk/'bin/nvcc'), '-ccbin', '/usr/bin/g++-13', str(unit), '-cubin', '-o', str(binary),
               '-std=c++20', '-DEP_TRACE_PTR=4096ULL', '-DCXI_EP_PACK_ROWS=1', '-DCXI_EP_UPDATE_INTERVAL='+str(a.interval),
               '-DCXI_EP_FORWARD_CHUNK=3', '--ptxas-options=-v', '--ptxas-options=--register-usage-level=10',
               '-I'+str(runtime/'include'), '-I'+str(ep/'deep_ep/include'), '--gpu-architecture=sm_90a',
               '--compiler-options=-fPIC,-O3,-fconcepts,-Wno-deprecated-declarations,-Wno-abi', '-O3',
               '--expt-relaxed-constexpr', '--expt-extended-lambda', '--diag-suppress=39,161,174,177,186,940,3012']
        with (out/(name+'.log')).open('w') as log:
            log.write(' '.join(cmd)+'\n'); log.flush()
            subprocess.check_call(cmd, env=env, stdout=log, stderr=subprocess.STDOUT)
        records.append(dict(name=name, command=cmd, sha256=hashlib.sha256(binary.read_bytes()).hexdigest()))
        print('TEMPLATE_PASS '+name, flush=True)
(out/'compile.json').write_text(json.dumps(dict(checker_sha256=checker, source=s.name,
    manifest_sha256=hashlib.sha256((s/'manifest.json').read_bytes()).hexdigest(), records=records,
    scope='6 actual private dispatch/combine trace templates; compilation only; GPU qualification pending'), indent=2)+'\n')
(out/'PASS').write_text('6 actual private trace SM90a templates PASS; no GPU execution\n')
print('PASS all6 private trace context templates', flush=True)
