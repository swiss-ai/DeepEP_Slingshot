#!/usr/bin/env bash
# Build the NCCL GIN host plugin (libnccl-gin-cxi.so) from backend/host. This is the compile
# command of backend/tools/direct_node.sh with its paths as parameters; it runs inside the
# Clariden container where the host's libcxi is visible under /host_usr (site/clariden/).
#
#   scripts/build_plugin.sh NCCL_PREFIX NCCL_SOURCE OUTPUT.so
#
#   NCCL_PREFIX  built NCCL (include/nccl_device.h, lib/libnccl.so.2.32.3) with the cxi headers
#   NCCL_SOURCE  the patched NCCL source tree (plugin-internal headers under src/include)
#   environment  CUDA_HOME (/usr/local/cuda), LIBCXI (/host_usr/lib64/libcxi.so),
#                LIBCXI_INCLUDE (/host_usr/include), CXX (g++), BACKEND (<repo>/backend)
set -euo pipefail
[ $# -eq 3 ] || { sed -n '2,12p' "$0" >&2; exit 2; }
here=$(cd "$(dirname "$0")" && pwd)
backend=${BACKEND:-$(dirname "$here")/backend}
prefix=$(realpath "$1"); source=$(realpath "$2"); out=$3
cuda=${CUDA_HOME:-/usr/local/cuda}; libcxi=${LIBCXI:-/host_usr/lib64/libcxi.so}; libcxi_inc=${LIBCXI_INCLUDE:-/host_usr/include}
for f in "$prefix/include/nccl_device.h" "$prefix/lib/libnccl.so.2.32.3" "$source/src/include/plugin" "$libcxi" "$backend/host/gin_plugin.cc"; do
  [ -e "$f" ] || { printf 'missing: %s\n' "$f" >&2; exit 2; }
done
mkdir -p "$(dirname "$out")"
"${CXX:-g++}" -std=c++17 -fPIC -shared -Wall -Wextra -Werror -Wno-misleading-indentation \
  -I"$backend/include" -I"$prefix/include" \
  -I"$source/src/include" -I"$source/src/include/plugin" \
  -I"$cuda/include" -idirafter "$libcxi_inc" \
  "$backend/host/cxi_resources.cc" "$backend/host/cxi_bootstrap.cc" "$backend/host/gin_plugin.cc" \
  "$libcxi" -L"$cuda/lib64" -lcudart -ldl -pthread \
  -o "$out"
sha256sum "$out"
