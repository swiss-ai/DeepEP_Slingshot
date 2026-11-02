#!/usr/bin/env bash
set -euo pipefail
root=/iopsstor/scratch/cscs/zyu/deepep-direct-20261026/tenhour
export CUDA_HOME=/iopsstor/scratch/cscs/zyu/deepep-direct-20261026/cuda-sdk/usr/local/cuda-13.0
export PATH="$CUDA_HOME/bin:$PATH"
export LD_LIBRARY_PATH="$CUDA_HOME/lib64:${LD_LIBRARY_PATH:-}"
mkdir -p "$root/cxi-build" "$root/build-logs"
exec 9>"$root/cxi-build.lock"
flock -n 9 || exit 3
{
  date -u
  uname -a
  gcc --version
  nvcc --version
  printf 'NCCL base revision: 12df1a11afad322be5a204a2db890161cbf8131d\n'
  printf 'Target: SM90, private CXI source patch, four build workers\n'
} > "$root/build-logs/cxi-environment.txt"
rm -f "$root/cxi-build.FAIL" "$root/cxi-build.PASS"
if make -C "$root/nccl-cxi-src" -j4 src.build \
    CUDA_HOME="$CUDA_HOME" BUILDDIR="$root/cxi-build" \
    NVCC_GENCODE='-gencode=arch=compute_90,code=sm_90' \
    > "$root/build-logs/cxi-build.log" 2>&1; then
  sha256sum "$root/cxi-build/lib/libnccl.so.2.32.3" "$root/cxi-build/include/nccl.h" \
    > "$root/build-logs/cxi-binaries.sha256"
  date -u +%FT%TZ > "$root/cxi-build.PASS"
else
  rc=$?
  printf '%s\n' "$rc" > "$root/cxi-build.FAIL"
  exit "$rc"
fi
