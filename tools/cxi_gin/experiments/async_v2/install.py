"""Create private runtimes; never modify tested releases or an existing prefix."""
import hashlib,json,shutil,sys
from pathlib import Path
from prepare_trace import prepare_headers
snapshot,tested,root=map(Path,sys.argv[1:]);sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
m=json.loads((snapshot/'manifest.json').read_text());assert sha(tested/'lib/libnccl.so.2.32.3')==m['baseline_library_sha256']
assert sha(tested/'include/nccl_device/gin/cxi/cxi_primitives.cuh')==sha(snapshot/'baseline-cxi_primitives.cuh')
variants=json.loads((snapshot/'variants.json').read_text())
for base in ['baseline','async','cap4','threshold']:variants[base+'-trace']=dict(variants[base])
for variant,defines in variants.items():
    dest=root/variant;assert not dest.exists(),dest
    shutil.copytree(tested/'include',dest/'include');(dest/'lib').mkdir()
    shutil.copyfile(tested/'lib/libnccl.so.2.32.3',dest/'lib/libnccl.so.2.32.3')
    (dest/'lib/libnccl.so.2').symlink_to('libnccl.so.2.32.3');(dest/'lib/libnccl.so').symlink_to('libnccl.so.2')
    d=dest/'include/nccl_device/gin/cxi'
    if variant not in ['baseline','baseline-trace']:
        for name in ['cxi_primitives.cuh','cxi_queue_credit.h']:shutil.copyfile(snapshot/'backend/device'/name,d/name)
    p=d/'cxi_primitives.cuh';p.write_text(''.join('#define %s %d\n'%(k,v) for k,v in sorted(defines.items()))+p.read_text())
    if variant.endswith('-trace'):prepare_headers(d)
    manifest=dict(variant=variant,gpu_qualified=False,defines=defines,files={str(p.relative_to(dest)):sha(p) for p in sorted(dest.rglob('*')) if p.is_file()})
    (dest/'runtime-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n');print(dest)
