#!/usr/bin/env python3
"""Create per-variant NCCL runtime prefixes from one NCCL build, the way the harness does
(harness/runner/install.py): copy the build's include/ and lib/, replace the gin/cxi headers with
this repository's backend headers, prepend the variant's defines to cxi_primitives.cuh and record a
hashed runtime-manifest.json. DeepEP's JIT and the GIN tests then compile that variant by pointing
EP_NCCL_ROOT_DIR at the variant prefix.

usage: make_variant_runtime.py --nccl-build PREFIX --out ROOT [--backend DIR] [--variants FILE] [VARIANT ...]
       (default variants: all in backend/variants.json; a prefix that already exists is never touched)
"""
import argparse, hashlib, json, shutil, sys
from pathlib import Path

HEADERS = {'cassini_user_defs.h': 'include', 'cxi_gin_abi.h': 'include', 'cxi_primitives.cuh': 'device',
           'cxi_queue_credit.h': 'device', 'cxi_fence_command.h': 'device', 'gin_cxi.cuh': 'device'}

def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def main():
    repo = Path(__file__).resolve().parents[1]
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--nccl-build', required=True, type=Path, help='NCCL build prefix with include/ and lib/libnccl.so.2.*')
    ap.add_argument('--out', required=True, type=Path, help='directory that receives one sub-directory per variant')
    ap.add_argument('--backend', type=Path, default=repo / 'backend')
    ap.add_argument('--variants', type=Path, default=None, help='variants JSON (default backend/variants.json)')
    ap.add_argument('variant', nargs='*')
    a = ap.parse_args()
    variants = json.loads((a.variants or a.backend / 'variants.json').read_text())
    names = a.variant or sorted(variants)
    unknown = [n for n in names if n not in variants]
    if unknown: sys.exit('unknown variant(s): %s (known: %s)' % (', '.join(unknown), ', '.join(sorted(variants))))
    libs = sorted((a.nccl_build / 'lib').glob('libnccl.so.2.*'))
    if not libs or not (a.nccl_build / 'include/nccl_device.h').is_file(): sys.exit('not an NCCL build prefix: %s' % a.nccl_build)
    lib = libs[-1]
    for name in names:
        dest = a.out / name
        if dest.exists(): sys.exit('refusing to overwrite existing prefix %s' % dest)
        shutil.copytree(a.nccl_build / 'include', dest / 'include'); (dest / 'lib').mkdir()
        shutil.copyfile(lib, dest / 'lib' / lib.name)
        (dest / 'lib/libnccl.so.2').symlink_to(lib.name); (dest / 'lib/libnccl.so').symlink_to('libnccl.so.2')
        d = dest / 'include/nccl_device/gin/cxi'; d.mkdir(parents=True, exist_ok=True)
        for h, sub in HEADERS.items(): shutil.copyfile(a.backend / sub / h, d / h)
        p = d / 'cxi_primitives.cuh'
        p.write_text(''.join('#define %s %d\n' % (k, v) for k, v in sorted(variants[name].items())) + p.read_text())
        manifest = dict(variant=name, defines=variants[name], gpu_qualified=False,
                        nccl_build=str(a.nccl_build.resolve()), backend=str(a.backend.resolve()),
                        files={str(f.relative_to(dest)): sha(f) for f in sorted(dest.rglob('*')) if f.is_file()})
        (dest / 'runtime-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
        print(dest)

if __name__ == '__main__':
    main()
