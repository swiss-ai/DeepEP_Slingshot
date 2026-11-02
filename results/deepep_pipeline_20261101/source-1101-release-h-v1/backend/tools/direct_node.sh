#!/usr/bin/env bash
set -euo pipefail
ulimit -c 0
export EP_SUPPRESS_NCCL_CHECK=0
source /iopsstor/scratch/cscs/zyu/deepep-v2-20261022/tools/runtime_cxi.sh
root=/iopsstor/scratch/cscs/zyu/deepep-direct-20261026
src="$SNAPSHOT/backend"
transport="${CXI_TRANSPORT:-direct}"
case "$transport" in
  direct) ;;
  proxy) [[ "${CXI_TEST_KIND:-smoke}" = ep || "${CXI_TEST_KIND:-smoke}" = sglang ]] || { printf 'Proxy control requires EP or SGLang test\n' >&2;exit 2; };;
  *) printf 'Unknown CXI_TRANSPORT\n' >&2;exit 2;;
esac
base="$OUT/$transport/node$SLURM_PROCID"
mkdir -p "$base"
{
  date -u +%FT%TZ
  hostname
  uname -r
  nvidia-smi --query-gpu=name,uuid,driver_version,pci.bus_id --format=csv
  for file in /sys/module/cxi_core/version /sys/module/cxi_ss1/version /host_usr/lib64/pkgconfig/libcxi.pc;do
    if [ -r "$file" ];then printf '\n%s\n' "$file";cat "$file";fi
  done
  sha256sum /host_usr/lib64/libcxi.so
} > "$base/node-inventory.txt" 2>&1
export EP_NCCL_ROOT_DIR="${CXI_NCCL_PREFIX:-$root/tenhour/releases/cxi-20261026-201823}"
nccl_source="${CXI_NCCL_SOURCE:-$root/tenhour/nccl-cxi-src}"
if [ ! -r "$EP_NCCL_ROOT_DIR/lib/libnccl.so.2.32.3" ] || [ ! -r "$EP_NCCL_ROOT_DIR/include/nccl_device.h" ];then
  printf 'Modified NCCL build not ready; no direct test attempted\n' > "$base/NOT_READY"
  exit 75
fi
export LD_LIBRARY_PATH="$EP_NCCL_ROOT_DIR/lib:$LD_LIBRARY_PATH"
export LD_PRELOAD="$EP_NCCL_ROOT_DIR/lib/libnccl.so.2"
helpers="$src/tests"
if [ ! -f "$helpers/common.py" ];then
  helpers="$SNAPSHOT"
  [ -f "$helpers/common.py" ] || helpers=$(dirname "$SNAPSHOT")
fi
[ -f "$helpers/common.py" ]
ep_source="${CXI_DEEPEP_SOURCE:-$root/DeepEP-portable}"
export PYTHONPATH="$helpers:$ep_source"
overlay="$OUT/nccl-overlay-direct-node$SLURM_PROCID"
mkdir -p "$overlay/nvidia/nccl/lib"
ln -s "$EP_NCCL_ROOT_DIR/lib/libnccl.so.2.32.3" "$overlay/nvidia/nccl/lib/libnccl.so.2"
export PYTHONPATH="$overlay:$PYTHONPATH"
export EP_JIT_CACHE_DIR="${CXI_LOCAL_JIT_DIR:-$OUT/jit/node$SLURM_PROCID}"
export NCCL_GIN_TYPE=6 NCCL_GIN_NCONNECTIONS=1 NCCL_ALGO=Ring NCCL_DEBUG=INFO
export CXI_GIN_BOOTSTRAP_IFNAME=hsn0
mkdir -p "$EP_JIT_CACHE_DIR"
g++ -std=c++17 -fPIC -shared -Wall -Wextra -Werror -Wno-misleading-indentation \
  -I"$src/include" -I"$EP_NCCL_ROOT_DIR/include" \
  -I"$nccl_source/src/include" -I"$nccl_source/src/include/plugin" \
  -I/usr/local/cuda/include -idirafter /host_usr/include \
  "$src/host/cxi_resources.cc" "$src/host/cxi_bootstrap.cc" "$src/host/gin_plugin.cc" \
  /host_usr/lib64/libcxi.so -L/usr/local/cuda/lib64 -lcudart -ldl -pthread \
  -o "$base/libnccl-gin-cxi.so"
export NCCL_GIN_PLUGIN="$base/libnccl-gin-cxi.so"
if [ "$transport" = proxy ];then
  export NCCL_GIN_TYPE=2
  unset NCCL_GIN_PLUGIN
fi
case "${CXI_TEST_KIND:-smoke}" in
  smoke) test_source=gin_smoke.cu;;
  producer) test_source=gin_producer_stress.cu;;
  bad_offset) test_source=gin_bad_offset.cu;;
  bounds) test_source=gin_bounds.cu;;
  ep|sglang) test_source=;;
  *) printf 'Unknown CXI_TEST_KIND\n' >&2;exit 2;;
esac
if [ -n "$test_source" ];then
nvcc -std=c++17 -shared -Xcompiler=-fPIC -arch=sm_90 \
  -I"$EP_NCCL_ROOT_DIR/include" "$src/tests/$test_source" \
  -L"$EP_NCCL_ROOT_DIR/lib" -lnccl -ldl -o "$base/gin_smoke.so"
sha256sum "$base/gin_smoke.so" > "$base/test-binary.sha256"
fi
sha256sum "$base/libnccl-gin-cxi.so" "$EP_NCCL_ROOT_DIR/lib/libnccl.so.2.32.3" > "$base/binaries.sha256"
# Device-header experiments can share the same host library/ABI. Preserve the
# actual installed header identities as well as the runtime library hash.
sha256sum "$EP_NCCL_ROOT_DIR/include/nccl_device/gin/cxi/"*.h \
  "$EP_NCCL_ROOT_DIR/include/nccl_device/gin/cxi/"*.cuh > "$base/device-headers.sha256"
export EP_JIT_NVCC_COMPILER="$helpers/nvcc_wrapper.py"
if [ "${CXI_DEVICE_TRACE:-0}" = 1 ]; then
  nvcc -std=c++17 -shared -Xcompiler=-fPIC -arch=sm_90 "$helpers/stamp.cu" -o "$base/stamp.so"
  export EP_TRACE_STAMP_SO="$base/stamp.so"
fi
export CASE_OUT="$OUT/$transport/smoke" SMOKE_SO="$base/gin_smoke.so"
export MASTER_PORT=$((MASTER_PORT+2))
test_args=("$src/tests/gin_smoke.py")
case "${CXI_TEST_KIND:-smoke}" in
  ep|sglang)
    # The pinned C++ dispatch prints on every call when debug is enabled.
    if [ "${CXI_EP_DEBUG:-1}" = 0 ];then
      unset EP_BUFFER_DEBUG
    else
      export EP_BUFFER_DEBUG=1
    fi
    ;;
esac
if [ "${CXI_TEST_KIND:-smoke}" = ep ];then
  export DEEPEP_SOURCE="$ep_source"
  read -r -a models <<< "${CXI_EP_MODELS:-v4flash}"
  read -r -a tokens <<< "${CXI_EP_TOKENS:-32}"
  read -r -a dtypes <<< "${CXI_EP_DTYPES:-bf16}"
  read -r -a routing <<< "${CXI_EP_ROUTING:-mixed}"
  read -r -a seeds <<< "${CXI_EP_SEEDS:-1}"
  test_args=("$src/tests/ep_benchmark.py" --backend deepep --output "$OUT/$transport/ep"
    --models "${models[@]}" --tokens "${tokens[@]}" --dtypes "${dtypes[@]}"
    --routing "${routing[@]}" --seeds "${seeds[@]}" --warmup "${CXI_EP_WARMUP:-2}"
    --iters "${CXI_EP_ITERS:-5}" --nic-iters "${CXI_EP_NIC_ITERS:-0}"
    --profile-steps "${CXI_EP_PROFILE_STEPS:-0}")
elif [ "${CXI_TEST_KIND:-smoke}" = sglang ];then
  sgl_overlay="$base/sglang-overlay"
  python "$src/tools/prepare_sglang_overlay.py" --destination "$sgl_overlay/sglang" \
    --adapter "$src/sglang/deepep_v2_cxi.py" > "$base/sglang-overlay.json"
  export PYTHONPATH="$sgl_overlay:$PYTHONPATH" SGLANG_CXI_DEEPEP_V2=1 SGLANG_ENABLE_JIT_DEEPGEMM=1
  if [ "$transport" = proxy ];then
    export SGLANG_CXI_DEEPEP_V2_ALLOW_PROXY_CONTROL=1
  else
    unset SGLANG_CXI_DEEPEP_V2_ALLOW_PROXY_CONTROL
  fi
  # Compile the actual tested expert shapes on demand, rather than the image's
  # default sweep over 128 unused token shapes on every rank. Kernels remain JIT.
  export SGLANG_JIT_DEEPGEMM_PRECOMPILE=0
  export SGLANG_DG_CACHE_DIR="$root/tenhour/deepgemm-$SLURM_JOB_ID/node$SLURM_PROCID"
  export SGLANG_CXI_DEEPEP_V2_SMS="${CXI_EP_SMS:-64}" SGLANG_CXI_DEEPEP_V2_CONTEXTS="${CXI_EP_CONTEXTS:-129}"
  if [ "${CXI_LOCAL_JIT:-0}" = 1 ]; then
    export SGLANG_DG_CACHE_DIR="$EP_JIT_CACHE_DIR/sglang-deepgemm"
  fi
  if [ "${CXI_LOCAL_RESULTS:-0}" = 1 ]; then
    sglang_shared_results="$CASE_OUT"
    export CASE_OUT=$(mktemp -d "/dev/shm/deepep-sglang-${SLURM_JOB_ID}-n${SLURM_PROCID}-XXXXXX")
    printf '%s\n' "$CASE_OUT" > "$base/local-sglang-results-path.txt"
  fi
  test_args=("$src/tests/sglang_dispatcher_smoke.py")
fi
if [ "${CXI_LOCAL_JIT:-0}" = 1 ]; then
  # Triton dlopens compiled .so files, so its cache must not live on a noexec mount (/dev/shm is
  # noexec inside the container). Use the container-local /tmp when it allows exec; otherwise keep
  # Triton's default cache location.
  tcache="/tmp/deepep-triton-${SLURM_JOB_ID}-n${SLURM_PROCID}"; mkdir -p "$tcache"
  tmount=$(stat -c %m "$tcache" 2>/dev/null || echo /)
  if awk -v m="$tmount" '$2==m {print $4}' /proc/mounts | grep -q noexec; then
    rm -rf "$tcache"; tcache=""
  fi
  if [ -n "$tcache" ]; then export TRITON_CACHE_DIR="$tcache"; fi
  printf '%s\n' "${TRITON_CACHE_DIR:-default}" > "$base/triton-cache-path.txt"
fi
runtime_log="$base/smoke.log"
if [ "${CXI_LOCAL_LOGS:-0}" = 1 ]; then
  runtime_log=$(mktemp "/dev/shm/deepep-log-${SLURM_JOB_ID}-n${SLURM_PROCID}-XXXXXX")
  printf '%s\n' "$runtime_log" > "$base/local-log-path.txt"
fi
if timeout --signal=TERM --kill-after=10s "${CXI_TEST_TIMEOUT:-180}s" python -m torch.distributed.run \
  --nnodes=2 --nproc_per_node=4 --node_rank="$SLURM_PROCID" \
  --master_addr="$MASTER_ADDR" --master_port="$MASTER_PORT" "${test_args[@]}" \
  > "$runtime_log" 2>&1; then test_rc=0; else test_rc=$?; fi
if [ "${CXI_LOCAL_LOGS:-0}" = 1 ]; then
  # GPU work is over before persistence; a failed copy preserves the local log.
  cp --no-preserve=all "$runtime_log" "$base/smoke.log"
  rm -- "$runtime_log"
fi
if [ -n "${sglang_shared_results:-}" ]; then
  # Persist only after torchrun exits. Failed tests retain their error records;
  # failed persistence leaves the complete local directory available to debug.
  mkdir -p "$sglang_shared_results"
  cp -r --no-preserve=all "$CASE_OUT/." "$sglang_shared_results/"
  rm -rf -- "$CASE_OUT"
fi
if [ "$test_rc" != 0 ]; then exit "$test_rc"; fi
date -u +%FT%TZ > "$base/PASS"
