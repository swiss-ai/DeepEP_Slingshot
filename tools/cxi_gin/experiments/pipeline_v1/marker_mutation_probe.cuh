// Receiver consumes and clears a PUT destination before sender flush.
// This is legal for self-describing notification data; the sender's source stays
// unchanged. A flush must not write the destination a second time.
struct MutationResult {unsigned rounds,errors,stage;uint32_t observed,expected;};
__global__ void mutation_probe(ncclDevComm_t comm,ncclWindow_t sw,ncclWindow_t dw,
    unsigned char* src,unsigned char* dst,unsigned rounds,bool expect_clobber,MutationResult* out) {
  ncclGin data(comm,0),hand(comm,1);auto world=ncclTeamWorld(comm);int peer=comm.rank^4;
  // Host barriers surround reset_smoke before launch. Never derive a baseline
  // from live peer-updated signals: a fast peer can advance them before we read.
  uint64_t ready=0,cleared=0,flushed=0;
  for(unsigned round=0;round<rounds;round++) {
    *(uint32_t*)src=0xffffffffu;*(uint32_t*)dst=0;__threadfence_system();
    hand.signal(world,peer,ncclGin_SignalInc{0});
    if(hand.waitSignal(ncclCoopThread(),0,++ready,64,cuda::memory_order_acquire,timeout_cycles)!=ncclSuccess){out->stage=1;out->errors++;return;}
    data.put(world,peer,dw,0,sw,0,4,ncclGin_None{},ncclGin_None{},ncclCoopThread());
    uint64_t start=clock64();uint32_t got;
    do {
      asm volatile("ld.acquire.sys.global.u32 %0, [%1];":"=r"(got):"l"(dst):"memory");
      if(clock64()-start>timeout_cycles){out->stage=2;out->errors++;out->observed=got;return;}
    }while(got!=0xffffffffu);
    asm volatile("st.release.sys.global.u32 [%0], %1;"::"l"(dst),"r"(0u):"memory");
    hand.signal(world,peer,ncclGin_SignalInc{1});
    if(hand.waitSignal(ncclCoopThread(),1,++cleared,64,cuda::memory_order_acquire,timeout_cycles)!=ncclSuccess){out->stage=3;out->errors++;return;}
    if(data.flush(ncclCoopThread(),cuda::memory_order_acquire,ncclGin_None{},timeout_cycles)!=ncclSuccess){out->stage=4;out->errors++;return;}
    hand.signal(world,peer,ncclGin_SignalInc{2});
    if(hand.waitSignal(ncclCoopThread(),2,++flushed,64,cuda::memory_order_acquire,timeout_cycles)!=ncclSuccess){out->stage=5;out->errors++;return;}
    asm volatile("ld.acquire.sys.global.u32 %0, [%1];":"=r"(got):"l"(dst):"memory");
    out->observed=got;out->expected=expect_clobber?0xff000000u:0u;
    if(got!=out->expected){out->stage=6;out->errors++;return;}
    hand.signal(world,peer,ncclGin_SignalInc{0});
    if(hand.waitSignal(ncclCoopThread(),0,++ready,64,cuda::memory_order_acquire,timeout_cycles)!=ncclSuccess){out->stage=7;out->errors++;return;}
    out->rounds++;
  }
  if(hand.flush(ncclCoopThread(),cuda::memory_order_acquire,ncclGin_None{},timeout_cycles)!=ncclSuccess){out->stage=8;out->errors++;}
}
