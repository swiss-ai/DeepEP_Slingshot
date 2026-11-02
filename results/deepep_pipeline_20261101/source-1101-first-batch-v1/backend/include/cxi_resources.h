#pragma once
#include "cxi_gin_abi.h"

struct CxiResources;
struct CxiMemory;
struct CxiChannel;

// Exceptions are caught at the plugin/API boundary. Destructors log failures;
// explicit close calls return nonzero if resource teardown fails.
CxiResources* cxi_resources_open(int gpu, int nic_index);
int cxi_resources_close(CxiResources*);
CxiMemory* cxi_memory_register(CxiResources*, void* pointer, size_t bytes,
                             bool device, int supplied_fd = -1, size_t fd_offset = 0);
CxiPeerAddress cxi_memory_peer(CxiMemory*);
void cxi_memory_local(CxiMemory*, CxiWindow*);
int cxi_memory_close(CxiMemory*);
CxiChannel* cxi_channel_open(CxiResources*, unsigned queue_depth);
CxiGpuContext cxi_channel_descriptor(CxiChannel*);
int cxi_channel_close(CxiChannel*, const CxiGpuContext* final_state = nullptr);
// Return a quiesced, healthy channel to this LNI's pool. Hardware CT values
// and GPU queue cursors must be preserved together across device contexts.
int cxi_channel_recycle(CxiChannel*, const CxiGpuContext* final_state);
void cxi_resources_report(CxiResources*, const char* phase);
int cxi_resources_errors(CxiResources*);

uint64_t cxi_channel_error(CxiChannel*);
