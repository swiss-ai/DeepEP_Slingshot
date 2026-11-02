#!/usr/bin/env bash
set -euo pipefail
ulimit -c 0
export EP_SUPPRESS_NCCL_CHECK=0
source /iopsstor/scratch/cscs/zyu/deepep-v2-20261022/tools/runtime_cxi.sh
root=/iopsstor/scratch/cscs/zyu/deepep-direct-20261026
export EP_NCCL_ROOT_DIR="$root/tenhour/control-build"
export LD_LIBRARY_PATH="$EP_NCCL_ROOT_DIR/lib:$LD_LIBRARY_PATH"
export LD_PRELOAD="$EP_NCCL_ROOT_DIR/lib/libnccl.so.2${LD_PRELOAD:+:$LD_PRELOAD}"
export PYTHONPATH="$SNAPSHOT:$root/DeepEP-portable"
export DEEPEP_SOURCE="$root/DeepEP-portable"
overlay="$OUT/nccl-overlay-control-node$SLURM_PROCID"
mkdir -p "$overlay/nvidia/nccl/lib"
ln -s "$EP_NCCL_ROOT_DIR/lib/libnccl.so.2.32.3" "$overlay/nvidia/nccl/lib/libnccl.so.2"
export PYTHONPATH="$overlay:$PYTHONPATH"
export EP_JIT_CACHE_DIR="$root/tenhour/jit-control-$SLURM_JOB_ID/node$SLURM_PROCID"
export EP_BUFFER_DEBUG=1 NCCL_DEBUG=INFO NCCL_GIN_TYPE=2
mkdir -p "$OUT/node$SLURM_PROCID" "$EP_JIT_CACHE_DIR"
python - <<'PY' > "$OUT/node$SLURM_PROCID/inventory.json"
import os,sys,json,hashlib,importlib.util
from pathlib import Path
import torch,deep_ep
spec=importlib.util.find_spec('sglang')
data=dict(hostname=os.uname().nodename,python=sys.version,torch=torch.__version__,
 cuda=torch.version.cuda,nccl=torch.cuda.nccl.version(),deep_ep=deep_ep.__file__,
 sglang_origin=spec.origin if spec else None,nccl_root=os.environ['EP_NCCL_ROOT_DIR'])
dest=Path(os.environ['OUT'])/('node'+os.environ['SLURM_PROCID'])
if spec and spec.submodule_search_locations:
 root=Path(next(iter(spec.submodule_search_locations)))
 files=list(root.rglob('*deepep*.py'))
 data['sglang_deepep_files']=[str(p) for p in files]
 for p in files:
  target=dest/'sglang-source'/p.relative_to(root)
  target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(p.read_bytes())
data['launcher_cpu_affinity']=sorted(os.sched_getaffinity(0))
data['loaded_nccl']=[l for l in Path('/proc/self/maps').read_text().splitlines() if 'libnccl' in l]
print(json.dumps(data,indent=2))
PY
nvcc -std=c++17 -shared -Xcompiler=-fPIC -arch=sm_90 \
  -I"$EP_NCCL_ROOT_DIR/include" "$SNAPSHOT/gin_probe.cu" \
  -L"$EP_NCCL_ROOT_DIR/lib" -lnccl -o "$OUT/node$SLURM_PROCID/gin_probe.so"
export MODE=proxy PROBE_SO="$OUT/node$SLURM_PROCID/gin_probe.so" CASE_OUT="$OUT/proxy"
timeout --signal=TERM --kill-after=10s 150s python -m torch.distributed.run \
  --nnodes=2 --nproc_per_node=4 --node_rank="$SLURM_PROCID" \
  --master_addr="$MASTER_ADDR" --master_port="$MASTER_PORT" "$SNAPSHOT/probe.py" \
  > "$OUT/node$SLURM_PROCID/proxy.log" 2>&1
export MASTER_PORT=$((MASTER_PORT+1))
timeout --signal=TERM --kill-after=10s 240s python -m torch.distributed.run \
  --nnodes=2 --nproc_per_node=4 --node_rank="$SLURM_PROCID" \
  --master_addr="$MASTER_ADDR" --master_port="$MASTER_PORT" "$SNAPSHOT/benchmark.py" \
  --backend deepep --output "$OUT/portable" --models v4flash --tokens 4096 \
  --seeds 1 --dtypes fp8 --routing mixed --warmup 2 --iters 5 \
  --nic-iters 0 --profile-steps 0 > "$OUT/node$SLURM_PROCID/portable.log" 2>&1
date -u +%FT%TZ > "$OUT/node$SLURM_PROCID/PASS"
# This node script is snapshotted when the allocation starts, including for
# already-submitted control jobs. Preserve a separate immutable dynamic source.
dynsnap="$SNAPSHOT/dynamic-node$SLURM_PROCID"
mkdir -p "$dynsnap/backend"
cp -R --no-preserve=mode,ownership "$root/tenhour/backend/include" "$root/tenhour/backend/host" \
  "$root/tenhour/backend/device" "$root/tenhour/backend/tests" \
  "$root/tenhour/backend/tools" "$dynsnap/backend/"
SNAPSHOT="$dynsnap" bash "$dynsnap/backend/tools/dynamic_node.sh"
# Only run direct GIN after the separate unmodified-NCCL and raw dynamic gates.
if [ -f "$root/tenhour/cxi-build.PASS" ];then
  SNAPSHOT="$dynsnap" bash "$dynsnap/backend/tools/direct_node.sh"
fi
