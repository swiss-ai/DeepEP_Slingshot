namespace {
// Called only by context destruction after cudaDeviceSynchronize and device
// state capture. No GPU producer is active. This issues local CT_GET commands,
// never TX payload, signal, fence or delivery-marker commands. Steady-state
// dispatch/combine remain entirely GPU-initiated.
int refresh_retired_completion(CxiChannel* q, CxiGpuContext& state) {
  const double deadline=now()+5.0;
  const uint64_t old_completed=state.completed;
  auto failure=[&](const char* reason,uint64_t observed) {
    q->r->errors++;
    fprintf(stderr,"CXI retirement failure gpu=%d ct=%u reason=%s posted=%llu completed=%llu observed=%llu\n",
      q->r->gpu,state.ct_id,reason,(unsigned long long)state.posted,
      (unsigned long long)state.completed,(unsigned long long)observed);
    return 1;
  };
  if(state.completed>state.posted || state.posted>=(1ULL<<48))
    return failure("invalid-completion-range",state.completed);
  auto wait_empty=[&](cxi_cq* cq,uint32_t expected32) {
    for(;;) {
      uint64_t status=__atomic_load_n((uint64_t*)cq->cmds32,__ATOMIC_ACQUIRE);
      c_cq_status decoded{};
      static_assert(sizeof(decoded)==sizeof(status), "CXI CQ status layout changed");
      memcpy(&decoded,&status,sizeof(decoded));
      if(decoded.num_write_cmds_rejected || decoded.fail_command || decoded.return_code!=C_RC_OK)
        return failure("queue-status",status);
      uint32_t rp32=uint32_t(decoded.rd_ptr)*2;
      if(rp32==expected32 || (rp32==0 && expected32==8))return 0;
      if(now()>deadline)return failure("queue-drain-timeout",status);
      usleep(10);
    }
  };
  // Reconcile the CPU helper cursors with the final GPU-owned queue cursors.
  // Updating these fields does not ring a doorbell or publish TX commands.
  q->tx->wp32=q->tx->hw_wp32=state.tx_wp32;
  q->trig->wp32=q->trig->hw_wp32=state.ct_wp32;
  if(wait_empty(q->tx,state.tx_wp32) || wait_empty(q->trig,state.ct_wp32))return 1;
  q->trig->rp32=state.ct_wp32;
  unsigned reads=0;
  for(;;) {
    __atomic_store_n((uint64_t*)q->wb,0ULL,__ATOMIC_RELEASE);
    c_ct_cmd get{};get.ct=q->ct->ctn;
    int rc=cxi_cq_emit_ct(q->trig,C_CMD_CT_GET,&get);
    if(rc)return failure("ct-get-submit",uint64_t(int64_t(rc)));
    cxi_cq_ring(q->trig);reads++;
    uint64_t value;
    do {
      value=__atomic_load_n((uint64_t*)q->wb,__ATOMIC_ACQUIRE);
      if(now()>deadline)return failure("ct-writeback-timeout",value);
      if(!(value&(1ULL<<63)))usleep(10);
    }while(!(value&(1ULL<<63)));
    if((value>>48)&127)return failure("ct-failure",value);
    uint64_t completed=value&((1ULL<<48)-1);
    if(completed<state.completed || completed>state.posted)
      return failure("ct-count-mismatch",value);
    if(wait_empty(q->trig,q->trig->wp32))return 1;
    state.ct_wp32=q->trig->wp32;
    q->trig->rp32=state.ct_wp32;
    state.completed=completed;
    if(completed==state.posted)break;
    if(now()>deadline)return failure("completion-timeout",value);
    usleep(10);
  }
  if(getenv("CXI_QUEUE_INVENTORY"))
    fprintf(stderr,"CXI_RETIRE_REFRESH gpu=%d ct=%u before=%llu posted=%llu completed=%llu reads=%u teardown_only=1\n",
      q->r->gpu,state.ct_id,(unsigned long long)old_completed,
      (unsigned long long)state.posted,(unsigned long long)state.completed,reads);
  return 0;
}
} // namespace

