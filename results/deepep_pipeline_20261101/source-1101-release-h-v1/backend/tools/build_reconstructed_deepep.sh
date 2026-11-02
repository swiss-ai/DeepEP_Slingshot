#!/usr/bin/env bash
# Run inside the pinned CUDA container on an allocated node; no pip installation.
set -euo pipefail
[ "$#" = 3 ] || { printf 'Usage: %s BUNDLE NEW_OUTPUT_DIR NCCL_PREFIX\n' "$0" >&2; exit 2; }
bundle=$(realpath "$1")
output=$(realpath -m "$2")
export EP_NCCL_ROOT_DIR=$(realpath "$3")
[ ! -e "$output" ] || { printf 'Output must be new\n' >&2; exit 2; }
[ -r "$EP_NCCL_ROOT_DIR/lib/libnccl.so.2.32.3" ]
python3 "$bundle/backend/tools/verify_rebuild_inputs.py" "$bundle" --components DeepEP fmt
mkdir -p "$output/source" "$output/logs"
trap 'rc=$?; if [ "$rc" != 0 ]; then printf "%s\n" "$rc" > "$output/FAIL"; fi' EXIT
tar -xf "$bundle/DeepEP-base.tar" -C "$output/source"
mkdir -p "$output/source/third-party/fmt"
tar -xf "$bundle/fmt-base.tar" -C "$output/source/third-party/fmt"
git -C "$output/source" apply --check "$bundle/DeepEP.patch"
git -C "$output/source" apply "$bundle/DeepEP.patch"
python3 - "$bundle" "$output/source" <<'PY'
import hashlib,json,sys
from pathlib import Path
bundle,source=map(Path,sys.argv[1:])
m=json.loads((bundle/'source-manifest.json').read_text())['repositories']['DeepEP']
assert hashlib.sha256((bundle/'DeepEP.patch').read_bytes()).hexdigest()==m['patch_sha256']
for name,expected in m['changed_files_sha256'].items():
    p=source/name
    assert (hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None)==expected,name
PY
export CUDA_HOME=/usr/local/cuda
export PATH="$CUDA_HOME/bin:$PATH"
export EP_NVSHMEM_ROOT_DIR=/usr/local/lib/python3.12/dist-packages/nvidia/nvshmem
export LD_PRELOAD="$EP_NCCL_ROOT_DIR/lib/libnccl.so.2"
export LD_LIBRARY_PATH="$EP_NCCL_ROOT_DIR/lib:$EP_NVSHMEM_ROOT_DIR/lib:${LD_LIBRARY_PATH:-}"
# The pinned setup.py uses -l:libnccl.so without adding its directory to -L.
export LIBRARY_PATH="$EP_NCCL_ROOT_DIR/lib:${LIBRARY_PATH:-}"
export MAX_JOBS=4 TORCH_CUDA_ARCH_LIST=9.0 EP_SUPPRESS_NCCL_CHECK=0
export EP_JIT_CACHE_DIR="$output/jit"
mkdir -p "$output/overlay/nvidia/nccl/lib"
ln -s "$EP_NCCL_ROOT_DIR/lib/libnccl.so.2.32.3" "$output/overlay/nvidia/nccl/lib/libnccl.so.2"
export PYTHONPATH="$output/overlay:$output/source"
{
  date -u +%FT%TZ
  python --version
  nvcc --version
  sha256sum "$EP_NCCL_ROOT_DIR/lib/libnccl.so.2.32.3" "$bundle/rebuild-inputs.json" "$bundle/DeepEP.patch"
} > "$output/logs/inputs.txt" 2>&1
cd "$output/source"
# Leave time inside the enclosing 900-second gate for import and EP8 execution.
timeout --signal=TERM --kill-after=15s 600s python setup.py build_ext --inplace \
  > "$output/logs/build.log" 2>&1
python - "$output" <<'PY'
import hashlib,json,sys
from pathlib import Path
import deep_ep
import deep_ep._C
out=Path(sys.argv[1]); binary=Path(deep_ep._C.__file__)
assert binary.is_relative_to(out/'source'),binary
record={'deep_ep':deep_ep.__file__,'extension':str(binary),
        'extension_sha256':hashlib.sha256(binary.read_bytes()).hexdigest(),
        'scope':'clean native build/import only; GPU correctness requires subsequent GIN and EP8 gates'}
(out/'build-import.json').write_text(json.dumps(record,indent=2)+'\n')
(out/'logs/libraries.txt').write_text(Path('/proc/self/maps').read_text())
PY
date -u +%FT%TZ > "$output/PASS"
