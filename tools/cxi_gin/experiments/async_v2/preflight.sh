#!/usr/bin/env bash
set -euo pipefail
: "${CAMPAIGN:?}" "${INITIAL_SNAPSHOT:?}"
src="$INITIAL_SNAPSHOT"
sdk=/iopsstor/scratch/cscs/zyu/deepep-direct-20261026/cuda-sdk/usr/local/cuda-13.0
out="$CAMPAIGN/preflight/$(basename "$src")"
mkdir -p "$out"
g++ -std=c++17 -O2 -Wall -Wextra -Werror -I"$src/backend/device" "$src/runner/test_queue_credit.cc" -o "$out/queue-test"
"$out/queue-test"
g++ -std=c++17 -Wall -Wextra -Werror -Wno-misleading-indentation \
 -I"$sdk/include" -I"$src/backend/include" -c "$src/backend/host/cxi_resources.cc" -o "$out/resources.o"
for variant in baseline async cap1 cap2 cap4 cap8 threshold threshold-cap4 baseline-trace async-trace cap4-trace threshold-trace; do
  prefix="$CAMPAIGN/runtime/$(basename "$src")/$variant"
  flags=()
  if [[ "$variant" = *-trace ]];then flags=(-DEP_TRACE_PTR=4096ULL);fi
  for name in gin_smoke gin_producer_stress device_compile_probe; do
    "$sdk/bin/nvcc" -std=c++17 -arch=sm_90 "${flags[@]}" -I"$prefix/include" \
      -c "$src/backend/tests/$name.cu" -o "$out/$variant-$name.o"
  done
done
for limit in 0 1 2 4 8; do
  "$sdk/bin/nvcc" -std=c++17 -arch=sm_90 -DCXI_TX_PENDING_LIMIT="$limit" -DCXI_CT_THRESHOLD_FLUSH=1 \
    -I"$src/backend/include" -I"$src/backend/device" -c "$src/runner/burst_probe.cu" -o "$out/burst-$limit.o"
done
date -Is > "$out/PASS"
