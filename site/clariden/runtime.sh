#!/usr/bin/env bash
set -euo pipefail
export DEEPEP_WORK=/iopsstor/scratch/cscs/zyu/deepep-v2-20261022
source "$DEEPEP_WORK/venv-ep8/bin/activate"
export EP_NCCL_ROOT_DIR="$DEEPEP_WORK/venv-ep8/lib/python3.12/site-packages/nvidia/nccl"
export EP_NVSHMEM_ROOT_DIR=/usr/local/lib/python3.12/dist-packages/nvidia/nvshmem
export LD_LIBRARY_PATH="$EP_NCCL_ROOT_DIR/lib:$EP_NVSHMEM_ROOT_DIR/lib:${LD_LIBRARY_PATH:-}"
export PYTHONPATH="$DEEPEP_WORK/DeepEP-ep8"
export PYTHONNOUSERSITE=1 PYTHONUNBUFFERED=1 OMP_NUM_THREADS=1
export EP_JIT_CACHE_DIR="$DEEPEP_WORK/jit-${SLURM_JOB_ID}/${SLURMD_NODENAME}"
mkdir -p "$EP_JIT_CACHE_DIR"
