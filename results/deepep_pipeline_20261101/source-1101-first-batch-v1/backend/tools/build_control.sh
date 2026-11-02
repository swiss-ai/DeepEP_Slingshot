#!/usr/bin/env bash
set -euo pipefail
root=/iopsstor/scratch/cscs/zyu/deepep-direct-20261026/tenhour
export CUDA_HOME=/iopsstor/scratch/cscs/zyu/deepep-direct-20261026/cuda-sdk/usr/local/cuda-13.0
export PATH="$CUDA_HOME/bin:$PATH"
export LD_LIBRARY_PATH="$CUDA_HOME/lib64:${LD_LIBRARY_PATH:-}"
mkdir -p "$root/control-build" "$root/build-logs"
exec 9>"$root/control-build.lock"
flock -n 9 || exit 3
{
  date -u
  uname -a
  gcc --version
  nvcc --version
  printf 'NCCL source revision: 12df1a11afad322be5a204a2db890161cbf8131d\n'
  printf 'Target: SM90, unmodified source, four build workers\n'
} > "$root/build-logs/control-environment.txt"
if make -C "$root/nccl-control-src" -j4 src.build \
    CUDA_HOME="$CUDA_HOME" BUILDDIR="$root/control-build" \
    NVCC_GENCODE='-gencode=arch=compute_90,code=sm_90' \
    > "$root/build-logs/control-build.log" 2>&1; then
  sha256sum "$root/control-build/lib/libnccl.so.2.32.3" "$root/control-build/include/nccl.h" \
    > "$root/build-logs/control-binaries.sha256"
  date -u +%FT%TZ > "$root/control-build.PASS"
else
  rc=$?
  printf '%s\n' "$rc" > "$root/control-build.FAIL"
  exit "$rc"
fi
