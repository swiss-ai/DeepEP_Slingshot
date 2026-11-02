"""Compile the actual EP8 combine, epilogue and dispatch templates of a snapshot on the Clariden
login node for every compile-time arm (packed combine on/off, final-tail merge on/off).
Python 3.6 compatible; no GPU execution. Usage: preflight_combine_templates.py SOURCE VARIANT"""
import hashlib, json, os, subprocess, sys, tarfile
from pathlib import Path
source = Path(sys.argv[1]).resolve(); variant = sys.argv[2]; campaign = source.parent.parent
archive = sys.argv[3] if len(sys.argv) > 3 else 'DeepEP.tar.gz'
extra = [(a if a.startswith('-') else '-D' + a) for a in sys.argv[4:]]
preflight = campaign / 'preflight' / source.name
assert (preflight / 'TRANSPORT_PREFLIGHT_PASS').is_file(), 'transport preflight first'
out = preflight / 'combine-templates'; out.mkdir()
manifest = json.loads((source / 'manifest.json').read_text())
for name, digest in manifest['files'].items():
    assert hashlib.sha256((source / name).read_bytes()).hexdigest() == digest, name
ep = out / 'ordinary-source'; ep.mkdir()
with tarfile.open(str(source / archive)) as a: a.extractall(str(ep))
sdk = Path('/iopsstor/scratch/cscs/zyu/deepep-direct-20261026/cuda-sdk/usr/local/cuda-13.0')
runtime = campaign / 'runtime' / source.name / variant
env = os.environ.copy(); env['TMPDIR'] = str(out)
records = []
def compile_unit(name, body, defines):
    unit = out / (name + '.cu'); binary = out / (name + '.cubin'); unit.write_text(body)
    command = [str(sdk / 'bin/nvcc'), '-ccbin', '/usr/bin/g++-13', str(unit), '-cubin', '-o', str(binary), '-std=c++20'] + defines + [
        '--ptxas-options=-v', '--ptxas-options=--register-usage-level=10',
        '-I' + str(runtime / 'include'), '-I' + str(ep / 'deep_ep/include'),
        '--gpu-architecture=sm_90a', '--compiler-options=-fPIC,-O3,-fconcepts,-Wno-deprecated-declarations,-Wno-abi',
        '-O3', '--expt-relaxed-constexpr', '--expt-extended-lambda', '--diag-suppress=39,161,174,177,186,940,3012']
    with (out / (name + '.log')).open('w') as log:
        log.write(' '.join(command) + '\n'); log.flush()
        subprocess.check_call(command, env=env, stdout=log, stderr=subprocess.STDOUT)
    text = (out / (name + '.log')).read_text()
    spill = [l.strip() for l in text.splitlines() if 'spill' in l]
    regs = [l.strip() for l in text.splitlines() if 'Used' in l and 'registers' in l]
    records.append(dict(name=name, sha256=hashlib.sha256(binary.read_bytes()).hexdigest(), spill=spill, registers=regs))
    print('EP8_TEMPLATE_COMPILE_PASS %s | %s | %s' % (name, ' '.join(regs)[:60], ' '.join(spill)[:80]), flush=True)
common = extra + ['-DCXI_EP_PACK_ROWS=1', '-DCXI_EP_UPDATE_INTERVAL=16', '-DCXI_EP_FORWARD_CHUNK=3', '-DCXI_EP_PACK_COMBINE_CHANNELS=256', '-DCXI_EP_COMBINE_BATCH=16']
for packc in [0, 1]:
    for tokens in [257, 4096, 16384]:
        compile_unit('combine-%d-packc%d' % (tokens, packc), '''#include <deep_ep/impls/hybrid_combine.cuh>
using namespace deep_ep::elastic;
static void __instantiate_kernel() {
 auto ptr = reinterpret_cast<void*>(&hybrid_combine_impl<false,true,64,4,4,2,4,4096,%d,256,6,129,118800000000>);
}
''' % tokens, common + ['-DCXI_EP_PACK_COMBINE=%d' % packc, '-DCXI_EP_MERGE_FINAL_TAIL=0'])
        compile_unit('epilogue-%d-packc%d' % (tokens, packc), '''#include <deep_ep/impls/combine_reduce_epilogue.cuh>
using namespace deep_ep::elastic;
static void __instantiate_kernel() {
 auto ptr = reinterpret_cast<void*>(&combine_reduce_epilogue_impl<false,true,132,32,2,4,4096,%d,256,6>);
}
''' % tokens, common + ['-DCXI_EP_PACK_COMBINE=%d' % packc, '-DCXI_EP_MERGE_FINAL_TAIL=0'])
for merge in [0, 1]:
    for tokens in [257, 4096, 16384]:
        for mode, cpu, reuse, notify in [('fresh', 'true', 'false', 4), ('cached', 'false', 'true', 0)]:
            compile_unit('dispatch-%s-%d-merge%d' % (mode, tokens, merge), '''#include <deep_ep/impls/hybrid_dispatch.cuh>
using namespace deep_ep::elastic;
static void __instantiate_kernel() {
 auto ptr = reinterpret_cast<void*>(&hybrid_dispatch_impl<%s,%s,64,%d,4,4,2,4,4096,32,%d,256,6,128,129,118800000000>);
}
''' % (cpu, reuse, notify, tokens), common + ['-DCXI_EP_PACK_COMBINE=0', '-DCXI_EP_MERGE_FINAL_TAIL=%d' % merge])
(out / 'template-compilation.json').write_text(json.dumps(dict(records=records), indent=2) + '\n')
(preflight / 'PASS').write_text('Transport identity, CPU models, and %d combine/epilogue/dispatch EP8 templates compiled; GPU unqualified. Evidence: %s\n' % (len(records), out))
print('ALL_TEMPLATES_PASS', len(records))
