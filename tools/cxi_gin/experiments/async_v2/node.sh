#!/usr/bin/env bash
set -euo pipefail
ulimit -c 0
: "${CAMPAIGN:?}" "${SNAPSHOT:?}" "${OUT:?}" "${CXI_VARIANT:?}"
source /iopsstor/scratch/cscs/zyu/deepep-v2-20261022/tools/runtime_cxi.sh
export EP_NCCL_ROOT_DIR="$CAMPAIGN/runtime/$(basename "$SNAPSHOT")/$CXI_VARIANT"
export CXI_NCCL_PREFIX="$EP_NCCL_ROOT_DIR"
export CXI_NCCL_SOURCE=/iopsstor/scratch/cscs/zyu/deepep-direct-20261026/tenhour/nccl-cxi-src
export CUDA_HOME=/usr/local/cuda
export EP_NVSHMEM_ROOT_DIR=/usr/local/lib/python3.12/dist-packages/nvidia/nvshmem
export LD_PRELOAD="$EP_NCCL_ROOT_DIR/lib/libnccl.so.2"
export LD_LIBRARY_PATH="$EP_NCCL_ROOT_DIR/lib:$EP_NVSHMEM_ROOT_DIR/lib:${LD_LIBRARY_PATH:-}"
export LIBRARY_PATH="$EP_NCCL_ROOT_DIR/lib:${LIBRARY_PATH:-}"
export MAX_JOBS=4 TORCH_CUDA_ARCH_LIST=9.0 EP_SUPPRESS_NCCL_CHECK=0
mkdir -p "$OUT/node$SLURM_PROCID"
stage="$OUT/node$SLURM_PROCID/STAGE"
printf 'verify snapshot and runtime\n' > "$stage"
python "$SNAPSHOT/runner/verify.py" "$SNAPSHOT" "$EP_NCCL_ROOT_DIR"
if [ "${CXI_TEST_KIND:-smoke}" = burst ]; then
  mapfile -t variant_flags < <(python - "$SNAPSHOT/variants.json" "$CXI_VARIANT" <<'FLAGS'
import json,sys
for k,v in json.load(open(sys.argv[1]))[sys.argv[2]].items():print('-D%s=%s'%(k,v))
FLAGS
  )
  base="$OUT/dynamic/node$SLURM_PROCID"
  mkdir -p "$base" "$OUT/dynamic/exchange"
  g++ -std=c++17 -Wall -Wextra -Werror -Wno-misleading-indentation -idirafter /host_usr/include \
    -I/usr/local/cuda/include -I"$SNAPSHOT/backend/include" \
    -c "$SNAPSHOT/backend/host/cxi_resources.cc" -o "$base/resources.o"
  nvcc -std=c++17 -arch=sm_90 "${variant_flags[@]}" -I"$SNAPSHOT/backend/include" -I"$SNAPSHOT/backend/device" \
    -c "$SNAPSHOT/runner/burst_probe.cu" -o "$base/device.o"
  nvcc "$base/resources.o" "$base/device.o" /host_usr/lib64/libcxi.so -ldl -o "$base/probe"
  printf 'burst queue-wrap/source-reuse probe\n' > "$stage"
  pids=()
  for gpu in 0 1 2 3; do
    timeout --signal=TERM --kill-after=10s 240s "$base/probe" "$gpu" "$SLURM_PROCID" "$OUT/dynamic/exchange" > "$base/gpu$gpu.log" 2>&1 &
    pids+=("$!")
  done
  failed=0
  for gpu in 0 1 2 3; do
    if wait "${pids[$gpu]}"; then rc=0; else rc=$?; failed=1; fi
    printf '%s\t%s\n' "$gpu" "$rc" >> "$base/status.tsv"
  done
  exit "$failed"
fi
build="$CAMPAIGN/jobs/$SLURM_JOB_ID/builds/$(basename "$SNAPSHOT")/$CXI_VARIANT/node$SLURM_PROCID"
if [ ! -f "$build/PASS" ]; then
  # Every failed build is rebuilt from a clean private source directory.
  if [ -e "$build" ]; then mv "$build" "$build.failed.$(date +%s)"; fi
  mkdir -p "$build/source" "$build/overlay/nvidia/nccl/lib"
  archive=DeepEP.tar.gz
  if [ "${CXI_DEVICE_TRACE:-0}" = 1 ]; then archive=DeepEP-trace.tar.gz; fi
  tar -xzf "$SNAPSHOT/$archive" -C "$build/source"
  ln -s "$EP_NCCL_ROOT_DIR/lib/libnccl.so.2.32.3" "$build/overlay/nvidia/nccl/lib/libnccl.so.2"
  export PYTHONPATH="$build/overlay:$build/source"
  printf 'clean DeepEP native build: %s\n' "$CXI_VARIANT" > "$stage"
  (cd "$build/source"; timeout --signal=TERM --kill-after=15s 900s python setup.py build_ext --inplace > "$build/build.log" 2>&1)
  python - "$build" <<'PY'
import hashlib,json,sys
from pathlib import Path
import deep_ep,deep_ep._C
p=Path(sys.argv[1]); b=Path(deep_ep._C.__file__)
assert b.is_relative_to(p/'source'), b
(p/'build.json').write_text(json.dumps({'extension':str(b),'sha256':hashlib.sha256(b.read_bytes()).hexdigest()}))
(p/'PASS').write_text('clean build/import PASS; GPU validation is separate\n')
PY
fi
export CXI_DEEPEP_SOURCE="$build/source"
export EP_JIT_CACHE_DIR="$OUT/jit/node$SLURM_PROCID"
printf 'GPU test %s: %s\n' "$CXI_VARIANT" "$CXI_TEST_KIND" > "$stage"
bash "$SNAPSHOT/backend/tools/direct_node.sh"
mkdir -p "$OUT/compiler-reports/node$SLURM_PROCID"
find "$EP_JIT_CACHE_DIR" -path '*/compiler-reports/*.txt' -exec cp {} "$OUT/compiler-reports/node$SLURM_PROCID/" \;
printf 'GPU test completed\n'  > "$stage"
