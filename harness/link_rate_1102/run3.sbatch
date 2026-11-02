#!/usr/bin/env bash
#SBATCH --account=infra01
#SBATCH --partition=debug
#SBATCH --nodes=2
#SBATCH --ntasks-per-node=1
#SBATCH --gpus-per-node=4
#SBATCH --time=00:15:00
#SBATCH --job-name=cxi-write-bw-3
#SBATCH --output=/iopsstor/scratch/cscs/zyu/cxi-write-bw-20261102/job-%j.log
# Third pass: (a) replica of the GPU-issued offset probe's PUT lengths with CPU-issued commands
# from GPU memory, (b) doorbell batch of 8 (the transport's batch) on one queue, (c) four rails
# concurrently with --overlap so the server steps are not serialized by GPU exclusivity.
set -uo pipefail
ROOT=/iopsstor/scratch/cscs/zyu/cxi-write-bw-20261102; OUT=$ROOT/job-$SLURM_JOB_ID; mkdir -p "$OUT"
mapfile -t NODES < <(scontrol show hostnames "$SLURM_JOB_NODELIST"); A=${NODES[0]}; B=${NODES[1]}
echo "server=$A client=$B start=$(date -u +%FT%TZ)" | tee "$OUT/nodes.txt"; scontrol show job "$SLURM_JOB_ID" > "$OUT/slurm-job.txt"
for n in $A $B; do srun -N1 -n1 -w "$n" --overlap bash "$ROOT/inventory.sh" > "$OUT/inventory-$n.txt" 2>&1; done
export LD_LIBRARY_PATH="$ROOT/cudart:${LD_LIBRARY_PATH:-}"; export USE_SVC=1
SR="srun -N1 -n1 --overlap --cpu-bind=none"
run() { local name=$1 port=$2 sargs=$3 cargs=$4
  $SR -w "$A" stdbuf -oL -eL bash "$ROOT/wrap.sh" server "$port" $sargs > "$OUT/$name.server.txt" 2>&1 & local sp=$!
  sleep 2
  $SR -w "$B" stdbuf -oL -eL bash "$ROOT/wrap.sh" client "$port" "$A" $cargs > "$OUT/$name.client.txt" 2>&1; local rc=$?
  wait $sp; echo "$(date -u +%T) $name rc=$rc $(grep -m1 -iE 'error|errx|fail|unable|denied' "$OUT/$name.client.txt" | cut -c1-120)"; return $rc; }
G="-g NVIDIA"
# (a) exact PUT lengths of the 11/02 offset probe (rows x row bytes), GPU memory both ends, writes placed
#     back to back (--buf-align=64) so writes alternate between 0 and 64 (or 32) bytes off a 128-byte line,
#     and at 128-byte placement as the aligned control.
for s in 60480 64800 69120 107328 115584 123840 132096; do
  run gpu-uni-s$s-align64 49400 "cxi0 -r 0 $G" "cxi0 -t 0 $G -s $s -D 4 --buf-align=64"
  run gpu-uni-s$s-align128 49401 "cxi0 -r 0 $G" "cxi0 -t 0 $G -s $s -D 4 --buf-align=128"
done
run gpu-uni-s64800-align32 49402 "cxi0 -r 0 $G" "cxi0 -t 0 $G -s 64800 -D 4 --buf-align=32"
for s in 60480 123840; do run host-uni-s$s-align64 49403 "cxi0" "cxi0 -s $s -D 4 --buf-align=64"; done
# (b) doorbell batch of 8 on one queue (the transport's CXI_TX_BATCH_LIMIT), DeepEP PUT sizes
for s in 69120 132096; do run gpu-uni-s$s-l8 49404 "cxi0 -r 0 $G" "cxi0 -t 0 $G -s $s -D 4 -l 8"; done
# (c) four rails concurrently (GPU i <-> cxi i), steps overlap on the node
rails() { local name=$1 base=$2 sargs=$3 cargs=$4; local pids=()
  for i in 0 1 2 3; do $SR -w "$A" stdbuf -oL -eL bash "$ROOT/wrap.sh" server $((base+i)) cxi$i $(eval echo "$sargs") > "$OUT/$name-cxi$i.server.txt" 2>&1 & pids+=($!); done
  sleep 3
  for i in 0 1 2 3; do $SR -w "$B" stdbuf -oL -eL bash "$ROOT/wrap.sh" client $((base+i)) "$A" cxi$i $(eval echo "$cargs") > "$OUT/$name-cxi$i.client.txt" 2>&1 & pids+=($!); done
  wait "${pids[@]}"; echo "$(date -u +%T) $name done: $(for i in 0 1 2 3; do grep -m1 '# attempts' "$OUT/$name-cxi$i.client.txt" | tr -d '#\n'; echo -n ' |'; done)"; }
rails rails4-gpu-bi-s132096 49500 '-t $i -r $i -g NVIDIA' '-t $i -r $i -g NVIDIA -s 132096 -D 5 -b'
rails rails4-gpu-bi-s1048576 49510 '-t $i -r $i -g NVIDIA' '-t $i -r $i -g NVIDIA -s 1048576 -D 5 -b'
rails rails4-host-uni-s1048576 49520 '' '-s 1048576 -D 5'
rails rails4-host-bi-s132096 49530 '' '-s 132096 -D 5 -b'
rails rails4-gpu-uni-s132096 49540 '-r $i -g NVIDIA' '-t $i -g NVIDIA -s 132096 -D 5'
echo "end=$(date -u +%FT%TZ)" >> "$OUT/nodes.txt"; touch "$OUT/DONE"
