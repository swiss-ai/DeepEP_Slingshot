#include "cxi_queue_credit.h"
#include "cxi_gin_abi.h"
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <random>
#include <vector>

int main() {
  uint64_t writes=0, refreshes=0, cached=0, wraps=0, full=0;
  // Monotonic producer/consumer indices and tagged ring entries are an
  // independent oracle. Delayed NIC status updates and cached GPU reads are
  // separate delays. No write may overwrite an unconsumed descriptor.
  for(unsigned size : {12u,16u,32u,128u,2048u})
    for(unsigned limit : {0u,1u,4u,16u})
      for(bool initial_zero : {false,true}) {
        const unsigned capacity=(size-8)/2;
        std::vector<uint64_t> ring(capacity,0);
        uint64_t posted=0, consumed=0, reported=0;
        uint32_t cached_rp=initial_zero?0:8;
        bool report_seen=!initial_zero;
        std::mt19937 random(size*19+limit*3+initial_zero);
        for(unsigned iteration=0;iteration<300000;++iteration) {
          if(consumed<posted && random()%3!=0) {
            assert(ring[consumed%capacity]==consumed+1);
            ring[consumed++%capacity]=0;
          }
          if(random()%7==0) {reported=consumed;report_seen=true;}
          unsigned wp=8+2*(posted%capacity);
          assert(cxi_gin::cq_positions_valid(size,wp,cached_rp));
          if(cxi_gin::cq_refresh_required(size,wp,cached_rp,limit)) {
            cached_rp=report_seen?8+2*(reported%capacity):0;
            ++refreshes;
          } else ++cached;
          int free=cxi_gin::cq_free_slots32(size,wp,cached_rp);
          if(free>=2 && (!limit || cxi_gin::cq_pending_commands(size,wp,cached_rp)<limit)) {
            assert(posted-consumed<capacity-1);
            assert(!limit || posted-consumed<limit);
            assert(ring[posted%capacity]==0);
            ring[posted%capacity]=posted+1;
            ++posted;++writes;
            if(posted%capacity==0)++wraps;
          } else ++full;
        }
        assert(posted && consumed);
      }
  assert(cached && refreshes && wraps && full);
  std::printf("PASS cached-credit ring simulation: writes=%llu refreshes=%llu cached=%llu wraps=%llu backpressure=%llu; host model only\n",
    (unsigned long long)writes,(unsigned long long)refreshes,(unsigned long long)cached,
    (unsigned long long)wraps,(unsigned long long)full);
}
