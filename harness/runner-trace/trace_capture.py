"""All-rank, per-operation GPU timestamps. NIC issue/observation != wire time."""
import ctypes,gzip,json,os,time
from pathlib import Path
import torch
import torch.distributed as dist
from common import equal
from ep_benchmark import measure
from trace_format import SLOTS,CAPACITY,HEADER,WORDS,decode_record
EVENTS={100:'dispatch_kernel',101:'dispatch_initial_barrier',102:'dispatch_metadata',103:'dispatch_sender',104:'dispatch_forwarder',105:'dispatch_arrival_wait',106:'dispatch_final_barrier',108:'dispatch_token_forward',109:'dispatch_NVLink_copy',110:'dispatch_signal',111:'dispatch_GIN_put',112:'dispatch_pack',120:'dispatch_copy_epilogue',121:'dispatch_epilogue_dependency',130:'combine_kernel',131:'combine_initial_barrier',132:'combine_NVLink_sender',133:'combine_forwarder',134:'combine_local_contributors_wait',135:'combine_reduce_and_stage_inclusive',136:'combine_TMA_store_wait',137:'combine_final_flush_and_signal',138:'combine_remote_tail_wait',139:'combine_end',140:'combine_reduce_epilogue',141:'combine_epilogue_dependency',200:'context_lock_acquire',201:'TX_publish_inclusive',202:'TX_capacity_or_baseline_consumption_wait',203:'completion_flush',204:'payload_put_inclusive',205:'signal_inclusive',206:'GIN_put_inclusive',207:'CT_writeback_wait',208:'CT_command_consumption_wait'}
EVENTS.update({113: 'packed_payload_submission', 114: 'tail_notification_submission', 115: 'receiver_tail_observation', 209: 'TX_publication', 210: 'delivery_marker_enqueue', 211: 'NIC_fence_enqueue', 212: 'CSTATE_submission', 213: 'atomic_notification_submission', 214: 'TX_admission_cursor_observation', 116: 'packed_combine_batch_submission'})
EVENTS.update({113: 'packed_payload_submission', 114: 'tail_notification_submission', 115: 'receiver_tail_observation', 209: 'TX_publication', 210: 'delivery_marker_enqueue', 211: 'NIC_fence_enqueue', 212: 'CSTATE_submission', 213: 'atomic_notification_submission', 214: 'TX_admission_cursor_observation'})
TRACE=None
def initialize():
    global TRACE
    TRACE=torch.zeros(HEADER+SLOTS*CAPACITY*WORDS,device='cuda',dtype=torch.int64)
    os.environ['EP_TRACE_DEVICE_PTR']=str(TRACE.data_ptr())
    os.environ['EP_JIT_CACHE_DIR']+='/trace-rank'+str(dist.get_rank())+'-pid'+str(os.getpid())
def write(p,v):p.write_text(json.dumps(v,indent=2)+'\n')
def decode():
    header=TRACE[:HEADER].cpu().tolist();active=[i for i,n in enumerate(header[8:]) if n]
    assert header[1]==0,('overflow',header[1],max(header[8:]))
    assert active and max(header[8:])<=CAPACITY
    rows=TRACE[HEADER:].view(SLOTS,CAPACITY,WORDS).index_select(0,torch.tensor(active,device='cuda')).cpu().numpy()
    result=[]
    for slab,slot in zip(rows,active):
        for r in slab[:header[8+slot]]:
            result.append(decode_record(r,EVENTS))
    return result,dict(overflow=header[1],max_records_per_warp=max(header[8:]),occupied_warps=len(active),records=len(result))
def clock_exchange(group,rounds=12):
    rank=dist.get_rank();p=torch.zeros(1,dtype=torch.int64);r=torch.zeros(2,dtype=torch.int64);out={'rank':rank,'offset_lower_ns':0,'offset_upper_ns':0}
    for peer in range(1,8):
        dist.barrier(group=group);samples=[]
        for _ in range(rounds):
            if rank==0:
                t0=time.monotonic_ns();dist.send(p,peer,group=group);dist.recv(r,peer,group=group);t3=time.monotonic_ns();samples.append((int(r[1])-t3,int(r[0])-t0))
            elif rank==peer:
                dist.recv(p,0,group=group);r[0]=time.monotonic_ns();r[1]=time.monotonic_ns();dist.send(r,0,group=group)
        if rank==0:
            r[0]=max(x[0] for x in samples);r[1]=min(x[1] for x in samples);assert r[0]<=r[1];dist.send(r,peer,group=group)
        elif rank==peer:
            dist.recv(r,0,group=group);out={'rank':rank,'offset_lower_ns':int(r[0]),'offset_upper_ns':int(r[1])}
    dist.barrier(group=group);return out

def gpu_clock():
    lib=ctypes.CDLL(os.environ['EP_TRACE_STAMP_SO']);lib.trace_stamp.argtypes=[ctypes.c_void_p,ctypes.c_void_p];lib.trace_stamp.restype=ctypes.c_int
    t=torch.empty(1,dtype=torch.int64,device='cuda');samples=[]
    for _ in range(12):
        torch.cuda.synchronize();lo=time.monotonic_ns();assert lib.trace_stamp(t.data_ptr(),torch.cuda.current_stream().cuda_stream)==0
        torch.cuda.synchronize();hi=time.monotonic_ns();samples.append(dict(gpu_ns=int(t.item()),host_lower_ns=lo,host_upper_ns=hi))
    return min(samples,key=lambda v:v['host_upper_ns']-v['host_lower_ns'])

def capture(backend,funcs,args,out,case,reference,combine_expected,weights):
    import deep_ep._C
    rank=dist.get_rank();target=out/'device-traces';target.mkdir(exist_ok=True)
    group=dist.new_group(backend='gloo');pre=dict(host=clock_exchange(group),gpu=gpu_clock())
    name='%s-%s-%s-%s'%(case['model'],case['tokens_per_gpu'],case['dispatch_dtype'],case['routing'])
    def check(op,r):
        if op=='combine':
            cy,cw,_=r;equal(cw,weights,'traced combine weights')
            err=(cy.float()-combine_expected).abs();assert torch.all(err<=.0625+.03*combine_expected.abs())
        else:
            rx,ri,rw,counts,handle,src,n=backend.unpack(r,reference[3]);order=torch.argsort(src)
            equal(src[order],reference[3],'traced source IDs');equal(ri[:n][order],reference[1],'traced expert IDs')
            for got,want in zip(rx if isinstance(rx,tuple) else (rx,),reference[0] if isinstance(reference[0],tuple) else (reference[0],)):
                equal(got[:n][order],want,'traced payload/scales')
            equal(rw[:n][order].masked_fill(reference[1]<0,0),reference[2].masked_fill(reference[1]<0,0),'traced weights')
    for op in ['dispatch_fresh','combine']:
        fn=funcs[op];disabled_before=measure(fn,args);captures=[]
        for i in range(int(os.environ.get('CXI_TRACE_CAPTURES','3'))):
            TRACE.zero_();TRACE[0].fill_(1);torch.cuda.synchronize();dist.barrier(group=group)
            deep_ep._C._ep_trace_host_enable(True)
            a=torch.cuda.Event(enable_timing=True);b=torch.cuda.Event(enable_timing=True)
            host_start=time.monotonic_ns();a.record();result=fn();host_return=time.monotonic_ns();b.record();torch.cuda.synchronize();host_end=time.monotonic_ns()
            host=deep_ep._C._ep_trace_host_read();TRACE[0].zero_();torch.cuda.synchronize()
            check(op,result);del result
            events,stats=decode();elapsed=a.elapsed_time(b)*1000
            record=dict(rank=rank,operation=op,iteration=i,case=case,cuda_event_us=elapsed,correctness='PASS',stats=stats,
                        host_start_ns=host_start,host_return_ns=host_return,host_end_ns=host_end,host_events=host,events=events)
            with gzip.open(target/('%s-%s-rank%d-iteration%d.json.gz'%(name,op,rank,i)),'wt') as f:json.dump(record,f)
            captures.append(dict(iteration=i,cuda_event_us=elapsed,**stats));dist.barrier(group=group)
        after=measure(fn,args)
        write(target/('%s-%s-rank%d-summary.json'%(name,op,rank)),dict(rank=rank,operation=op,case=case,clock_pre=pre,
              disabled_before=disabled_before,disabled_after=after,captures=captures,events=EVENTS,
              scope='GPU-observed inclusive/overlapping intervals; no NIC wire timestamps. Local elapsed times valid; cross-rank alignment has bounded uncertainty.'))
    write(target/('%s-clock-post-rank%d.json'%(name,rank)),dict(host=clock_exchange(group),gpu=gpu_clock()))
    dist.destroy_process_group(group)
