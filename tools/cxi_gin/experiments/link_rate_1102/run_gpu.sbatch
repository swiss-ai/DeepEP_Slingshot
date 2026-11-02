#!/usr/bin/env bash
#SBATCH --account=infra01
#SBATCH --partition=debug
#SBATCH --nodes=2
#SBATCH --ntasks-per-node=1
#SBATCH --gpus-per-node=4
#SBATCH --time=00:20:00
#SBATCH --job-name=cxi-write-bw-gpu
#SBATCH --output=/iopsstor/scratch/cscs/zyu/cxi-write-bw-20261102/job-%j.log
# Second pass: GPU-memory cases (host-side cxi_write_bw with the container's CUDA runtime copied
# to scratch), the four-rail cases with client connect-retry, and two host controls.
set -uo pipefail
ROOT=/iopsstor/scratch/cscs/zyu/cxi-write-bw-20261102; OUT=$ROOT/job-$SLURM_JOB_ID; mkdir -p "$OUT"
EDF=/iopsstor/scratch/cscs/zyu/deepep-pipeline-20261030/container.toml
mapfile -t NODES < <(scontrol show hostnames "$SLURM_JOB_NODELIST"); A=${NODES[0]}; B=${NODES[1]}
echo "server=$A client=$B start=$(date -u +%FT%TZ)" | tee "$OUT/nodes.txt"; scontrol show job "$SLURM_JOB_ID" > "$OUT/slurm-job.txt"
for n in $A $B; do srun -N1 -n1 -w "$n" --gpus-per-task=4 bash "$ROOT/inventory.sh" > "$OUT/inventory-$n.txt" 2>&1; done
# 1. CUDA runtime for the bare-node tool: copy libcudart out of the harness container image.
mkdir -p "$ROOT/cudart"
srun -N1 -n1 -w "$A" --environment="$EDF" bash -c 'set -e; f=$(find /usr/local/cuda* /usr/lib /usr/local/lib -name "libcudart.so.1[0-9]*" -type f 2>/dev/null | head -1); echo "container libcudart: $f"; cp -f "$f" '"$ROOT"'/cudart/; cd '"$ROOT"'/cudart && ln -sfn "$(basename "$f")" libcudart.so && ls -la' > "$OUT/cudart-export.txt" 2>&1
cat "$OUT/cudart-export.txt"
export LD_LIBRARY_PATH="$ROOT/cudart:${LD_LIBRARY_PATH:-}"
srun -N1 -n1 -w "$B" --gpus-per-task=4 bash -c 'ldd '"$ROOT"'/cudart/libcudart.so | grep -iE "not found|libcuda" ; echo "ldd done"; nvidia-smi -L | head -4; for i in 0 1 2 3; do echo "gpu$i numa=$(cat /sys/bus/pci/devices/$(nvidia-smi --query-gpu=pci.bus_id --format=csv,noheader -i $i | tr A-F a-f | sed "s/^0000//")/numa_node 2>/dev/null)"; done' > "$OUT/cudart-check.txt" 2>&1
cat "$OUT/cudart-check.txt"
export USE_SVC=1
run() { local name=$1 port=$2 sargs=$3 cargs=$4
  srun -N1 -n1 -w "$A" --gpus-per-task=4 --cpu-bind=none bash "$ROOT/wrap.sh" server "$port" $sargs > "$OUT/$name.server.txt" 2>&1 & local sp=$!
  sleep 2
  srun -N1 -n1 -w "$B" --gpus-per-task=4 --cpu-bind=none bash "$ROOT/wrap.sh" client "$port" "$A" $cargs > "$OUT/$name.client.txt" 2>&1; local rc=$?
  wait $sp; echo "$(date -u +%T) $name rc=$rc $(grep -m1 -iE 'error|errx|fail|unable|denied' "$OUT/$name.client.txt" | cut -c1-120)"; return $rc; }
# host controls on this node pair
run host-uni-s132096 49200 "cxi0" "cxi0 -s 132096 -D 4"
run host-bi-s132096 49201 "cxi0" "cxi0 -s 132096 -D 4 -b"
# GPU memory, one rail (GPU 0 <-> cxi0)
G="-g NVIDIA"
for s in 16384 65536 69120 132096 262144 1048576; do run gpu-uni-s$s 49202 "cxi0 -r 0 $G" "cxi0 -t 0 $G -s $s -D 4"; done
for s in 65536 132096 1048576; do run gpu-bi-s$s 49203 "cxi0 -t 0 -r 0 $G" "cxi0 -t 0 -r 0 $G -s $s -D 4 -b"; done
# 128-byte alignment from GPU memory: 8192/8256/8320-byte writes at 64- vs 128-byte placement
for al in 64 128; do for s in 8192 8256 8320; do run gpu-uni-s$s-align$al 49205 "cxi0 -r 0 $G" "cxi0 -t 0 $G -s $s -D 4 --buf-align=$al"; done; done
# doorbell batching sensitivity from GPU memory
for l in 1 16; do run gpu-uni-s132096-l$l 49206 "cxi0 -r 0 $G" "cxi0 -t 0 $G -s 132096 -D 4 -l $l"; done
# all four rails concurrently (GPU i <-> cxi i): GPU bidirectional at the DeepEP PUT size and 1 MiB, host unidirectional 1 MiB
rails() { local name=$1 base=$2 sargs=$3 cargs=$4; local pids=()
  for i in 0 1 2 3; do srun -N1 -n1 -w "$A" --gpus-per-task=4 --cpu-bind=none bash "$ROOT/wrap.sh" server $((base+i)) cxi$i $(eval echo "$sargs") > "$OUT/$name-cxi$i.server.txt" 2>&1 & pids+=($!); done
  sleep 3
  for i in 0 1 2 3; do srun -N1 -n1 -w "$B" --gpus-per-task=4 --cpu-bind=none bash "$ROOT/wrap.sh" client $((base+i)) "$A" cxi$i $(eval echo "$cargs") > "$OUT/$name-cxi$i.client.txt" 2>&1 & pids+=($!); done
  wait "${pids[@]}"; echo "$(date -u +%T) $name done: $(for i in 0 1 2 3; do grep -m1 '# attempts' "$OUT/$name-cxi$i.client.txt" | tr -d '#\n'; echo -n ' |'; done)"; }
rails rails4-gpu-bi-s132096 49300 '-t $i -r $i -g NVIDIA' '-t $i -r $i -g NVIDIA -s 132096 -D 5 -b'
rails rails4-gpu-bi-s1048576 49310 '-t $i -r $i -g NVIDIA' '-t $i -r $i -g NVIDIA -s 1048576 -D 5 -b'
rails rails4-host-uni-s1048576 49320 '' '-s 1048576 -D 5'
rails rails4-host-bi-s132096 49330 '' '-s 132096 -D 5 -b'
echo "end=$(date -u +%FT%TZ)" >> "$OUT/nodes.txt"; touch "$OUT/DONE"
