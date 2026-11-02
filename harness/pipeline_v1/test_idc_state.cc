#include "cxi_idc_state.h"
#include "cxi_gin_abi.h"
#include "cassini_user_defs.h"
#include <cassert>
#include <cstdio>
#include <random>

int main() {
  CxiGpuContext fresh{};
  assert(fresh.idc_state_key == 0);
  assert(!cxi_gin::idc_state_fields_valid(32,0,0,0));
  assert(!cxi_gin::idc_state_fields_valid(0,8,0,0));
  assert(!cxi_gin::idc_state_fields_valid(0,0,2048,0));
  assert(!cxi_gin::idc_state_fields_valid(0,0,0,2048));
  std::mt19937 rng(49);
  unsigned checks=0;
  for(unsigned i=0;i<1000000;i++) {
    unsigned index=rng()%32,lac=rng()%8,ct=rng()%2048,eq=rng()%2048;
    assert(cxi_gin::idc_state_fields_valid(index,lac,ct,eq));
    auto key=cxi_gin::idc_state_key(index,lac,ct,eq);
    assert((key>>31)==1 && ((key>>30)&1)==0);
    assert((key&31)==index && ((key>>5)&7)==lac);
    assert(((key>>8)&2047)==ct && ((key>>19)&2047)==eq);
    c_cstate_cmd command{};
    command.index_ext=index;command.write_lac=lac;command.ct=ct;command.eq=eq;
    assert(command.index_ext==index && command.write_lac==lac);
    assert(command.ct==ct && command.eq==eq);
    // Every single-field transition changes the key, including wrap to zero.
    assert(key!=cxi_gin::idc_state_key((index+1)%32,lac,ct,eq));
    assert(key!=cxi_gin::idc_state_key(index,(lac+1)%8,ct,eq));
    assert(key!=cxi_gin::idc_state_key(index,lac,(ct+1)%2048,eq));
    assert(key!=cxi_gin::idc_state_key(index,lac,ct,(eq+1)%2048));
    fresh.idc_state_key=key;
    CxiGpuContext recycled=fresh;
    assert(recycled.idc_state_key==key);
    checks++;
  }
  std::printf("PASS IDC state ABI/layout/key: %u randomized field transitions\n",checks);
}
