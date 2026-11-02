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
for variant in marker-zero; do
  prefix="$CAMPAIGN/runtime/$(basename "$src")/$variant"
  flags=()
  if [[ "$variant" = *-trace ]];then flags=(-DEP_TRACE_PTR=4096ULL);fi
  for name in gin_smoke gin_producer_stress device_compile_probe; do
    "$sdk/bin/nvcc" -std=c++17 -arch=sm_90 "${flags[@]}" -I"$prefix/include" \
      -c "$src/backend/tests/$name.cu" -o "$out/$variant-$name.o"
  done
done
for limit in 0 1; do
for hw_fence in 0 1; do
for zero in 0 1; do
  "$sdk/bin/nvcc" -std=c++17 -arch=sm_90 -DCXI_ZERO_DELIVERY_MARKER="$zero" -DCXI_HW_SIGNAL_FENCE="$hw_fence" -DCXI_TX_BATCH_LIMIT=8 -DCXI_BATCH_DELIVERY="$limit" -DCXI_CT_THRESHOLD_FLUSH=1 \
    -I"$src/backend/include" -I"$src/backend/device" -c "$src/runner/burst_probe.cu" -o "$out/burst-$limit-fence$hw_fence-zero$zero.o"
  "$sdk/bin/nvcc" -std=c++17 -arch=sm_90 -DCXI_ZERO_DELIVERY_MARKER="$zero" -DCXI_HW_SIGNAL_FENCE="$hw_fence" -DCXI_TX_BATCH_LIMIT=8 -DCXI_BATCH_DELIVERY="$limit" -DCXI_CT_THRESHOLD_FLUSH=1 \
    -I"$src/backend/include" -I"$src/backend/device" -c "$src/runner/offset_probe.cu" -o "$out/offset-$limit-fence$hw_fence-zero$zero.o"
done
done
g++ -std=c++17 -Wall -Wextra -Werror -I"$src/backend/device"   "$src/runner/test_fence_descriptor.cc" -o "$out/fence-descriptor"
"$out/fence-descriptor"
done
g++ -std=c++17 -O2 -Wall -Wextra -Werror -I"$src/runner" "$src/runner/test_packed_rows.cc" -o "$out/packed-model"
"$out/packed-model"
g++ -std=c++17 -O2 -Wall -Wextra -Werror -I"$src/runner" "$src/runner/test_packed_combine.cc" -o "$out/packed-combine-model"
"$out/packed-combine-model"
date -Is > "$out/TRANSPORT_PREFLIGHT_PASS"
# Actual EP8 templates require preflight_packed_rows.py with the transport parent.

