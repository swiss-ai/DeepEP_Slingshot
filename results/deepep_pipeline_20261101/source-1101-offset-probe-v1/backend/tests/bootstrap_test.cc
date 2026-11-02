#include "cxi_bootstrap.h"
#include <thread>
#include <vector>
#include <cstdio>
#include <cstdlib>
#include <atomic>
#include <stdexcept>

int main() {
  setenv("CXI_GIN_BOOTSTRAP_IFNAME","lo",1);
  constexpr int peers=8;
  std::vector<CxiListener*> listeners;std::vector<void*> handles;
  for(int r=0;r<peers;r++){listeners.push_back(cxi_listen(r));handles.push_back(&listeners.back()->handle);}
  std::atomic<int> failures{0};std::vector<std::thread> workers;
  for(int rank=0;rank<peers;rank++)workers.emplace_back([&,rank]{
    try {
      CxiBootstrap comm(handles.data(),peers,rank,listeners[rank]);
      for(unsigned round=0;round<64;round++) {
        struct Data {uint64_t rank,round,tag;};
        Data mine{(uint64_t)rank,round,0x123456789ULL+rank*101+round};std::vector<Data> all(peers);
        comm.allgather(&mine,sizeof(mine),all.data());
        for(int r=0;r<peers;r++)if(all[r].rank!=(unsigned)r || all[r].round!=round || all[r].tag!=0x123456789ULL+r*101+round)
          throw std::runtime_error("allgather data mismatch");
      }
    }catch(const std::exception& e){fprintf(stderr,"rank%d: %s\n",rank,e.what());failures++;}
  });
  for(auto& worker:workers)worker.join();for(auto* l:listeners)cxi_listener_close(l);
  printf("bootstrap_test peers=8 rounds=64 errors=%d\n",failures.load());return failures?1:0;
}
