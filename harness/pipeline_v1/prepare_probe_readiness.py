"""Separate raw-probe host allocation/module loading from GPU network timeout."""
from pathlib import Path
from package import replace


def prepare(snapshot):
    probe=Path(snapshot)/'runner/burst_probe.cu'
    replace(probe,'double deadline=secs()+25;', 'double deadline=secs()+120;')
    replace(probe,'  CxiGpuContext final{};bool copied=false;int rc=1;',
            '  CxiGpuContext final{};bool copied=false;int rc=1;double setup_start=secs();')
    replace(probe,'    dynamic_test<<<1,1>>>(dc,sw,dw,src,dst,rank,result);', '''    // Descriptor publication precedes queue/device allocation. A peer must not
    // start its short GPU protocol timeout while this rank is still setting up.
    // Force module loading here as well; the handshake is outside the kernel.
    cudaFuncAttributes attributes{};
    CK(cudaFuncGetAttributes(&attributes,dynamic_test));
    CK(cudaDeviceSynchronize());
    fprintf(stderr,"RAW_SETUP rank=%u phase=kernel_ready elapsed_s=%.6f\\n",rank,secs()-setup_start);
    exchange(dir,rank,hd.peer[rank],"kernel-ready");
    fprintf(stderr,"RAW_SETUP rank=%u phase=peer_ready elapsed_s=%.6f\\n",rank,secs()-setup_start);
    dynamic_test<<<1,1>>>(dc,sw,dw,src,dst,rank,result);''')
