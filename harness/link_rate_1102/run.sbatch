#!/usr/bin/env bash
#SBATCH --account=infra01
#SBATCH --partition=debug
#SBATCH --nodes=2
#SBATCH --ntasks-per-node=1
#SBATCH --gpus-per-node=4
#SBATCH --time=00:50:00
#SBATCH --job-name=cxi-write-bw
#SBATCH --output=/iopsstor/scratch/cscs/zyu/cxi-write-bw-20261102/job-%j.log
set -uo pipefail
ROOT=/iopsstor/scratch/cscs/zyu/cxi-write-bw-20261102; OUT=$ROOT/job-$SLURM_JOB_ID; mkdir -p "$OUT"
mapfile -t NODES < <(scontrol show hostnames "$SLURM_JOB_NODELIST"); A=${NODES[0]}; B=${NODES[1]}
echo "server=$A client=$B start=$(date -u +%FT%TZ)" | tee "$OUT/nodes.txt"; scontrol show job "$SLURM_JOB_ID" > "$OUT/slurm-job.txt"
for n in $A $B; do srun -N1 -n1 -w "$n" --gpus-per-task=4 bash "$ROOT/inventory.sh" > "$OUT/inventory-$n.txt" 2>&1; done
export USE_SVC=1
run() { local name=$1 port=$2 sargs=$3 cargs=$4
  srun -N1 -n1 -w "$A" --gpus-per-task=4 --cpu-bind=none bash "$ROOT/wrap.sh" server "$port" $sargs > "$OUT/$name.server.txt" 2>&1 & local sp=$!
  sleep 3
  srun -N1 -n1 -w "$B" --gpus-per-task=4 --cpu-bind=none bash "$ROOT/wrap.sh" client "$port" "$A" $cargs > "$OUT/$name.client.txt" 2>&1; local rc=$?
  wait $sp; echo "$(date -u +%T) $name rc=$rc $(grep -m1 -iE 'error|errx|fail|unable|denied' "$OUT/$name.client.txt" | cut -c1-120)"; return $rc; }
# probe: service id handling
if ! run probe-svc 49194 "cxi0" "cxi0 -s 65536 -D 2"; then echo "probe with job service id failed; retrying with default service"; export USE_SVC=0; run probe-default 49195 "cxi0" "cxi0 -s 65536 -D 2"; fi
SIZES="4096 8192 16384 32768 65536 69120 132096 262144 1048576"
for s in $SIZES; do run host-uni-s$s 49200 "cxi0" "cxi0 -s $s -D 5"; done
for s in 65536 132096 1048576; do run host-bi-s$s 49201 "cxi0" "cxi0 -s $s -D 5 -b"; done
for s in $SIZES; do run gpu-uni-s$s 49202 "cxi0 -r 0 -g NVIDIA" "cxi0 -t 0 -g NVIDIA -s $s -D 5"; done
for s in 65536 132096 1048576; do run gpu-bi-s$s 49203 "cxi0 -t 0 -r 0 -g NVIDIA" "cxi0 -t 0 -r 0 -g NVIDIA -s $s -D 5 -b"; done
# 128-byte alignment: 8256-byte writes placed at 64- vs 128-byte alignment, host and GPU memory
for al in 64 128; do for s in 8192 8256 8320; do run host-uni-s$s-align$al 49204 "cxi0" "cxi0 -s $s -D 4 --buf-align=$al"; run gpu-uni-s$s-align$al 49205 "cxi0 -r 0 -g NVIDIA" "cxi0 -t 0 -g NVIDIA -s $s -D 4 --buf-align=$al"; done; done
# issue-rate sensitivity: commands per doorbell
for l in 1 16; do run gpu-uni-s132096-l$l 49206 "cxi0 -r 0 -g NVIDIA" "cxi0 -t 0 -g NVIDIA -s 132096 -D 4 -l $l"; done
# all four rails concurrently (GPU i <-> cxi i), bidirectional, DeepEP-like 132096-byte writes; then host unidirectional 1 MiB
for s in 132096 1048576; do
  pids=(); for i in 0 1 2 3; do srun -N1 -n1 -w "$A" --gpus-per-task=4 --cpu-bind=none bash "$ROOT/wrap.sh" server $((49300+i)) cxi$i -t $i -r $i -g NVIDIA > "$OUT/rails4-gpu-bi-s$s-cxi$i.server.txt" 2>&1 & pids+=($!); done; sleep 4
  for i in 0 1 2 3; do srun -N1 -n1 -w "$B" --gpus-per-task=4 --cpu-bind=none bash "$ROOT/wrap.sh" client $((49300+i)) "$A" cxi$i -t $i -r $i -g NVIDIA -s $s -D 6 -b > "$OUT/rails4-gpu-bi-s$s-cxi$i.client.txt" 2>&1 & pids+=($!); done; wait "${pids[@]}"; echo "$(date -u +%T) rails4-gpu-bi-s$s done"
done
pids=(); for i in 0 1 2 3; do srun -N1 -n1 -w "$A" --gpus-per-task=4 --cpu-bind=none bash "$ROOT/wrap.sh" server $((49310+i)) cxi$i > "$OUT/rails4-host-uni-s1048576-cxi$i.server.txt" 2>&1 & pids+=($!); done; sleep 4
for i in 0 1 2 3; do srun -N1 -n1 -w "$B" --gpus-per-task=4 --cpu-bind=none bash "$ROOT/wrap.sh" client $((49310+i)) "$A" cxi$i -s 1048576 -D 6 > "$OUT/rails4-host-uni-s1048576-cxi$i.client.txt" 2>&1 & pids+=($!); done; wait "${pids[@]}"; echo "$(date -u +%T) rails4-host-uni done"
echo "end=$(date -u +%FT%TZ)" >> "$OUT/nodes.txt"; touch "$OUT/DONE"
