#include <nccl_device.h>
#include <cstdio>
__global__ void exercise(ncclDevComm_t comm,ncclWindow_t window) {
  ncclGin gin(comm,0);auto world=ncclTeamWorld(comm);
  gin.put(world,0,window,0,window,0,8,ncclGin_SignalInc{0});
  gin.signal(world,0,ncclGin_VASignalAdd{window,8,1});
  gin.flush(ncclCoopThread());
}
