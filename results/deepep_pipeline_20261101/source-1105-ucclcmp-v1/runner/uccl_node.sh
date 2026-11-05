#!/usr/bin/env bash
# UCCL-EP (native CPU proxy over libfabric/CXI) side of the EP8 comparison. Same benchmark, inputs and
# metric as the direct-GIN gates (backend/tests/ep_benchmark.py); the transport is the Swiss AI reference
# build 54ef064 of 2026-10-28 (job 3783795), untouched.
set -euo pipefail
ulimit -c 0
: "${SNAPSHOT:?}" "${OUT:?}" "${MASTER_ADDR:?}" "${MASTER_PORT:?}"
source /iopsstor/scratch/cscs/zyu/uccl-ep-20261023/tools/runtime.sh
unset NCCL_GIN_TYPE NCCL_GIN_PLUGIN EP_NCCL_ROOT_DIR LD_PRELOAD EP_JIT_NVCC_COMPILER
build=/iopsstor/scratch/cscs/zyu/uccl-ep8-live-20261028/builds/apertus-54ef064-v1
base="$OUT/uccl/node$SLURM_PROCID"; work="$OUT/uccl/work"
mkdir -p "$base" "$work"
printf 'UCCL gate: inventory\n' > "$OUT/node$SLURM_PROCID.STAGE" 2>/dev/null || true
{
  date -u +%FT%TZ; hostname; uname -r
  nvidia-smi --query-gpu=name,uuid,driver_version,pci.bus_id --format=csv
  sha256sum "$build/python/uccl/"ep*.so /host_usr/lib64/libcxi.so "$DEPS/lf-install/lib/libfabric.so"* 2>/dev/null || true
  python -c 'import torch,sys;print("torch",torch.__version__,"python",sys.version)'
} > "$base/node-inventory.txt" 2>&1
# Provenance for the benchmark's source_metadata: the extracted reference tree plus its pinned commit.
if [ "$SLURM_PROCID" = 0 ]; then
  ln -sfn "$build/source" "$work/source"
  printf '%s\n' '{"sources": {"UCCL": {"sha": "54ef06429dde1c2debd3dbfb565530020650f7fd", "repository": "https://github.com/swiss-ai/uccl", "build": "/iopsstor/scratch/cscs/zyu/uccl-ep8-live-20261028/builds/apertus-54ef064-v1", "extension_sha256": "dcce642bedc055ab8cf5a9a4297eb297f236e23b12980f19f33aeaeb857d874c"}}}' > "$work/source-manifest.json"
fi
for i in $(seq 1 60); do [ -f "$work/source-manifest.json" ] && [ -e "$work/source" ] && break; sleep 1; done
grep -q "dcce642bedc055ab8cf5a9a4297eb297f236e23b12980f19f33aeaeb857d874c" "$base/node-inventory.txt" || { printf 'UCCL extension hash differs from the qualified reference build\n' >&2; exit 2; }
export UCCL_WORK="$work"
export PYTHONPATH="$SNAPSHOT/backend/tests:$build/python:$build/source/ep/bench"
export UCCL_EP_TRANSPORT=cxi
export EP_JIT_CACHE_DIR="$base/jit"; mkdir -p "$EP_JIT_CACHE_DIR"
read -r -a models <<< "${CXI_EP_MODELS:-v4flash}"
read -r -a tokens <<< "${CXI_EP_TOKENS:-4096}"
read -r -a dtypes <<< "${CXI_EP_DTYPES:-fp8}"
read -r -a routing <<< "${CXI_EP_ROUTING:-mixed}"
read -r -a seeds <<< "${CXI_EP_SEEDS:-1}"
export MASTER_PORT=$((MASTER_PORT+2))
printf 'UCCL gate: benchmark\n' > "$OUT/node$SLURM_PROCID.STAGE" 2>/dev/null || true
if timeout --signal=TERM --kill-after=10s "${CXI_TEST_TIMEOUT:-300}s" python -m torch.distributed.run \
  --nnodes=2 --nproc_per_node=4 --node_rank="$SLURM_PROCID" \
  --master_addr="$MASTER_ADDR" --master_port="$MASTER_PORT" "$SNAPSHOT/backend/tests/ep_benchmark.py" \
  --backend uccl --output "$OUT/uccl/ep" \
  --models "${models[@]}" --tokens "${tokens[@]}" --dtypes "${dtypes[@]}" --routing "${routing[@]}" --seeds "${seeds[@]}" \
  --warmup "${CXI_EP_WARMUP:-20}" --iters "${CXI_EP_ITERS:-100}" --nic-iters "${CXI_EP_NIC_ITERS:-0}" --profile-steps 0 \
  --sms 24 --nvl-chunk 32 --rdma-chunk 32 \
  --combine-nvl-chunk 4 --combine-rdma-chunk 32 \
  > "$base/benchmark.log" 2>&1; then rc=0; else rc=$?; fi
[ "$rc" = 0 ] || exit "$rc"
date -u +%FT%TZ > "$base/PASS"
