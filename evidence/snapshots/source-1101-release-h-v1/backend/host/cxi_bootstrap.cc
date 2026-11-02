#include "cxi_bootstrap.h"
#include <sys/socket.h>
#include <sys/ioctl.h>
#include <sys/random.h>
#include <net/if.h>
#include <netinet/in.h>
#include <netinet/tcp.h>
#include <poll.h>
#include <unistd.h>
#include <cerrno>
#include <cstring>
#include <cstdio>
#include <cstdlib>
#include <stdexcept>
#include <string>
#include <algorithm>

namespace {
constexpr uint64_t magic=0x43584947494e3031ULL;
void fail(const char* op) {throw std::runtime_error(std::string(op)+": "+strerror(errno));}
void options(int fd) {
  timeval tv{90,0};int one=1;
  if(setsockopt(fd,SOL_SOCKET,SO_RCVTIMEO,&tv,sizeof(tv)) ||
     setsockopt(fd,SOL_SOCKET,SO_SNDTIMEO,&tv,sizeof(tv)) ||
     setsockopt(fd,IPPROTO_TCP,TCP_NODELAY,&one,sizeof(one)))fail("bootstrap socket options");
}
void transfer(int fd,void* p,size_t n,bool send_data) {
  auto* b=static_cast<char*>(p);
  while(n) {
    ssize_t done=send_data?send(fd,b,n,MSG_NOSIGNAL):recv(fd,b,n,0);
    if(done<0 && errno==EINTR)continue;
    if(done<=0){if(done==0)errno=ECONNRESET;fail(send_data?"bootstrap send":"bootstrap recv");}
    b+=done;n-=done;
  }
}
struct Hello {uint64_t magic,cookie;uint32_t rank,peers;};
struct Header {uint64_t magic,sequence,bytes;};
}
CxiListener* cxi_listen(int device) {
  auto* l=new CxiListener;l->device=device;
  try {
    l->fd=socket(AF_INET,SOCK_STREAM|SOCK_CLOEXEC,0);if(l->fd<0)fail("socket");options(l->fd);
    ifreq req{};const char* iface=getenv("CXI_GIN_BOOTSTRAP_IFNAME");if(!iface)iface="hsn0";
    if(strlen(iface)>=IFNAMSIZ)throw std::runtime_error("bootstrap interface name too long");
    strcpy(req.ifr_name,iface);if(ioctl(l->fd,SIOCGIFADDR,&req))fail("bootstrap interface address");
    sockaddr_in addr=*reinterpret_cast<sockaddr_in*>(&req.ifr_addr);addr.sin_port=0;
    if(bind(l->fd,(sockaddr*)&addr,sizeof(addr)) || listen(l->fd,64))fail("bootstrap bind/listen");
    socklen_t len=sizeof(addr);if(getsockname(l->fd,(sockaddr*)&addr,&len))fail("getsockname");
    l->handle.magic=magic;l->handle.address=addr.sin_addr.s_addr;l->handle.port=addr.sin_port;
    if(getrandom(&l->handle.cookie,sizeof(l->handle.cookie),0)!=(ssize_t)sizeof(l->handle.cookie))fail("getrandom");
    return l;
  }catch(...){cxi_listener_close(l);throw;}
}
void cxi_listener_close(CxiListener* l){if(l){if(l->fd>=0)close(l->fd);delete l;}}
CxiBootstrap::CxiBootstrap(void* handles[],int n,int r,CxiListener* l):rank(r),peers(n),sockets(n,-1) {
  if(n<1 || n>64 || r<0 || r>=n)throw std::runtime_error("bootstrap rank bounds");
  auto h=*static_cast<CxiBootstrapHandle*>(handles[0]);
  if(h.magic!=magic)throw std::runtime_error("bootstrap handle ABI");
  try {
    if(rank==0) {
      for(int i=1;i<n;i++) {
        pollfd p{l->fd,POLLIN,0};int rc;
        do{rc=poll(&p,1,90000);}while(rc<0 && errno==EINTR);
        if(rc<=0){errno=ETIMEDOUT;fail("bootstrap accept timeout");}
        int fd=accept4(l->fd,nullptr,nullptr,SOCK_CLOEXEC);if(fd<0)fail("accept");
        try {
          options(fd);Hello hello{};transfer(fd,&hello,sizeof(hello),false);
          if(hello.magic!=magic || hello.cookie!=h.cookie || hello.peers!=(uint32_t)n ||
             hello.rank==0 || hello.rank>=(uint32_t)n || sockets[hello.rank]>=0)
            throw std::runtime_error("bootstrap invalid handshake");
          sockets[hello.rank]=fd;
        }catch(...){close(fd);throw;}
      }
    }else {
      int fd=socket(AF_INET,SOCK_STREAM|SOCK_CLOEXEC,0);if(fd<0)fail("socket");sockets[0]=fd;options(fd);
      sockaddr_in a{};a.sin_family=AF_INET;a.sin_addr.s_addr=h.address;a.sin_port=h.port;
      if(::connect(fd,(sockaddr*)&a,sizeof(a)))fail("bootstrap connect");
      Hello hello{magic,h.cookie,(uint32_t)r,(uint32_t)n};transfer(fd,&hello,sizeof(hello),true);
    }
    uint32_t value=rank;std::vector<uint32_t> ranks(n);allgather(&value,sizeof(value),ranks.data());
    for(int i=0;i<n;i++)if(ranks[i]!=(uint32_t)i)throw std::runtime_error("bootstrap rank validation");
  }catch(...){for(auto fd:sockets)if(fd>=0)close(fd);sockets.assign(n,-1);throw;}
}
CxiBootstrap::~CxiBootstrap(){for(auto fd:sockets)if(fd>=0)close(fd);}
void CxiBootstrap::allgather(const void* local,size_t bytes,void* all) {
  if(!bytes || bytes>65536)throw std::runtime_error("bootstrap allgather size");
  Header expected{magic,sequence++,bytes};
  auto* buffer=static_cast<char*>(all);memcpy(buffer+rank*bytes,local,bytes);
  if(rank==0) {
    for(int r=1;r<peers;r++) {
      Header got{};transfer(sockets[r],&got,sizeof(got),false);
      if(got.magic!=expected.magic || got.sequence!=expected.sequence || got.bytes!=bytes)
        throw std::runtime_error("bootstrap collective mismatch");
      transfer(sockets[r],buffer+r*bytes,bytes,false);
    }
    for(int r=1;r<peers;r++)transfer(sockets[r],buffer,bytes*peers,true);
  }else {
    transfer(sockets[0],&expected,sizeof(expected),true);
    transfer(sockets[0],const_cast<void*>(local),bytes,true);
    transfer(sockets[0],buffer,bytes*peers,false);
  }
}
