#!/usr/bin/env bash
#SBATCH --account=infra01
#SBATCH --partition=normal
#SBATCH --nodes=2
#SBATCH --ntasks-per-node=1
#SBATCH --gpus-per-node=4
#SBATCH --cpus-per-task=288
#SBATCH --time=04:00:00
#SBATCH --job-name=deepep-cxi-pipeline
#SBATCH --output=/iopsstor/scratch/cscs/zyu/deepep-pipeline-20261030/job-%j.log
set -euo pipefail
: "${CAMPAIGN:?}" "${INITIAL_SNAPSHOT:?}"
export MASTER_ADDR=$(scontrol show hostnames "$SLURM_JOB_NODELIST" | head -n1)
mkdir -p "$CAMPAIGN/jobs/$SLURM_JOB_ID"
scontrol show job "$SLURM_JOB_ID" > "$CAMPAIGN/jobs/$SLURM_JOB_ID/slurm.txt"
export CXI_KEEP_ALLOCATION=1
python3 "$INITIAL_SNAPSHOT/runner/controller.py"
