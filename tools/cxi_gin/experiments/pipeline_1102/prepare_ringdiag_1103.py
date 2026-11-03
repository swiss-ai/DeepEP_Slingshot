#!/usr/bin/env python3
"""Ring registration diagnostic and ATS ring access (2026-11-03 morning).

Finding (11-02 evening traces, 11_02 log §5.7–5.9): every channel's first PUT pays ~80 µs in its first
access to the host-mapped command ring when 128 contexts start together; later accesses cost 1–3 µs. The
ring is libcxi's command queue: kernel pages (`alloc_pages_node`) mapped into the process with
`remap_pfn_range` (shs-cxi-driver cass_cq.c / cxi_user_mmap.c), which `cudaHostRegister` cannot pin as
plain mapped memory, so `CxiResources::map()` most likely takes its silent `cudaHostRegisterIoMemory`
fallback and the GPU treats the ring as uncached IO memory. Two host-side changes, no device code:

1. Diagnostic: `map()` records which registration succeeded, prints the first eight mappings with the
   first attempt's error, the device pointer and the backing VMA line from /proc/self/maps (`CXI_MAP`),
   and the pool report carries cumulative map/fallback counts. `cxi_resources_open` prints the GPU's
   addressing attributes (`CXI_GPU_ADDRESSING`: pageable access, host page tables = ATS, host register).
2. `CXI_RING_ACCESS=ats`: the device uses the ring's host virtual address directly (GH200 address
   translation through the host page tables) instead of a registered device pointer; honoured only when
   the device reports PageableMemoryAccessUsesHostPageTables=1, otherwise a line says so and the
   registration path is used. The `CXI_QUEUE` inventory line carries `ring=ats|register`.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'pipeline_v1'))
from package import replace  # noqa: E402

def prepare(snapshot):
    out = Path(snapshot)
    f = out / 'backend/host/cxi_resources.cc'
    replace(f, '''void* page_alloc(size_t bytes) {void* p=nullptr;CK(posix_memalign(&p,65536,bytes));memset(p,0,bytes);return p;}
''', '''void* page_alloc(size_t bytes) {void* p=nullptr;CK(posix_memalign(&p,65536,bytes));memset(p,0,bytes);return p;}
// CXI_RING_ACCESS=ats: the device addresses the libcxi command ring through its host virtual address
// (GPU translation through the host page tables, GH200 ATS) instead of a cudaHostRegister mapping.
const char* ring_access_name(){const char* s=getenv("CXI_RING_ACCESS");return (s && !strcmp(s,"ats"))?"ats":"register";}
// /proc/self/maps line backing an address (diagnostic only).
std::string vma_line(const void* p) {
  std::string out="?";FILE* f=fopen("/proc/self/maps","r");if(!f)return out;
  char line[512];unsigned long long a=(unsigned long long)(uintptr_t)p;
  while(fgets(line,sizeof line,f)){unsigned long long lo=0,hi=0;
    if(sscanf(line,"%llx-%llx",&lo,&hi)==2 && a>=lo && a<hi){size_t n=strlen(line);while(n && (line[n-1]=='\\n'||line[n-1]==' '))line[--n]=0;out=line;break;}}
  fclose(f);return out;
}
''')
    replace(f, '''  uint64_t created_channels=0,reused_channels=0;
  int errors=0;
  void* map(void* p,size_t bytes,bool io) {
    auto it=mappings.find(p);
    if(it!=mappings.end()){if(bytes>it->second.bytes)throw std::runtime_error("overlapping CUDA map");it->second.refs++;return it->second.gpu;}
    unsigned flags=cudaHostRegisterMapped|(io?cudaHostRegisterIoMemory:0);
    auto rc=cudaHostRegister(p,bytes,flags);
    if(rc){cudaGetLastError();rc=cudaHostRegister(p,bytes,cudaHostRegisterMapped|(io?0:cudaHostRegisterIoMemory));}
    CK(rc);void* gp=nullptr;
    rc=cudaHostGetDevicePointer(&gp,p,0);
    if(rc){cudaHostUnregister(p);CK(rc);}
    mappings.emplace(p,Map{gp,bytes,1});return gp;
  }
''', '''  uint64_t created_channels=0,reused_channels=0;
  int errors=0;
  unsigned map_count=0,map_fallbacks=0;int ats_capable=-1; // diagnostic 2026-11-03
  void* map(void* p,size_t bytes,bool io) {
    auto it=mappings.find(p);
    if(it!=mappings.end()){if(bytes>it->second.bytes)throw std::runtime_error("overlapping CUDA map");it->second.refs++;return it->second.gpu;}
    unsigned flags=cudaHostRegisterMapped|(io?cudaHostRegisterIoMemory:0);
    auto rc=cudaHostRegister(p,bytes,flags);int first_rc=rc;bool fallback=false;
    if(rc){cudaGetLastError();fallback=true;rc=cudaHostRegister(p,bytes,cudaHostRegisterMapped|(io?0:cudaHostRegisterIoMemory));}
    CK(rc);void* gp=nullptr;
    rc=cudaHostGetDevicePointer(&gp,p,0);
    if(rc){cudaHostUnregister(p);CK(rc);}
    map_count++;if(fallback)map_fallbacks++;
    if(map_count<=8)fprintf(stderr,"CXI_MAP gpu=%d p=%p bytes=%zu requested=%s registered=%s first_rc=%d(%s) device_ptr=%p vma=[%s]\\n",
      gpu,p,bytes,io?"IoMemory":"Mapped",(io!=fallback)?"IoMemory":"Mapped",first_rc,cudaGetErrorString((cudaError_t)first_rc),gp,vma_line(p).c_str());
    mappings.emplace(p,Map{gp,bytes,1});return gp;
  }
''')
    replace(f, '''    if(dev.rfind("cxi",0)!=0 || !svc)throw std::runtime_error("invalid allocated CXI service");
''', '''    if(dev.rfind("cxi",0)!=0 || !svc)throw std::runtime_error("invalid allocated CXI service");
    {int pma=0,hpt=0,dma=0,hreg=0;
     cudaDeviceGetAttribute(&pma,cudaDevAttrPageableMemoryAccess,gpu);
     cudaDeviceGetAttribute(&hpt,cudaDevAttrPageableMemoryAccessUsesHostPageTables,gpu);
     cudaDeviceGetAttribute(&dma,cudaDevAttrDirectManagedMemAccessFromHost,gpu);
     cudaDeviceGetAttribute(&hreg,cudaDevAttrHostRegisterSupported,gpu);
     r->ats_capable=hpt;
     fprintf(stderr,"CXI_GPU_ADDRESSING gpu=%d pageable_memory_access=%d uses_host_page_tables=%d direct_managed_from_host=%d host_register_supported=%d ring_access=%s\\n",
       gpu,pma,hpt,dma,hreg,ring_access_name());}
''')
    replace(f, '''    d.tx_queue=(uint64_t*)r->map(q->tx->cmds32,q->tx->size*64,false);q->txmap=true;
    d.ct_queue=(uint64_t*)r->map(q->trig->cmds32,q->trig->size*64,false);q->ctmap=true;
''', '''    const bool ats=!strcmp(ring_access_name(),"ats") && r->ats_capable==1;
    if(ats){d.tx_queue=(uint64_t*)q->tx->cmds32;d.ct_queue=(uint64_t*)q->trig->cmds32;}
    else {
      if(!strcmp(ring_access_name(),"ats") && r->created_channels==0)
        fprintf(stderr,"CXI_RING_ACCESS=ats requested but uses_host_page_tables=%d; using cudaHostRegister\\n",r->ats_capable);
      d.tx_queue=(uint64_t*)r->map(q->tx->cmds32,q->tx->size*64,false);q->txmap=true;
      d.ct_queue=(uint64_t*)r->map(q->trig->cmds32,q->trig->size*64,false);q->ctmap=true;
    }
''')
    replace(f, '''      "CXI_QUEUE gpu=%d requested=%u tx_size32=%u tx_wp32=%u ct_size32=%u ct_id=%u eq_id=%u\\n",
      r->gpu,depth,d.tx_size32,d.tx_wp32,d.ct_size32,d.ct_id,d.eq_id);
''', '''      "CXI_QUEUE gpu=%d requested=%u tx_size32=%u tx_wp32=%u ct_size32=%u ct_id=%u eq_id=%u ring=%s\\n",
      r->gpu,depth,d.tx_size32,d.tx_wp32,d.ct_size32,d.ct_id,d.eq_id,ats?"ats":"register");
''')
    replace(f, '''  fprintf(stderr,"CXI pool phase=%s gpu=%d created=%llu reused=%llu allocated=%u idle=%zu ct_in_use=%d usage_rc=%d\\n",
    phase,r->gpu,(unsigned long long)r->created_channels,(unsigned long long)r->reused_channels,
    r->channels,r->idle_channels.size(),rc?-1:(int)use.in_use[CXI_RSRC_TYPE_CT],rc);
''', '''  fprintf(stderr,"CXI pool phase=%s gpu=%d created=%llu reused=%llu allocated=%u idle=%zu ct_in_use=%d usage_rc=%d cuda_maps=%u iomem_fallbacks=%u\\n",
    phase,r->gpu,(unsigned long long)r->created_channels,(unsigned long long)r->reused_channels,
    r->channels,r->idle_channels.size(),rc?-1:(int)use.in_use[CXI_RSRC_TYPE_CT],rc,r->map_count,r->map_fallbacks);
''')
    return out

if __name__ == '__main__':
    prepare(sys.argv[1]); print('prepared', sys.argv[1])
