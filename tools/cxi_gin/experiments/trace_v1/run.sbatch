#!/usr/bin/env bash
#SBATCH --account=infra01
#SBATCH --partition=debug
#SBATCH --nodes=2
#SBATCH --ntasks-per-node=1
#SBATCH --gpus-per-node=4
#SBATCH --cpus-per-task=288
#SBATCH --time=00:30:00
#SBATCH --job-name=deepep-ep8-trace
#SBATCH --output=/iopsstor/scratch/cscs/zyu/deepep-direct-20261026/trace-20261028/trace-%j.log
set -euo pipefail
: "${SNAPSHOT:?}"
export OUT="/iopsstor/scratch/cscs/zyu/deepep-direct-20261026/trace-20261028/jobs/$SLURM_JOB_ID"
mkdir -p "$OUT"
export MASTER_ADDR=$(scontrol show hostnames "$SLURM_JOB_NODELIST" | head -n1)
export MASTER_PORT=$((28000+SLURM_JOB_ID%10000))
scontrol show job "$SLURM_JOB_ID" > "$OUT/slurm.txt"
trap 'rc=$?; printf "%s\n" "$rc" > "$OUT/EXIT_CODE"' EXIT
timeout --signal=TERM --kill-after=15s 1650s srun --kill-on-bad-exit=1 --cpu-bind=none \
 --environment=/iopsstor/scratch/cscs/zyu/deepep-v2-20261022/tools/deepep-v2-cxi.toml \
 bash "$SNAPSHOT/trace/node.sh"
# Host Python 3.6 is sufficient for the offline analyzer; CUDA not required.
python3 "$SNAPSHOT/trace/analyze.py" "$OUT/captures/v4flash" "$OUT/analysis/v4flash"
