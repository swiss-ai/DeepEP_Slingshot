#!/usr/bin/env python3
"""Copy the inspected SGLang package and add an explicit normal-mode v2 opt-in."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil

parser = argparse.ArgumentParser()
parser.add_argument('--source', type=Path, default=Path('/sgl-workspace/sglang/python/sglang'))
parser.add_argument('--destination', type=Path, required=True)
parser.add_argument('--adapter', type=Path, required=True)
args = parser.parse_args()
if args.destination.exists():
    raise SystemExit('Destination must be new; existing installations are never patched in place')
source_module = args.source / 'srt/layers/moe/token_dispatcher/deepep.py'
text = source_module.read_text()
old = '''        if self.deepep_mode.enable_normal():
            self._normal_dispatcher = _DeepEPDispatcherImplNormal(
                async_finish=async_finish,
                **common_kwargs,
            )'''
new = '''        if self.deepep_mode.enable_normal():
            import os
            impl = _DeepEPDispatcherImplNormal
            if os.getenv("SGLANG_CXI_DEEPEP_V2") == "1":
                from .deepep_v2_cxi import DeepEPV2CXINormal
                impl = DeepEPV2CXINormal
            self._normal_dispatcher = impl(
                async_finish=async_finish,
                **common_kwargs,
            )'''
if text.count(old) != 1:
    raise SystemExit('Inspected dispatcher constructor differs; review source before adapting')
# Do not copy modes, ownership, or ACL xattrs across the container boundary.
args.destination.mkdir(parents=True)
for directory, subdirs, files in os.walk(str(args.source), followlinks=False):
    subdirs[:] = [name for name in subdirs if name != '__pycache__']
    relative = Path(directory).relative_to(args.source)
    target = args.destination / relative
    target.mkdir(parents=True, exist_ok=True)
    for name in list(subdirs):
        original = Path(directory) / name
        if original.is_symlink():
            (target / name).symlink_to(os.readlink(str(original)))
            subdirs.remove(name)
    for name in files:
        if name.endswith('.pyc'):
            continue
        original = Path(directory) / name
        if original.is_symlink():
            (target / name).symlink_to(os.readlink(str(original)))
        else:
            shutil.copyfile(str(original), str(target / name))
module = args.destination / 'srt/layers/moe/token_dispatcher/deepep.py'
module.write_text(text.replace(old, new))
adapter = module.with_name('deepep_v2_cxi.py')
shutil.copyfile(str(args.adapter), str(adapter))
manifest = {'source_root': str(args.source), 'destination': str(args.destination),
            'original_dispatcher_sha256': hashlib.sha256(text.encode()).hexdigest(),
            'patched_dispatcher_sha256': hashlib.sha256(module.read_bytes()).hexdigest(),
            'adapter_sha256': hashlib.sha256(adapter.read_bytes()).hexdigest(),
            'enable_environment': 'SGLANG_CXI_DEEPEP_V2=1',
            'qualification': 'not yet runtime validated'}
(args.destination.parent / 'cxi-sglang-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
print(json.dumps(manifest, indent=2))
