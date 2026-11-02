#!/usr/bin/env bash
#SBATCH --account=infra01
#SBATCH --partition=normal
#SBATCH --nodes=2
#SBATCH --ntasks-per-node=1
#SBATCH --gpus-per-node=4
#SBATCH --cpus-per-task=288
#SBATCH --time=00:20:00
#SBATCH --job-name=cxi-p01-control
#SBATCH --output=/iopsstor/scratch/cscs/zyu/deepep-direct-20261026/tenhour/control-%j.log
set -euo pipefail
root=/iopsstor/scratch/cscs/zyu/deepep-direct-20261026
export OUT="$root/tenhour/results/p01-$SLURM_JOB_ID"
export SNAPSHOT="$root/tenhour/sources/p01-$SLURM_JOB_ID"
mkdir -p "$OUT" "$SNAPSHOT"
mkdir -p "$SNAPSHOT/backend"
cp -a "$root/tenhour/backend/include" "$root/tenhour/backend/host" \
  "$root/tenhour/backend/device" "$root/tenhour/backend/tests" \
  "$root/tenhour/backend/tools" "$SNAPSHOT/backend/"
cp "$root"/tools/*.py "$root"/tools/gin_probe.cu "$SNAPSHOT/"
cp "$root/tenhour/tools/control_node.sh" "$SNAPSHOT/"
cp "$root/tenhour/build-logs/control-environment.txt" "$SNAPSHOT/"
scontrol show job "$SLURM_JOB_ID" > "$OUT/slurm.txt"
for tick in $(seq 1 60);do
  [ -f "$root/tenhour/control-build.PASS" ] && break
  [ ! -f "$root/tenhour/control-build.FAIL" ] || exit 2
  sleep 5
done
if [ ! -f "$root/tenhour/control-build.PASS" ];then
  printf 'Control build not ready within 300 seconds\n' > "$OUT/NOT_READY"
  exit 75
fi
cp "$root/tenhour/build-logs/control-binaries.sha256" "$SNAPSHOT/"
export MASTER_ADDR=$(scontrol show hostnames "$SLURM_JOB_NODELIST" | head -n 1)
export MASTER_PORT=$((32000+SLURM_JOB_ID%10000))
timeout --signal=TERM --kill-after=10s 840s srun --kill-on-bad-exit=1 --cpu-bind=none \
  --environment="$root/../deepep-v2-20261022/tools/deepep-v2-cxi.toml" \
  bash "$SNAPSHOT/control_node.sh"
date -u +%FT%TZ > "$OUT/JOB_COMPLETED"
