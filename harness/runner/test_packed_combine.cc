// CPU model of the packed-combine permutation and batching. Host-only evidence.
#include "cxi_packed_combine.cuh"
#include <cassert>
#include <cstdio>
#include <vector>
#include <random>
using deep_ep::elastic::packed_combine_slot;
int main() {
  long cases = 0, batches = 0, rows = 0;
  for (int cap : {257, 4096, 8192, 16384}) for (int channels : {64, 128, 256}) {
    // Bijection on [0, cap) and channel ownership of a contiguous slot range.
    std::vector<int> seen(cap, 0);
    for (int t = 0; t < cap; ++t) { int s = packed_combine_slot(cap, channels, t); assert(0 <= s && s < cap); assert(!seen[s]++); }
    for (int c = 0; c < channels; ++c) {
      int prev = -1;
      for (int t = c; t < cap; t += channels) { int s = packed_combine_slot(cap, channels, t); assert(prev < 0 || s == prev + 1); prev = s; }
    }
    // Batch model: remote-origin subsequence of a channel (random gaps) -> contiguous runs only.
    std::mt19937 rng(cap * 31 + channels);
    for (int c = 0; c < channels; ++c) for (int batch : {8, 16}) {
      int first = -1, last = -1; std::vector<std::pair<int,int>> puts;
      for (int t = c; t < cap; t += channels) {
        if (rng() % 64 == 0) continue;               // token with no expert on the remote node
        int j = t / channels; ++rows;
        bool contiguous = first >= 0 && j == last + 1;
        if (!contiguous) { if (first >= 0) puts.emplace_back(first, last); first = j; }
        last = j;
        if (last - first + 1 >= batch) { puts.emplace_back(first, last); first = -1; }
      }
      if (first >= 0) puts.emplace_back(first, last);
      for (auto [a, b] : puts) { assert(a <= b && b - a + 1 <= batch); ++batches;
        // Every slot in the put range belongs to channel c, so no other channel's slot is overwritten.
        for (int j = a; j <= b; ++j) { int t = c + j * channels; assert(t < cap && packed_combine_slot(cap, channels, t) == packed_combine_slot(cap, channels, c) + j); } }
      ++cases;
    }
  }
  std::printf("PASS packed combine model: cases=%ld rows=%ld batches=%ld; GPU untested\n", cases, rows, batches);
}
