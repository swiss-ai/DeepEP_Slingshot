"""Compile Qwen3 and MiniMax packed EP8 templates; no GPU execution.

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
out = campaign/'preflight'/s.name/('models-q129-i%d-%s' % (a.interval, checker[:12]))
out.mkdir()
ep = out/'source'; ep.mkdir()
with tarfile.open(str(s/'DeepEP.tar.gz')) as archive:
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
runtime = campaign/'runtime'/s.name/'marker-zero'
env = os.environ.copy(); env['TMPDIR'] = str(out)
records = []
for model, h, experts, topk in [('qwen3',4096,128,8), ('minimax',3072,256,8)]:
 for tokens in [257,4096,16384]:
    instances = []
    for dtype, hidden, scales in [('fp8',h,h//128),('bf16',2*h,0)]:
        for mode,cpu,reuse,notify in [('fresh','true','false',4),('cached','false','true',0)]:
            instances.append((mode+'-'+dtype,'dispatch',
                'hybrid_dispatch_impl<%s,%s,64,%d,4,4,2,4,%d,%d,%d,%d,%d,128,129,118800000000>'
                % (cpu,reuse,notify,hidden,scales,tokens,experts,topk)))
    instances.append(('combine','combine',
        'hybrid_combine_impl<false,true,64,4,4,2,4,%d,%d,%d,%d,129,118800000000>' % (h,tokens,experts,topk)))
    for label, header, instance in instances:
        name = '%s-%s-%d-packed1-i%d-q129' % (model, label, tokens, a.interval)
        unit = out/(name+'.cu'); binary = out/(name+'.cubin')
        unit.write_text('#include <deep_ep/impls/hybrid_%s.cuh>\n'
                        'using namespace deep_ep::elastic;\n'
                        'static void __instantiate_kernel() { auto ptr = reinterpret_cast<void*>(&%s); }\n'
                        % (header, instance))
        cmd = [str(sdk/'bin/nvcc'), '-ccbin', '/usr/bin/g++-13', str(unit), '-cubin', '-o', str(binary),
               '-std=c++20', '-DCXI_EP_PACK_ROWS=1', '-DCXI_EP_UPDATE_INTERVAL='+str(a.interval),
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
    scope='30 actual Qwen3/MiniMax dispatch/combine templates; compilation only; GPU qualification pending'), indent=2)+'\n')
(out/'PASS').write_text('30 actual SM90a templates PASS; no GPU execution\n')
print('PASS all30 model templates', flush=True)
