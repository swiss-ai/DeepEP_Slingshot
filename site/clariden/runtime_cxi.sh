#!/usr/bin/env bash
set -euo pipefail
source /iopsstor/scratch/cscs/zyu/deepep-v2-20261022/tools/runtime.sh
export LD_LIBRARY_PATH="$DEEPEP_WORK/ofi-install/lib:$DEEPEP_WORK/lf-install/lib:$DEEPEP_WORK/json-install/lib:$DEEPEP_WORK/host-deps/lib:$LD_LIBRARY_PATH"
export NCCL_NET_PLUGIN=ofi NCCL_GIN_TYPE=2 OFI_NCCL_PROTOCOL=RDMA
export FI_PROVIDER=cxi FI_CXI_ENABLE_WRITEDATA=1
export FI_MR_CACHE_MONITOR=userfaultfd FI_CXI_DISABLE_HOST_REGISTER=1
export FI_CXI_DEFAULT_CQ_SIZE=131072 FI_CXI_DEFAULT_TX_SIZE=2048
export NCCL_CROSS_NIC=1 NCCL_NET_GDR_LEVEL=PHB
export NCCL_SOCKET_IFNAME=hsn0 GLOO_SOCKET_IFNAME=hsn0
export EP_DISABLE_GIN=0
unset NCCL_IB_DISABLE
