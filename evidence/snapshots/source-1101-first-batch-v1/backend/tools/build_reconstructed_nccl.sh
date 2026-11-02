#!/usr/bin/env bash
# Rebuild the exported pinned NCCL patch into a new private prefix.
set -euo pipefail
if [ "$#" != 3 ];then
  printf 'Usage: %s BUNDLE NEW_OUTPUT_DIR CUDA_HOME\n' "$0" >&2
  exit 2
fi
bundle=$(realpath "$1")
output=$(realpath -m "$2")
export CUDA_HOME=$(realpath "$3")
[ ! -e "$output" ] || { printf 'Output must be new: %s\n' "$output" >&2;exit 2; }
[ -x "$CUDA_HOME/bin/nvcc" ]
python3 "$bundle/backend/tools/verify_rebuild_inputs.py" "$bundle" --components nccl
mkdir -p "$output/source" "$output/build" "$output/logs"
trap 'rc=$?; if [ "$rc" != 0 ];then printf "%s\n" "$rc" > "$output/FAIL"; fi' EXIT
export PATH="$CUDA_HOME/bin:$PATH"
export LD_LIBRARY_PATH="$CUDA_HOME/lib64:${LD_LIBRARY_PATH:-}"
{
  date -u +%FT%TZ
  uname -a
  gcc --version
  nvcc --version
  sha256sum "$bundle/nccl-base.tar" "$bundle/nccl.patch" "$bundle/source-manifest.json"
} > "$output/logs/inputs.txt"
tar -xf "$bundle/nccl-base.tar" -C "$output/source"
git -C "$output/source" apply --check "$bundle/nccl.patch"
git -C "$output/source" apply "$bundle/nccl.patch"
# Verify source hashes from the independently checked local patch bundle.
python3 - "$bundle" "$output/source" <<'PY'
import hashlib,json,sys
from pathlib import Path
bundle,source=map(Path,sys.argv[1:])
data=json.loads((bundle/'source-manifest.json').read_text())['repositories']['nccl']
assert data['baseline_commit']=='12df1a11afad322be5a204a2db890161cbf8131d'
assert hashlib.sha256((bundle/'nccl.patch').read_bytes()).hexdigest()==data['patch_sha256']
for name,expected in data['changed_files_sha256'].items():
    path=source/name
    actual=hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None
    assert actual==expected, name
print('Pinned patch/source reconstruction verified')
PY
make -C "$output/source" -j4 src.build \
  CUDA_HOME="$CUDA_HOME" BUILDDIR="$output/build" \
  NVCC_GENCODE='-gencode=arch=compute_90,code=sm_90' \
  > "$output/logs/build.log" 2>&1
sha256sum "$output/build/lib/libnccl.so.2.32.3" "$output/build/include/nccl.h" \
  > "$output/logs/binaries.sha256"
date -u +%FT%TZ > "$output/PASS"
