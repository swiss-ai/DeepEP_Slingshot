#!/usr/bin/env bash
set -euo pipefail
ulimit -c 0
source /iopsstor/scratch/cscs/zyu/deepep-v2-20261022/tools/runtime_cxi.sh
base="$OUT/dynamic/node$SLURM_PROCID"
src="$SNAPSHOT/backend"
mkdir -p "$base" "$OUT/dynamic/exchange"
g++ -std=c++17 -Wall -Wextra -Werror -Wno-misleading-indentation \
  -idirafter /host_usr/include -I/usr/local/cuda/include -I"$src/include" \
  -c "$src/host/cxi_resources.cc" -o "$base/resources.o"
nvcc -std=c++17 -arch=sm_90 -I"$src/include" -I"$src/device" \
  -c "$src/tests/cxi_dynamic_probe.cu" -o "$base/device.o"
nvcc "$base/resources.o" "$base/device.o" /host_usr/lib64/libcxi.so -ldl -o "$base/probe"
pids=()
for gpu in 0 1 2 3;do
  timeout --signal=TERM --kill-after=5s 120s "$base/probe" "$gpu" "$SLURM_PROCID" "$OUT/dynamic/exchange" \
    > "$base/gpu$gpu.log" 2>&1 &
  pids+=("$!")
done
failed=0
for gpu in 0 1 2 3;do
  if wait "${pids[$gpu]}";then rc=0;else rc=$?;failed=1;fi
  printf '%s\t%s\n' "$gpu" "$rc" >> "$base/status.tsv"
done
exit "$failed"
