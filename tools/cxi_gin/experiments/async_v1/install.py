"""Copy tested NCCL runtime; overlay only the candidate device headers."""
import hashlib,json,shutil,sys
from pathlib import Path
snapshot,tested,root=map(Path,sys.argv[1:])
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
m=json.loads((snapshot/'manifest.json').read_text())
assert sha(tested/'lib/libnccl.so.2.32.3')==m['baseline_library_sha256']
assert sha(tested/'include/nccl_device/gin/cxi/cxi_primitives.cuh')==sha(snapshot/'baseline-cxi_primitives.cuh')
for variant in ['baseline','async']:
    dest=root/variant
    assert not dest.exists(),dest
    shutil.copytree(tested/'include',dest/'include')
    (dest/'lib').mkdir()
    shutil.copyfile(tested/'lib/libnccl.so.2.32.3',dest/'lib/libnccl.so.2.32.3')
    (dest/'lib/libnccl.so.2').symlink_to('libnccl.so.2.32.3');(dest/'lib/libnccl.so').symlink_to('libnccl.so.2')
    if variant=='async':
        for name in ['cxi_primitives.cuh','cxi_queue_credit.h']:
            shutil.copyfile(snapshot/'backend/device'/name,dest/'include/nccl_device/gin/cxi'/name)
    manifest={'variant':variant,'gpu_qualified':False,'files':{str(p.relative_to(dest)):sha(p) for p in sorted(dest.rglob('*')) if p.is_file()}}
    (dest/'runtime-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print(dest)
