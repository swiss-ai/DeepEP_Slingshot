#pragma once
#include <cstddef>
#include <cstdint>
#include <vector>

struct CxiBootstrapHandle {
  uint64_t magic, cookie;
  uint32_t address;
  uint16_t port, reserved;
};
struct CxiListener {int fd=-1, device=-1; CxiBootstrapHandle handle{};};
CxiListener* cxi_listen(int device);
void cxi_listener_close(CxiListener*);
class CxiBootstrap {
 public:
  int rank=0, peers=0;
  CxiBootstrap(void* handles[],int nranks,int rank,CxiListener*);
  ~CxiBootstrap();
  void allgather(const void* local,size_t bytes,void* all);
 private:
  std::vector<int> sockets;
  uint64_t sequence=0;
};
