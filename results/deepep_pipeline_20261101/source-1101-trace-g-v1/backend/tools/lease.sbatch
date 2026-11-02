#!/usr/bin/env bash
#SBATCH --account=infra01
#SBATCH --partition=normal
#SBATCH --nodes=2
#SBATCH --ntasks-per-node=1
#SBATCH --gpus-per-node=4
#SBATCH --cpus-per-task=288
#SBATCH --time=01:00:00
#SBATCH --job-name=cxi-gin-debug
#SBATCH --output=/iopsstor/scratch/cscs/zyu/deepep-direct-20261026/tenhour/lease-%j.log
set -euo pipefail
root=/iopsstor/scratch/cscs/zyu/deepep-direct-20261026/tenhour
export LEASE_ROOT="$root/leases/$SLURM_JOB_ID"
export MASTER_ADDR=$(scontrol show hostnames "$SLURM_JOB_NODELIST" | head -n 1)
export MASTER_PORT=$((32000+SLURM_JOB_ID%10000))
mkdir -p "$LEASE_ROOT/requests" "$LEASE_ROOT/results"
scontrol show job "$SLURM_JOB_ID" > "$LEASE_ROOT/slurm.txt"
cp "$root/tools/lease_driver.py" "$LEASE_ROOT/lease_driver.py"
cp "$root/tools/validate_gate.py" "$LEASE_ROOT/validate_gate.py"
cp "$root/tools/allocation_time.py" "$LEASE_ROOT/allocation_time.py"
python3 "$LEASE_ROOT/lease_driver.py"
