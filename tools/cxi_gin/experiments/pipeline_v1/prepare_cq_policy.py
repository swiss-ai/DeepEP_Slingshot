"""Expose TX credit-writeback policy while retaining ALWAYS for CT commands.

This is a setup-only knob, not a device ABI/ordering change. A pooled channel
must have the requested policy; changing an environment option cannot silently
reuse a differently configured queue. Default behavior remains ALWAYS.
"""
from pathlib import Path
from package import replace


def prepare(snapshot):
    root=Path(snapshot)
    (root/'backend/include/cxi_cq_policy.h').write_text('''#pragma once
#include <cstring>
#include <stdexcept>
#include <libcxi/libcxi.h>
namespace cxi_gin_host {
inline cxi_cq_update_policy tx_policy(const char* value) {
  if(!value || !std::strcmp(value,"always"))return CXI_CQ_UPDATE_ALWAYS;
  if(!std::strcmp(value,"high_empty"))return CXI_CQ_UPDATE_HIGH_FREQ_EMPTY;
  if(!std::strcmp(value,"low_empty"))return CXI_CQ_UPDATE_LOW_FREQ_EMPTY;
  throw std::runtime_error("CXI_TX_CQ_POLICY must be always, high_empty, or low_empty");
}
}
''')
    host=root/'backend/host/cxi_resources.cc'
    replace(host,'#include "cxi_resources.h"','#include "cxi_resources.h"\n#include "cxi_cq_policy.h"')
    replace(host,'  unsigned depth=0;bool pooled=false;',
            '  unsigned depth=0;bool pooled=false;\n  cxi_cq_update_policy tx_policy=CXI_CQ_UPDATE_ALWAYS;')
    replace(host,'  depth=std::max(depth,64u);',
            '  depth=std::max(depth,64u);\n  const auto policy=cxi_gin_host::tx_policy(getenv("CXI_TX_CQ_POLICY"));')
    replace(host,'    if(q->depth>=depth){', '    if(q->depth>=depth && q->tx_policy==policy){')
    replace(host,'  auto* q=new CxiChannel;q->r=r;q->depth=depth;',
            '  auto* q=new CxiChannel;q->r=r;q->depth=depth;q->tx_policy=policy;')
    replace(host,'cxi_cq_alloc_opts qo{};qo.count=std::max(depth,64u);qo.flags=CXI_CQ_IS_TX;qo.lcid=r->cp->lcid;qo.policy=CXI_CQ_UPDATE_ALWAYS;',
            'cxi_cq_alloc_opts qo{};qo.count=std::max(depth,64u);qo.flags=CXI_CQ_IS_TX;qo.lcid=r->cp->lcid;qo.policy=policy;')
    replace(host,'qo.lcid=r->trig_cp->lcid;',
            'qo.lcid=r->trig_cp->lcid;qo.policy=CXI_CQ_UPDATE_ALWAYS;')
    replace(host,'ct_id=%u eq_id=%u\\n",', 'ct_id=%u eq_id=%u tx_policy=%u ct_policy=%u\\n",')
    replace(host,'r->gpu,depth,d.tx_size32,d.tx_wp32,d.ct_size32,d.ct_id,d.eq_id);',
            'r->gpu,depth,d.tx_size32,d.tx_wp32,d.ct_size32,d.ct_id,d.eq_id,\n      unsigned(policy),unsigned(CXI_CQ_UPDATE_ALWAYS));')
    (root/'runner/test_cq_policy.cc').write_text('''#include "cxi_cq_policy.h"
#include <cassert>
#include <cstdio>
#include <initializer_list>
int main(){
  using cxi_gin_host::tx_policy;
  assert(tx_policy(nullptr)==CXI_CQ_UPDATE_ALWAYS);
  assert(tx_policy("always")==CXI_CQ_UPDATE_ALWAYS);
  assert(tx_policy("high_empty")==CXI_CQ_UPDATE_HIGH_FREQ_EMPTY);
  assert(tx_policy("low_empty")==CXI_CQ_UPDATE_LOW_FREQ_EMPTY);
  for(const char* bad:{"","low","invalid"}){
    bool rejected=false;try{tx_policy(bad);}catch(const std::runtime_error&){rejected=true;}
    assert(rejected);
  }
  std::printf("PASS policy parser: always=%u high_empty=%u low_empty=%u; hardware untested\\n",
    unsigned(CXI_CQ_UPDATE_ALWAYS),unsigned(CXI_CQ_UPDATE_HIGH_FREQ_EMPTY),unsigned(CXI_CQ_UPDATE_LOW_FREQ_EMPTY));
}
''')
