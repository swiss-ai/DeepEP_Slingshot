#!/usr/bin/env bash
set -euo pipefail
ulimit -c 0
source /iopsstor/scratch/cscs/zyu/deepep-v2-20261022/tools/runtime_cxi.sh
: "${SNAPSHOT:?}" "${OUT:?}"
base=/iopsstor/scratch/cscs/zyu/deepep-direct-20261026
work="$OUT/build-node$SLURM_PROCID"
mkdir -p "$work"
printf 'verify snapshot\n' > "$work/STAGE"
python - "$SNAPSHOT" <<'PY'
import hashlib,json,sys
from pathlib import Path
p=Path(sys.argv[1]);m=json.loads((p/'manifest.json').read_text())
for n,h in m['files'].items():assert hashlib.sha256((p/n).read_bytes()).hexdigest()==h,n
print('Snapshot hashes PASS',len(m['files']))
PY
# Control uses the recorded, unchanged native extension and original headers.
export CXI_TEST_KIND=ep CXI_EP_MODELS=v4flash CXI_EP_TOKENS=4096 CXI_EP_DTYPES=fp8 CXI_EP_ROUTING=uniform
export CXI_EP_DEBUG=0 CXI_EP_WARMUP=10 CXI_EP_ITERS=50 CXI_EP_NIC_ITERS=0 CXI_EP_PROFILE_STEPS=0
export CXI_TEST_TIMEOUT=240
unset EP_JIT_NVCC_COMPILER EP_TRACE_DEVICE_PTR
printf 'original uninstrumented control\n' > "$work/STAGE"
parent_out="$OUT";export OUT="$parent_out/original-control"
bash "$SNAPSHOT/backend/tools/direct_node.sh"
export OUT="$parent_out"
mkdir -p "$work/source" "$work/runtime"
printf 'copy header contents without source ACLs\n' > "$work/STAGE"
python "$SNAPSHOT/trace/copy_headers.py" \
 "$base/tenhour/releases/cxi-20261026-201823/include" "$work/runtime/include"
ln -s "$base/tenhour/releases/cxi-20261026-201823/lib" "$work/runtime/lib"
cp "$SNAPSHOT/trace-headers/"* "$work/runtime/include/nccl_device/gin/cxi/"
tar -xzf "$SNAPSHOT/DeepEP-instrumented.tar.gz" -C "$work/source"
export EP_NCCL_ROOT_DIR="$work/runtime" CXI_NCCL_PREFIX="$work/runtime"
export CUDA_HOME=/usr/local/cuda EP_NVSHMEM_ROOT_DIR=/usr/local/lib/python3.12/dist-packages/nvidia/nvshmem
export LD_PRELOAD="$EP_NCCL_ROOT_DIR/lib/libnccl.so.2"
export LD_LIBRARY_PATH="$EP_NCCL_ROOT_DIR/lib:$EP_NVSHMEM_ROOT_DIR/lib:${LD_LIBRARY_PATH:-}"
export LIBRARY_PATH="$EP_NCCL_ROOT_DIR/lib:${LIBRARY_PATH:-}"
export MAX_JOBS=4 TORCH_CUDA_ARCH_LIST=9.0 EP_SUPPRESS_NCCL_CHECK=0
export EP_JIT_CACHE_DIR="$work/jit-build"
mkdir -p "$work/overlay/nvidia/nccl/lib"
ln -s "$EP_NCCL_ROOT_DIR/lib/libnccl.so.2.32.3" "$work/overlay/nvidia/nccl/lib/libnccl.so.2"
export PYTHONPATH="$work/overlay:$work/source:$SNAPSHOT/backend/tests"
cd "$work/source"
printf 'build instrumented native extension\n' > "$work/STAGE"
timeout --signal=TERM --kill-after=10s 600s python setup.py build_ext --inplace > "$work/build.log" 2>&1
python -c 'import deep_ep._C; assert hasattr(deep_ep._C,"_ep_trace_host_enable");print(deep_ep._C.__file__)' > "$work/import.txt"
nvcc -std=c++17 -arch=sm_90 -shared -Xcompiler=-fPIC "$SNAPSHOT/trace/stamp.cu" -o "$work/stamp.so"
export EP_TRACE_STAMP_SO="$work/stamp.so"
src="$SNAPSHOT/backend"
g++ -std=c++17 -fPIC -shared -Wall -Wextra -Werror -Wno-misleading-indentation \
 -I"$src/include" -I"$EP_NCCL_ROOT_DIR/include" \
 -I"$base/tenhour/nccl-cxi-src/src/include" -I"$base/tenhour/nccl-cxi-src/src/include/plugin" \
 -I/usr/local/cuda/include -idirafter /host_usr/include \
 "$src/host/cxi_resources.cc" "$src/host/cxi_bootstrap.cc" "$src/host/gin_plugin.cc" \
 /host_usr/lib64/libcxi.so -L/usr/local/cuda/lib64 -lcudart -ldl -pthread -o "$work/libnccl-gin-cxi.so"
export NCCL_GIN_PLUGIN="$work/libnccl-gin-cxi.so" NCCL_GIN_TYPE=6 NCCL_GIN_NCONNECTIONS=1 NCCL_ALGO=Ring NCCL_DEBUG=INFO
export CXI_GIN_BOOTSTRAP_IFNAME=hsn0 CXI_EP_CONTEXTS=129
unset EP_BUFFER_DEBUG
nvidia-smi topo -m > "$work/topology.txt"
sha256sum "$work/source/deep_ep/"*.so "$work/libnccl-gin-cxi.so" "$EP_NCCL_ROOT_DIR/lib/libnccl.so.2.32.3" > "$work/binaries.sha256"
# Single model first: all eight ranks, three full captures, same input/route seed.
export EP_JIT_CACHE_DIR="$work/jit-capture"
printf 'eight-rank capture and correctness\n' > "$work/STAGE"
timeout --signal=TERM --kill-after=10s 720s python -m torch.distributed.run \
 --nnodes=2 --nproc_per_node=4 --node_rank="$SLURM_PROCID" \
 --master_addr="$MASTER_ADDR" --master_port="$((MASTER_PORT+40))" \
 "$SNAPSHOT/trace/capture.py" --output "$OUT/captures" --model v4flash --captures 3 --nic-iters 600 \
 > "$work/capture.log" 2>&1
date -u +%FT%TZ > "$work/PASS"
printf 'capture passed; offline analysis next\n' > "$work/STAGE"
