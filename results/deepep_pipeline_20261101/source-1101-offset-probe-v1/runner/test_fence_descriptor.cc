#include <cstring>
#include <libcxi/libcxi.h>
#include "cxi_fence_command.h"
#include <cstdio>
int main() {
  cxi_cmd32 storage[128]{};cxi_cq queue{};
  queue.cmds32=storage;queue.wp32=queue.hw_wp32=queue.rp32=8;queue.size32=128;
  if(cxi_cq_emit_cq_cmd(&queue,C_CMD_CQ_FENCE))return 1;
  uint64_t expected[8];cxi_build_fence_command(expected);
  if(queue.wp32!=10 || memcmp(expected,&storage[8],64))return 2;
  puts("PASS GPU CQ_FENCE descriptor builder matches installed libcxi helper; no NIC semantics tested");
}
