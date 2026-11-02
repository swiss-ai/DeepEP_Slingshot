#!/usr/bin/env bash
#SBATCH --account=infra01
#SBATCH --partition=debug
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=1
#SBATCH --gpus-per-node=4
#SBATCH --cpus-per-task=32
#SBATCH --time=00:15:00
#SBATCH --job-name=cxi-ki-build
#SBATCH --output=/iopsstor/scratch/cscs/zyu/cxi-gin-20261025/build-%j.log
set -euo pipefail
: "${CXI_KI_PREFIX:?Supply a matching KI-enabled libfabric installation}"
campaign=/iopsstor/scratch/cscs/zyu/cxi-gin-20261025
mkdir -p "$campaign/builds"
srun --kill-on-bad-exit=1 \
    --environment=/iopsstor/scratch/cscs/zyu/deepep-v2-20261022/tools/deepep-v2-cxi.toml \
    bash "$campaign/tools/build.sh" "$campaign/builds/job-$SLURM_JOB_ID"
