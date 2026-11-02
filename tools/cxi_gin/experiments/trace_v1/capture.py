"""All-rank diagnostic capture, with correctness and overhead controls.

The ordinary benchmark stays unchanged. Trace buffers are private per process;
no collectives or file writes occur inside the captured dispatch call.
"""
import argparse
import faulthandler
faulthandler.enable(all_threads=True)
import ctypes
import gzip
import hashlib
import json
import os
from pathlib import Path
import statistics
import threading
import time
from datetime import timedelta
import torch
import torch.distributed as dist
from events import BUFFER_WORDS,CAPACITY,HEADER,SLOTS,WORDS,EVENTS
from common import bind_cpu,equal,reference_dispatch
from ep_benchmark import Backend,fp8,sha,measure,nic_snapshot,MODELS


def write(path,data):
    path.write_text(json.dumps(data,indent=2)+'\n')


def clock_exchange(group,rounds=12):
    """Bound remote monotonic-clock offset relative to rank 0 via ping-pong.

    No symmetric-delay assumption: lower=t2-t3, upper=t1-t0. The midpoint is
    only a visualization estimate. Absolute cross-rank intervals retain bounds.
    """
    rank=dist.get_rank();world=dist.get_world_size();result={'rank':rank,'offset_lower_ns':0,'offset_upper_ns':0}
    ping=torch.zeros(1,dtype=torch.int64);reply=torch.zeros(2,dtype=torch.int64)
    for peer in range(1,world):
        dist.barrier(group=group)
        samples=[]
        for _ in range(rounds):
            if rank==0:
                t0=time.monotonic_ns();dist.send(ping,dst=peer,group=group)
                dist.recv(reply,src=peer,group=group);t3=time.monotonic_ns()
                samples.append((int(reply[1])-t3,int(reply[0])-t0))
            elif rank==peer:
                dist.recv(ping,src=0,group=group);t1=time.monotonic_ns()
                reply[0]=t1;reply[1]=time.monotonic_ns();dist.send(reply,dst=0,group=group)
        if rank==0:
            low,high=max(x[0] for x in samples),min(x[1] for x in samples)
            assert low<=high,('clock offset intervals inconsistent',samples)
            reply[0]=low;reply[1]=high;dist.send(reply,dst=peer,group=group)
        elif rank==peer:
            dist.recv(reply,src=0,group=group)
            result={'rank':rank,'offset_lower_ns':int(reply[0]),'offset_upper_ns':int(reply[1])}
    dist.barrier(group=group)
    return result


def gpu_clock(lib):
    stamp=torch.empty(1,device='cuda',dtype=torch.int64);samples=[]
    for _ in range(12):
        torch.cuda.synchronize();lo=time.monotonic_ns()
        assert lib.trace_stamp(stamp.data_ptr(),torch.cuda.current_stream().cuda_stream)==0
        torch.cuda.synchronize();hi=time.monotonic_ns()
        gpu=int(stamp.item());samples.append({'gpu_ns':gpu,'host_lower_ns':lo,'host_upper_ns':hi})
    # One bracket, rather than an unjustified exact CPU/GPU timestamp conversion.
    best=min(samples,key=lambda x:x['host_upper_ns']-x['host_lower_ns'])
    return dict(best=best,samples=samples)


def counters(stop,path):
    with path.open('w') as f:
        while not stop.is_set():
            lo=time.monotonic_ns()
            try:r=nic_snapshot();error=None
            except Exception as e:r={};error=repr(e)
            hi=time.monotonic_ns()
            f.write(json.dumps(dict(host_lower_ns=lo,host_upper_ns=hi,counters=r,error=error))+'\n');f.flush()
            stop.wait(.01)


def decode(buffer):
    header=buffer[:HEADER].cpu().tolist()
    assert header[1]==0,('trace overflow',header[1])
    active=[i for i,n in enumerate(header[8:]) if n]
    assert active,'no device events'
    assert max(header[8:])<=CAPACITY
    # Copy only occupied warp slabs, not the full 256 MiB allocation.
    selected=buffer[HEADER:].view(SLOTS,CAPACITY,WORDS).index_select(0,torch.tensor(active,device='cuda'))
    selected=selected.cpu().numpy();events=[]
    for slab,slot in zip(selected,active):
        for row in slab[:header[8+slot]]:
            start,end,event,block,thread,a,b,sm=map(int,row)
            assert end>=start>0 and event in EVENTS,(start,end,event)
            events.append(dict(start_ns=start,end_ns=end,event=event,block=block,thread=thread,aux0=a,aux1=b,sm=sm))
    return events,{'overflow':header[1],'occupied_warps':len(active),'max_records_per_warp':max(header[8:]),'records':len(events)}


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,required=True);ap.add_argument('--model',default='v4flash',choices=MODELS)
    ap.add_argument('--captures',type=int,default=3);ap.add_argument('--nic-iters',type=int,default=600);a=ap.parse_args()
    rank=int(os.environ['RANK']);local=int(os.environ['LOCAL_RANK'])
    def stage(name):print(f'TRACE_STARTUP rank={rank} stage={name}',flush=True)
    stage('bind_cpu');affinity=bind_cpu(local)
    stage('cuda_set_device');torch.cuda.set_device(local)
    stage('init_nccl_eager')
    dist.init_process_group('nccl',device_id=torch.device('cuda',local),timeout=timedelta(seconds=240));assert dist.get_world_size()==8
    stage('init_gloo');control=dist.new_group(backend='gloo',timeout=timedelta(seconds=180))
    stage('allocate_trace')
    out=a.output/a.model;out.mkdir(parents=True,exist_ok=True)
    trace=torch.zeros(BUFFER_WORDS,device='cuda',dtype=torch.int64)
    os.environ['EP_TRACE_DEVICE_PTR']=str(trace.data_ptr())
    os.environ['EP_JIT_NVCC_COMPILER']=str(Path(__file__).with_name('nvcc_wrapper.py'))
    # Compiler caches must never reuse a cubin containing another process's pointer.
    os.environ['EP_JIT_CACHE_DIR']=os.environ['EP_JIT_CACHE_DIR']+'/trace-rank'+str(rank)+'-pid'+str(os.getpid())
    import deep_ep,deep_ep._C
    assert hasattr(deep_ep._C,'_ep_trace_host_enable'),'trace native build not loaded'
    lib=ctypes.CDLL(os.environ['EP_TRACE_STAMP_SO']);lib.trace_stamp.argtypes=[ctypes.c_void_p,ctypes.c_void_p];lib.trace_stamp.restype=ctypes.c_int
    n=4096;h,e,k=MODELS[a.model];torch.manual_seed(100+rank)
    idx=torch.rand(n,e,device='cuda').topk(k,dim=1).indices
    weights=torch.rand(n,k,device='cuda');weights/=weights.sum(1,keepdim=True)
    xb=torch.randn(n,h,dtype=torch.bfloat16,device='cuda');x=fp8(xb)
    args=argparse.Namespace(backend='deepep',warmup=10,iters=50)
    stage('create_backend');backend=Backend(args,n,h,e,k)
    stage('reference_dispatch');reference=reference_dispatch(x,idx,weights,e)
    def check(result):
        rx,ri,rw,counts,handle,src,count=backend.unpack(result,reference[3]);order=torch.argsort(src)
        equal(src[order],reference[3],'trace source IDs');equal(ri[:count][order],reference[1],'trace experts')
        for got,want in zip(rx,reference[0]):equal(got[:count][order],want,'trace payload/scales')
        equal(rw[:count][order].masked_fill(reference[1]<0,0),reference[2].masked_fill(reference[1]<0,0),'trace weights')
        expected=torch.bincount(reference[1][reference[1]>=0],minlength=e//8).tolist()
        assert list(counts)==[((v+127)//128)*128 for v in expected]
    def dispatch():return backend.dispatch(x,idx,weights)
    stage('initial_dispatch');initial=dispatch();check(initial);del initial;torch.cuda.synchronize()
    stage('initial_correctness_passed')
    clocks_pre=clock_exchange(control);gpu_pre=gpu_clock(lib)
    disabled=measure(dispatch,args)
    write(out/f'baseline-disabled-rank{rank}.json',disabled)
    # Repeated isolated operation window for hardware counter rates. Not a
    # claim about sub-millisecond wire activity; retain telemetry timestamps.
    stop=threading.Event();sampler=None
    if local==0:
        sampler=threading.Thread(target=counters,args=(stop,out/f'nic-node{rank//4}.jsonl'),daemon=True);sampler.start()
    dist.barrier(group=control);net_start=time.monotonic_ns()
    for _ in range(a.nic_iters):result=dispatch()
    torch.cuda.synchronize();net_end=time.monotonic_ns();dist.barrier(group=control)
    if sampler:stop.set();sampler.join()
    del result
    write(out/f'nic-window-rank{rank}.json',dict(start_ns=net_start,end_ns=net_end,iterations=a.nic_iters))
    captures=[]
    for iteration in range(a.captures):
        trace.zero_();trace[0].fill_(1);torch.cuda.synchronize();dist.barrier(group=control)
        deep_ep._C._ep_trace_host_enable(True)
        start=torch.cuda.Event(enable_timing=True);end=torch.cuda.Event(enable_timing=True)
        host_start=time.monotonic_ns();start.record();result=dispatch();end.record();torch.cuda.synchronize();host_end=time.monotonic_ns()
        host=deep_ep._C._ep_trace_host_read();trace[0].zero_();torch.cuda.synchronize()
        elapsed=start.elapsed_time(end)*1000;events,stats=decode(trace)
        check(result);del result
        capture=dict(rank=rank,iteration=iteration,model=a.model,host_start_ns=host_start,host_end_ns=host_end,
                     cuda_event_us=elapsed,host_events=host,events=events,stats=stats,correctness='PASS')
        with gzip.open(out/f'dispatch-rank{rank}-iteration{iteration}.json.gz','wt') as f:json.dump(capture,f)
        captures.append(dict(iteration=iteration,cuda_event_us=elapsed,**stats))
        dist.barrier(group=control)
    gpu_post=gpu_clock(lib);clocks_post=clock_exchange(control)
    after=measure(dispatch,args)
    binary=Path(deep_ep._C.__file__)
    write(out/f'manifest-rank{rank}.json',dict(rank=rank,hostname=os.uname().nodename,affinity=affinity,
        source=deep_ep.__file__,binary=str(binary),binary_sha256=hashlib.sha256(binary.read_bytes()).hexdigest(),
        route_sha256=sha(idx),hidden=h,experts=e,topk=k,tokens_per_gpu=n,sms=backend.sms,qps=backend.qps,
        remote_tokens=int((idx//(e//2)!=rank//4).any(1).sum()),gin_type=os.environ['NCCL_GIN_TYPE'],
        clock_pre=clocks_pre,clock_post=clocks_post,gpu_clock_pre=gpu_pre,gpu_clock_post=gpu_post,
        disabled_before=disabled,disabled_after=after,captures=captures,
        scope='Fresh FP8 dispatch; GPU intervals inclusive/overlapping. Cross-rank alignment bounded, not exact. NIC counters are window rates, not DMA-active durations.'))
    (out/f'libraries-rank{rank}.txt').write_text(Path('/proc/self/maps').read_text())
    torch.cuda.synchronize();dist.barrier(group=control);backend.buf.destroy()
    (out/f'DONE-rank{rank}').write_text('PASS\n');dist.destroy_process_group()

if __name__=='__main__':main()
