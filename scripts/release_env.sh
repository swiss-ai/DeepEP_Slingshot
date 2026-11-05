# Source this file to select the direct-CXI backend and the release-candidate kernel knobs
# (lean-b transport variant baked into the installed headers, see scripts/apply_patches.sh --variant).
#
#   export NCCL_GIN_PLUGIN=/abs/path/libnccl-gin-cxi.so EP_NCCL_ROOT_DIR=/abs/nccl/prefix
#   source scripts/release_env.sh
#
# Every CXI_EP_* value is a compile-time define injected by backend/tests/nvcc_wrapper.py when DeepEP
# JIT-compiles a kernel; DeepEP's JIT cache does not see them, so EP_JIT_CACHE_DIR must be fresh
# whenever one changes. Values are those of the 2026-11-03 release matrix (job 3835100).
_here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
export NCCL_GIN_TYPE=6 NCCL_GIN_NCONNECTIONS=1 NCCL_ALGO=Ring
export CXI_GIN_BOOTSTRAP_IFNAME=hsn0
export EP_SUPPRESS_NCCL_CHECK=0
export EP_JIT_NVCC_COMPILER="${EP_JIT_NVCC_COMPILER:-$_here/../backend/tests/nvcc_wrapper.py}"
export EP_JIT_CACHE_DIR="${EP_JIT_CACHE_DIR:-/tmp/deepep-jit-$USER-release}"
# transport variant label (recorded in results; the defines themselves live in the installed header)
export CXI_VARIANT=lean-b
# geometry of the qualified configuration
export CXI_EP_SMS=64 CXI_EP_CONTEXTS=129
# packed dispatch rows and packed combine (2026-11-01 qualified knobs)
export CXI_EP_PACK_ROWS=1 CXI_EP_UPDATE_INTERVAL=16 CXI_EP_FIRST_INTERVAL=4 CXI_EP_FORWARD_CHUNK=3 CXI_EP_MERGE_FINAL_TAIL=1
export CXI_EP_PACK_COMBINE=1 CXI_EP_COMBINE_BATCH=16 CXI_EP_COMBINE_FIRST_BATCH=4
# signal-path knobs of the release candidate (2026-11-02)
export CXI_EP_SKIP_COMBINE_FLUSH=1 CXI_EP_LOCAL_SELF_SIGNAL=1
# experimental knobs, off: the early scale-up tail (1 with CXI_EP_COMBINE_FIRST_BATCH=2 is exact and
# 16 us faster at 4K but has no release matrix), split barrier and double-buffered staging (no gain)
export CXI_EP_COMBINE_FIRST_TAIL=0 CXI_EP_COMBINE_SPLIT_BARRIER=0 CXI_EP_COMBINE_DOUBLE_TMA=0
# the pinned DeepEP prints on every call when its debug flag is set; keep it off for timing
export CXI_EP_DEBUG=0
unset _here
