#!/usr/bin/env bash
# Reconstruct/build independently on each allocated node, then run the EP gate.
set -euo pipefail
source /iopsstor/scratch/cscs/zyu/deepep-v2-20261022/tools/runtime_cxi.sh
: "${CXI_NCCL_PREFIX:?Select the reconstructed NCCL prefix}"
: "${CXI_NCCL_SOURCE:?Select its matching internal source}"
clean="$OUT/rebuild-node$SLURM_PROCID"
bash "$SNAPSHOT/backend/tools/build_reconstructed_deepep.sh" "$SNAPSHOT" "$clean" "$CXI_NCCL_PREFIX"
export CXI_DEEPEP_SOURCE="$clean/source"
bash "$SNAPSHOT/backend/tools/direct_node.sh"
