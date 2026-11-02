#include "cxi_queue_credit.h"
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <random>
#include <vector>

int main() {
  uint64_t states = 0, writes = 0, full = 0, wraps = 0;
  for (unsigned size : {16u, 32u, 128u, 2048u}) {
    const unsigned capacity = (size - 8) / 2;
    for (unsigned producer = 0; producer < capacity; ++producer)
      for (unsigned consumer = 0; consumer < capacity; ++consumer) {
        unsigned used = (producer + capacity - consumer) % capacity;
        int slots = cxi_gin::cq_free_slots32(size, 8 + 2 * producer, 8 + 2 * consumer);
        assert(slots == int(2 * (capacity - 1 - used)));
        if (slots >= 2) assert((producer + 1) % capacity != consumer);
        ++states;
      }
    assert(cxi_gin::cq_free_slots32(size, 8, 0) <= int(2 * (capacity - 1)));

    // Physical slots carry monotonically increasing tags. Simulate a NIC that
    // consumes independently and writes its read pointer back with delays.
    // Producer credit checks must never overwrite an unconsumed command.
    std::vector<uint64_t> ring(capacity, 0);
    uint64_t posted = 0, consumed = 0, reported = 0;
    std::mt19937 random(size);
    for (unsigned iteration = 0; iteration < 200000; ++iteration) {
      if (consumed < posted && random() % 3 != 0) {
        assert(ring[consumed % capacity] == consumed + 1);
        ring[consumed++ % capacity] = 0;
      }
      if (random() % 5 == 0) reported = consumed;
      int credits = cxi_gin::cq_free_slots32(size, 8 + 2 * (posted % capacity),
                                            8 + 2 * (reported % capacity));
      assert(credits >= 0);
      if (credits >= 2) {
        assert(posted - consumed < capacity - 1);
        assert(ring[posted % capacity] == 0);
        ring[posted % capacity] = posted + 1;
        ++posted; ++writes;
        if (posted % capacity == 0) ++wraps;
      } else ++full;
    }
  }
  assert(cxi_gin::cq_free_slots32(16, 6, 8) == -1);
  assert(cxi_gin::cq_free_slots32(16, 8, 2) == -1);
  assert(cxi_gin::cq_free_slots32(16, 8, 16) == -1);
  assert(!cxi_gin::cq_positions_valid(0, 8, 0));
  assert(!cxi_gin::cq_positions_valid(16, 9, 0));
  assert(!cxi_gin::cq_positions_valid(16, 8, 7));
  // A negative initial credit count is distinguishable from invalid metadata.
  assert(cxi_gin::cq_positions_valid(12, 8, 0));
  assert(cxi_gin::cq_free_slots32(12, 8, 0) < 2);
  assert(full && wraps);
  // A separate consumption sequence validates bounded pacing with stale NIC
  // read-pointer publication, including wrapping and the initial zero value.
  for (unsigned limit : {1u, 2u, 4u, 8u}) {
    const unsigned size=128, capacity=(size-8)/2;
    uint64_t posted=0, consumed=0, reported=0;
    std::mt19937 rng(limit);
    std::vector<uint64_t> ring(capacity,0);
    for(unsigned tick=0;tick<200000;++tick) {
      if(consumed<posted && rng()%3) {
        assert(ring[consumed%capacity]==consumed+1);
        ring[consumed++%capacity]=0;
      }
      if(rng()%4==0)reported=consumed;
      unsigned wp=8+2*(posted%capacity),rp=reported?8+2*(reported%capacity):0;
      const auto pending=cxi_gin::cq_pending_commands(size,wp,rp);
      assert(pending==posted-reported);
      if(cxi_gin::cq_free_slots32(size,wp,rp)>=2 && pending<limit) {
        assert(ring[posted%capacity]==0);
        ring[posted%capacity]=posted+1;++posted;
        assert(posted-consumed<=limit);
      }
    }
    assert(posted>capacity*100);
  }
  std::printf("PASS states=%llu writes=%llu backpressure=%llu wraps=%llu; CPU ring model only\n",
              (unsigned long long)states, (unsigned long long)writes,
              (unsigned long long)full, (unsigned long long)wraps);
}
