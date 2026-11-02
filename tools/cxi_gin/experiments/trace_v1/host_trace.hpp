#pragma once
#include <time.h>
#include <stdint.h>
#include <vector>
namespace ep_trace_host {
struct Event {const char* name; uint64_t ns;};
inline thread_local bool active=false;
inline thread_local std::vector<Event> events;
inline void mark(const char* name) {
  if (!active) return;
  timespec t; clock_gettime(CLOCK_MONOTONIC,&t);
  events.push_back({name,uint64_t(t.tv_sec)*1000000000ULL+uint64_t(t.tv_nsec)});
}
inline void enable(bool value) {events.clear();events.reserve(256);active=value;}
}
