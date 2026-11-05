#pragma once
#include <stdint.h>
#include <stddef.h>

// Private experimental ABI. Not an upstream NCCL backend identifier.
#define CXI_GIN_ABI_VERSION 3
#define CXI_GIN_DEVICE_VERSION 1
#define CXI_GIN_BACKEND_TYPE 6
#define CXI_GIN_MAX_PEERS 64
#define CXI_GIN_MAX_CHUNK (1u << 20)

struct CxiPeerAddress {
  uint32_t nid, pid, pid_bits, dfa;
  uint32_t index_ext;
  uint32_t reserved;
};

struct CxiWindow {
  uint32_t abi_version, peers;
  uint64_t bytes, local_iova, local_pointer;
  uint32_t local_lac, reserved;
  CxiPeerAddress peer[CXI_GIN_MAX_PEERS];
};

// Mutable queue state belongs to the GPU. The host copies it only after kernels
// quiesce. Each logical context initially owns a physical TX CQ and CT-read CQ.
struct alignas(64) CxiGpuContext {
  uint32_t abi_version, lock;
  uint64_t* tx_queue;
  uint64_t* tx_doorbell;
  uint64_t* ct_queue;
  uint64_t* ct_doorbell;
  uint64_t* ct_writeback;
  uint32_t tx_wp32, tx_size32, ct_wp32, ct_size32;
  uint32_t ct_id, eq_id;
  uint64_t posted, completed;
  uint64_t* signals;
  uint64_t* counters;
  CxiWindow* signal_window;
  uint32_t nsignals, ncounters;
  uint64_t signal_offset;
  uint64_t* diagnostic;  // mapped host memory; GPU writes, host only observes
  uint32_t tx_unpublished; // descriptors reserved/written but not yet doorbelled
  // Lean signal bookkeeping (device-owned; constants in cxi_primitives.cuh): bit 0 a transfer that
  // must precede the next signal was posted since the last CQ fence, bit 1 the newest ring entry is
  // the still-unpublished pending payload PUT, bits 8..16 cached CSTATE key. Host sets it to 1.
  uint32_t lean_state;
  uint64_t tx_doorbells, tx_commands; // cumulative diagnostics, updated under lock
  CxiWindow* pending_dst;
  uint64_t pending_local_addr, pending_remote_offset;
  uint32_t pending_lac, pending_peer;
  // pending_* and lean_state live inside the previous trailing padding; sizeof stays 192 bytes.
};

static_assert(sizeof(CxiPeerAddress) == 24, "peer ABI");
static_assert(offsetof(CxiGpuContext, posted) % 8 == 0, "counter alignment");
static_assert(alignof(CxiGpuContext) == 64, "context alignment");

static_assert(sizeof(CxiGpuContext) == 192, "context host/device ABI size");
static_assert(sizeof(CxiWindow) == 1576, "window host/device ABI size");
