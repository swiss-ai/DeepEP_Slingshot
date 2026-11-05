"""Matched standalone EP4/EP8 campaign. Input tokens are per GPU, before fanout."""
import argparse
import gc
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
import traceback
import numpy as np
import torch
import torch.distributed as dist
from common import bind_cpu, equal, record, reference_dispatch
from routing import routes, ROUTING_CHOICES
import bank_routing
from source_metadata import source_metadata

MODELS = {'v4flash': (4096,256,6), 'qwen3': (4096,128,8), 'minimax': (3072,256,8)}

def sha(t):
    return hashlib.sha256(t.detach().cpu().contiguous().view(torch.uint8).numpy().tobytes()).hexdigest()

def fp8(x):
    a=x.view(len(x),-1,128).abs().float().amax(2).clamp_min(1e-4)
    return (x.view(len(x),-1,128)*(448/a[:,:,None])).to(torch.float8_e4m3fn).view_as(x), a/448

def nic_snapshot():
    out={}
    for nic in sorted(Path('/sys/class/cxi').glob('cxi[0-9]*')):
        for counter in ('hni_sts_tx_ok_octets','hni_sts_rx_ok_octets'):
            raw=(nic/'device/telemetry'/counter).read_text().strip()
            value,stamp=raw.split('@')
            out[f'{nic.name}/{counter}']={'value':int(value),'timestamp':float(stamp)}
    return out

import diagnostic_watch

# UCCL: one buffer per process, as in upstream's benchmark. Destroying and recreating the buffer per case
# faulted the next case in October (UcclProxy and the DLPack deleter both freed the scratch allocation).
_UCCL_BUFFERS = {}

def measure(fn, args):
    for i in range(args.warmup):
        diagnostic_watch.mark('warmup_host_enter', call_index=i)
        result=fn()
        diagnostic_watch.mark('warmup_host_return', call_index=i)
    diagnostic_watch.mark('warmup_synchronize_enter')
    torch.cuda.synchronize(); dist.barrier()
    diagnostic_watch.mark('warmup_synchronize_and_barrier_return')
    starts=[torch.cuda.Event(enable_timing=True) for _ in range(args.iters)]
    ends=[torch.cuda.Event(enable_timing=True) for _ in starts]
    cpu=time.process_time(); wall=time.monotonic()
    for i,(a,b) in enumerate(zip(starts,ends)):
        diagnostic_watch.mark('timed_host_enter', call_index=i)
        a.record(); result=fn(); b.record()
        diagnostic_watch.mark('timed_host_return', call_index=i)
    diagnostic_watch.mark('timed_synchronize_enter')
    torch.cuda.synchronize()
    diagnostic_watch.mark('timed_synchronize_return')
    wall=time.monotonic()-wall; cpu=time.process_time()-cpu
    return {'cuda_event_us':[a.elapsed_time(b)*1000 for a,b in zip(starts,ends)],
            'window_wall_seconds':wall,'process_cpu_seconds':cpu,
            'process_cpu_core_equivalents':cpu/wall,'host_us_per_iteration':wall*1e6/args.iters}

def nic_window(fn,args,out,case):
    rank=dist.get_rank()
    torch.cuda.synchronize(); dist.barrier()
    before=nic_snapshot() if rank%4==0 else None
    dist.barrier(); start=time.monotonic()
    for _ in range(args.nic_iters): result=fn()
    torch.cuda.synchronize(); dist.barrier()
    elapsed=time.monotonic()-start
    if before:
        after=nic_snapshot(); rates={}
        for k,b in before.items():
            delta=after[k]['value']-b['value']; duration=after[k]['timestamp']-b['timestamp']
            assert duration>0 and delta>=0
            rates[k]={'octets':delta,'seconds':duration,'GBps':delta/duration/1e9}
        record(out/f'nic-node{rank//4}.jsonl',case|dict(before=before,after=after,rates=rates,
               iterations=args.nic_iters,wall_seconds=elapsed,hostname=os.uname().nodename,
               scope='isolated operation window including synchronization/control traffic'))
    dist.barrier()

class Backend:
    def __init__(self,args,n,h,e,k):
        self.args=args; self.e=e; self.n=n
        if args.backend=='uccl':
            from uccl import ep
            from buffer import Buffer
            Buffer.set_num_sms(args.sms)
            # Buffer sizes exactly as upstream bench/test_internode.py compute_buffer_sizes (hint config 8/512/16/512,
            # margin 1.2, 128-byte alignment); dispatch and combine get their own chunk configs as upstream tunes them.
            hint=ep.Config(args.sms,8,512,16,512)
            align=lambda x: ((int(x*1.2)+127)//128)*128
            nv=align(hint.get_nvl_buffer_size_hint(h*2,dist.get_world_size()))
            rd=align(hint.get_rdma_buffer_size_hint(h*2,dist.get_world_size())) if dist.get_world_size()>4 else 0
            self.config=ep.Config(args.sms,args.nvl_chunk,512,args.rdma_chunk,512)
            self.combine_config=ep.Config(args.sms,args.combine_nvl_chunk,512,args.combine_rdma_chunk,512)
            key=(nv,rd)
            if key not in _UCCL_BUFFERS:
                assert not _UCCL_BUFFERS, ('one UCCL buffer geometry per process', key, list(_UCCL_BUFFERS))
                _UCCL_BUFFERS[key]=Buffer(dist.group.WORLD,nv,rd,explicitly_destroy=True)
            self.buf=_UCCL_BUFFERS[key]
            if rd: assert self.buf.scratch.is_cuda
            self.sms=args.sms; self.qps=None; self.buffer_bytes=dict(nvl=nv,rdma=rd)
        else:
            import deep_ep
            self.buf=deep_ep.ElasticBuffer(dist.group.WORLD,num_max_tokens_per_rank=n,hidden=h,
                allow_hybrid_mode=True,allow_multiple_reduction=True,prefer_overlap_with_compute=False,
                num_allocated_qps=int(os.getenv('CXI_EP_CONTEXTS','129')),
                explicitly_destroy=True,num_cpu_timeout_secs=120,num_gpu_timeout_secs=60)
            self.sms=self.buf.get_theoretical_num_sms(e,k,rdma_gbs=25 if dist.get_world_size()>4 else 0)
            if os.getenv('CXI_EP_SMS'):
                self.sms=int(os.environ['CXI_EP_SMS'])
            self.qps=self.buf.get_theoretical_num_qps(self.sms)

    def dispatch(self,x,idx,w,handle=None):
        if self.args.backend=='uccl':
            if handle is not None:
                return self.buf.dispatch(x,handle=handle,config=self.config,async_finish=False)
            nr,nrdma,ne,mask,_=self.buf.get_dispatch_layout(idx,self.e)
            return self.buf.dispatch(x,num_tokens_per_rank=nr,num_tokens_per_rdma_rank=nrdma,
                num_tokens_per_expert=ne,is_token_in_rank=mask,topk_idx=idx,topk_weights=w,
                expert_alignment=128,config=self.config,async_finish=False)
        return self.buf.dispatch(x=x,topk_idx=idx if handle is None else None,
            topk_weights=w if handle is None else None,num_experts=self.e,num_max_tokens_per_rank=self.n,
            expert_alignment=128,num_sms=self.sms,num_qps=self.qps,handle=handle,
            do_handle_copy=True,do_cpu_sync=handle is None,do_expand=False,async_with_compute_stream=False)

    def unpack(self,result,reference_src):
        if self.args.backend=='uccl':
            rx,ri,rw,counts,handle,_=result
            return rx,ri,rw,counts,handle,reference_src,len(reference_src)
        rx,ri,rw,handle,_=result
        count=int(handle.psum_num_recv_tokens_per_scaleup_rank[-1].item())
        return rx,ri,rw,handle.num_recv_tokens_per_expert_list,handle,handle.recv_src_metadata[:count,0],count

    def combine(self,y,handle,w):
        if self.args.backend=='uccl':
            return self.buf.combine(y,handle,topk_weights=w,config=self.combine_config,async_finish=False)
        return self.buf.combine(y,handle,topk_weights=w,num_sms=self.sms,num_qps=self.qps,
                                async_with_compute_stream=False)

def run_case(args,model,n,dtype,routing,seed,out):
    rank,ep=dist.get_rank(),dist.get_world_size(); h,e,k=MODELS[model]
    torch.manual_seed(seed*100+rank)
    if routing=='uniform':
        idx=torch.rand(n,e,device='cuda').topk(k,dim=1).indices
    elif routing=='hot_rank':
        # Explicit empty-receiver case: every token targets unique experts on
        # rank zero; the other seven ranks receive zero payload rows.
        assert k <= e // ep
        idx=torch.arange(k,device='cuda',dtype=torch.int64)[None,:].expand(n,-1).contiguous()
    elif routing.startswith('bank_'):
        # Bank-consistent routing: exact per-expert counts of a real OpenSWE 4K unit (this rank's unit of
        # the forward), distinct experts per token, placement applied as a permutation of expert ids.
        bank_f,bank_l,bank_placement=bank_routing.parse_bank_name(routing); bank=bank_routing.load_bank(Path(__file__).parent)
        assert n==4096 and (e,k)==(256,6), 'bank routing is defined for 4096-token units of V4 Flash (256 experts, top-6)'
        bank_fi=list(bank['test_forwards']).index(bank_f); bank_counts=bank['test_counts'][bank_fi,bank_l,rank].astype(np.int64)
        bank_perm={'vanilla':np.arange(e),'greedy':bank['greedy_perm'][bank_l],'random':bank['random_perm']}[bank_placement]
        bank_ids=np.append(bank_perm,-1)[bank_routing.bank_routes(bank_counts,n,k,seed*1000+rank)]
        idx=torch.tensor(bank_ids,dtype=torch.int64,device='cuda')
    else:
        locality=routing if routing in ('local','remote') else 'mixed'
        skew=float(routing[4:]) if routing.startswith('skew') else 1.
        ids,_=routes(n,ep,e,k,skew,seed,locality)
        idx=torch.tensor(ids[rank*n:(rank+1)*n],dtype=torch.int64,device='cuda')
    w=torch.rand(n,k,device='cuda'); w=torch.where(idx<0,torch.zeros_like(w),w); w=w/w.sum(1,keepdim=True)
    drop_every=int(os.environ.get('CXI_EP_DROP_EVERY','0'))
    assert drop_every >= 0
    if drop_every:
        idx[::drop_every]=-1
        w[::drop_every]=0
    xb=torch.randn(n,h,dtype=torch.bfloat16,device='cuda')
    raw=fp8(xb) if dtype=='fp8' else xb
    x=(raw[0],raw[1].T.contiguous().T) if dtype=='fp8' and args.backend=='uccl' else raw
    case=dict(backend=args.backend,model=model,hidden=h,experts=e,topk=k,tokens_per_gpu=n,
        tokens_per_node=4*n,global_tokens=ep*n,ep=ep,rank=rank,seed=seed,dispatch_dtype=dtype,drop_every=drop_every,
        combine_dtype='bf16',routing=routing,route_sha256=sha(idx),input_sha256=sha(xb),
        requested_sms=args.sms,nvl_chunk=args.nvl_chunk,rdma_chunk=args.rdma_chunk,
        combine_nvl_chunk=args.combine_nvl_chunk,combine_rdma_chunk=args.combine_rdma_chunk,
        flush_l2=False,alignment=128,quantization_timed=False,expert_gemm=False,
        gin_type=os.getenv('NCCL_GIN_TYPE'), allocated_contexts=int(os.getenv('CXI_EP_CONTEXTS','129')))
    ids_np=idx.cpu().numpy()
    rows=bank_routing.route_matrix(ids_np,ep).tolist(); nic=bank_routing.nic_rows(ids_np,ep,rank)
    gathered=[None]*ep; dist.all_gather_object(gathered,(rows,nic))
    case['traffic']=bank_routing.traffic_stats([g[0] for g in gathered],[g[1] for g in gathered])
    if routing.startswith('bank_'):
        case['bank']=dict(forward=bank_f,layer=bank_l,placement=bank_placement,unit=8*bank_f+rank,
            tokens_with_fewer_experts=int((idx<0).any(1).sum().item()),**case['traffic'])
    diagnostic_watch.mark('case_start', model=model, tokens=n, dtype=dtype, routing=routing, seed=seed, operation=None)
    print('CASE_START',json.dumps(case),flush=True)
    ref=reference_dispatch(raw,idx,w,e)
    diagnostic_watch.mark('buffer_create_enter')
    b=Backend(args,n,h,e,k); case.update(actual_sms=b.sms,qps=b.qps,**(dict(uccl_buffer_bytes=b.buffer_bytes) if args.backend=='uccl' else {}))
    diagnostic_watch.mark('buffer_create_return')
    diagnostic_watch.mark('correctness_fresh_enter')
    result=b.dispatch(x,idx,w)
    diagnostic_watch.mark('correctness_fresh_return')
    rx,ri,rw,counts,handle,src,count=b.unpack(result,ref[3])
    order=torch.argsort(src); equal(src[order],ref[3],'source IDs')
    equal(ri[:count][order],ref[1],'expert IDs')
    for a,z in zip(rx if isinstance(rx,tuple) else (rx,),ref[0] if isinstance(ref[0],tuple) else (ref[0],)):
        equal(a[:count][order],z,'payload/scales')
    equal(rw[:count][order].masked_fill(ref[1]<0,0),ref[2].masked_fill(ref[1]<0,0),'weights')
    ec=torch.bincount(ref[1][ref[1]>=0],minlength=e//ep).tolist()
    assert list(counts)==[((v+127)//128)*128 for v in ec]
    diagnostic_watch.mark('correctness_fresh_validated')
    shape=(rx[0] if isinstance(rx,tuple) else rx).shape
    col=torch.arange(h,device='cuda')[None,:]; local_src=torch.arange(n,device='cuda')+rank*n
    def values(s,d,floating=False):
        v=((s[:,None]%7*3+d+col%5)%16)
        return (torch.sin(v.float()) if floating else v).to(torch.bfloat16)
    y=torch.zeros(shape,dtype=torch.bfloat16,device='cuda')
    errors={}
    for floating in (False,True):
        y[:count]=values(src,rank,floating)
        expected=torch.zeros(n,h,dtype=torch.float32,device='cuda')
        for d in range(ep):
            mask=(idx//(e//ep)==d).any(1)
            expected+=values(local_src,d,floating).float()*mask[:,None]
        diagnostic_watch.mark('correctness_combine_enter', floating=floating)
        cy,cw,_=b.combine(y,handle,rw)
        diagnostic_watch.mark('correctness_combine_return', floating=floating)
        equal(cw,w,'combine weights')
        if not floating: equal(cy,expected.to(torch.bfloat16),'exact combine')
        else:
            err=(cy.float()-expected).abs(); errors={'max_abs_error':err.max().item(),'atol':0.0625,'rtol':0.03}
            assert torch.all(err<=0.0625+0.03*expected.abs()),errors
    diagnostic_watch.mark('correctness_combines_validated')
    diagnostic_watch.mark('correctness_cached_enter')
    cached=b.dispatch(x,idx,w,handle)
    diagnostic_watch.mark('correctness_cached_return')
    crx=cached[0]
    for a,z in zip(crx if isinstance(crx,tuple) else (crx,),ref[0] if isinstance(ref[0],tuple) else (ref[0],)):
        equal(a[:count][order],z,'cached payload/scales')
    diagnostic_watch.mark('correctness_cached_validated')
    case['merged_final_tail']=bool(int(os.environ.get('CXI_EP_MERGE_FINAL_TAIL','0')))
    case['combine_double_tma']=int(os.environ.get('CXI_EP_COMBINE_DOUBLE_TMA','0'))
    case['skip_combine_flush']=int(os.environ.get('CXI_EP_SKIP_COMBINE_FLUSH','0'))
    case['local_self_signal']=int(os.environ.get('CXI_EP_LOCAL_SELF_SIGNAL','0'))
    case['combine_first_tail']=int(os.environ.get('CXI_EP_COMBINE_FIRST_TAIL','0'))
    case['combine_split_barrier']=int(os.environ.get('CXI_EP_COMBINE_SPLIT_BARRIER','0'))
    case['variant']=os.environ.get('CXI_VARIANT','')
    case['combine_first_batch']=int(os.environ.get('CXI_EP_COMBINE_FIRST_BATCH',os.environ.get('CXI_EP_COMBINE_BATCH','16')))
    case['first_interval']=int(os.environ.get('CXI_EP_FIRST_INTERVAL',os.environ.get('CXI_EP_UPDATE_INTERVAL','3')))
    case['packed_combine']=bool(int(os.environ.get('CXI_EP_PACK_COMBINE','0')))
    case['combine_batch']=int(os.environ.get('CXI_EP_COMBINE_BATCH','16'))
    case['packed_remote_rows']=bool(int(os.environ.get('CXI_EP_PACK_ROWS','0')))
    case['progress_update_interval']=int(os.environ.get('CXI_EP_UPDATE_INTERVAL','3'))
    case['forward_chunk']=int(os.environ.get('CXI_EP_FORWARD_CHUNK',str(case['progress_update_interval'])))
    owners=idx//(e//ep)
    delivered=[(owners==d).any(1).sum().item() for d in range(ep)]
    remote=((owners>=0)&(owners//4!=rank//4)).any(1).sum().item()
    record(out/f'correctness-rank{rank}.jsonl',case|dict(status='PASS',received_rows=count,
        padded_expert_counts=list(counts),unique_destination_gpu_rows=delivered,
        unique_remote_node_rows=remote,float_combine=errors))
    combine_expected=expected.clone()
    # Cycle uses constant expert outputs: no GEMM or output reordering enters the timer.
    cycle_y=torch.ones_like(y)
    def cycle():
        rr=b.dispatch(x,idx,w)
        hh=rr[4] if args.backend=='uccl' else rr[3]
        return b.combine(cycle_y,hh,rr[2])
    diagnostic_watch.mark('cycle_check_host_enter', operation='cycle_check')
    cy,_,_=cycle()
    diagnostic_watch.mark('cycle_check_host_return')
    expected=((owners[:,:,None]==torch.arange(ep,device='cuda')[None,None,:]).any(1).sum(1))
    equal(cy,expected[:,None].expand(n,h).to(torch.bfloat16),'cycle')
    funcs={'dispatch_fresh':lambda:b.dispatch(x,idx,w),
           'dispatch_cached':lambda:b.dispatch(x,idx,w,handle),
           'combine':lambda:b.combine(y,handle,rw),'cycle':cycle}
    for op,fn in funcs.items():
        diagnostic_watch.mark('operation_begin', operation=op)
        samples=measure(fn,args)
        record(out/f'timings-rank{rank}.jsonl',case|dict(operation=op,**samples))
        if ep==8 and seed==args.seeds[0] and n==4096 and args.nic_iters:
            nic_window(fn,args,out,case|dict(operation=op))
    if os.getenv('CXI_DEVICE_TRACE')=='1':
        from trace_capture import capture as capture_device
        capture_device(b,funcs,args,out,case,ref,combine_expected,w)
    if args.profile_steps and seed==args.seeds[0] and n==4096 and dtype=='fp8':
        from profile_capture import capture
        capture(b,funcs,args,out,case)
    diagnostic_watch.mark('buffer_destroy_sync_enter')
    torch.cuda.synchronize(); dist.barrier()
    diagnostic_watch.mark('buffer_destroy_enter')
    if args.backend!='uccl': b.buf.destroy()   # the UCCL buffer lives until the process exits (see _UCCL_BUFFERS)
    diagnostic_watch.mark('buffer_destroy_return')
    print('CASE_PASS',model,n,dtype,routing,seed,rank,flush=True)

def main(args):
    local=int(os.environ['LOCAL_RANK']); affinity=bind_cpu(local)
    torch.cuda.set_device(local)
    # DeepEP's import-time runtime guard matches loaded libnccl* paths broadly.
    # Import before process-group setup loads the OFI NCCL network plugin, as in
    # the historical working benchmark. Do not disable the runtime safety check.
    if args.backend=='deepep':
        import deep_ep
    dist.init_process_group('nccl',device_id=torch.device('cuda',local))
    rank,ep=dist.get_rank(),dist.get_world_size(); out=Path(args.output); out.mkdir(parents=True,exist_ok=True)
    if os.getenv('CXI_DEVICE_TRACE')=='1':
        from trace_capture import initialize
        initialize()
    diagnostic_watch.start(out,rank)
    source=os.environ['UCCL_WORK']+'/source' if args.backend=='uccl' else os.environ.get('DEEPEP_SOURCE',os.environ['DEEPEP_WORK']+'/DeepEP-ep8')
    manifest=dict(args=vars(args),rank=rank,ep=ep,hostname=os.uname().nodename,affinity=affinity,
        torch=torch.__version__,cuda=torch.version.cuda,job=os.getenv('SLURM_JOB_ID'),
        host_io=dict(local_logs=os.getenv('CXI_LOCAL_LOGS','0'),local_jit=os.getenv('CXI_LOCAL_JIT','0'),
                     local_results=os.getenv('CXI_LOCAL_RESULTS','0')),
        **(source_metadata(source,os.environ['UCCL_WORK']+'/source-manifest.json','UCCL') if args.backend=='uccl' else
           source_metadata(source,os.environ.get('DEEPEP_WORK','')+'/source-manifest.json','DeepEP')),
        script_hashes={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in Path(__file__).parent.glob('*.py')},
        environment={k:v for k,v in os.environ.items() if k.startswith(('NCCL_','FI_','UCCL_','EP_','OFI_'))})
    record(out/f'manifest-rank{rank}.jsonl',manifest)
    for seed in args.seeds:
        for model in args.models:
            for n in args.tokens:
                for dtype in args.dtypes:
                    for routing in args.routing:
                        try:
                            run_case(args,model,n,dtype,routing,seed,out)
                        except Exception:
                            record(out/f'failures-rank{rank}.jsonl',dict(model=model,n=n,dtype=dtype,
                                routing=routing,seed=seed,traceback=traceback.format_exc()))
                            if os.getenv('CXI_LOCAL_RESULTS') == '1':
                                import result_spool
                                result_spool.finish()
                            raise
                        gc.collect(); torch.cuda.empty_cache()
    if os.getenv('CXI_LOCAL_RESULTS') == '1':
        import result_spool
        result_spool.finish()
    diagnostic_watch.finish()
    (out/f'libraries-rank{rank}.txt').write_text(Path('/proc/self/maps').read_text())
    dist.barrier(); (out/f'DONE-rank{rank}').write_text('success\n'); dist.barrier()
    if rank==0:
        from summarize import summarize
        summarize(out)
    if args.backend=='uccl':
        # Upstream's own benchmark never tears the UCCL buffer down either: results are written and
        # synchronised, then the process exits without destroying the proxy or the process group.
        dist.barrier(); torch.cuda.synchronize(); os._exit(0)
    dist.destroy_process_group()

if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--backend',choices=['uccl','deepep'],required=True)
    p.add_argument('--output',required=True)
    p.add_argument('--models',nargs='+',choices=list(MODELS),default=list(MODELS))
    p.add_argument('--tokens',nargs='+',type=int,default=[4096])
    p.add_argument('--seeds',nargs='+',type=int,default=[1,2,3])
    p.add_argument('--dtypes',nargs='+',choices=['fp8','bf16'],default=['fp8','bf16'])
    p.add_argument('--routing',nargs='+',type=bank_routing.routing_name,default=['uniform','mixed'])
    p.add_argument('--sms',type=int,default=64)
    p.add_argument('--nvl-chunk',type=int,default=8)
    p.add_argument('--rdma-chunk',type=int,default=16)
    p.add_argument('--combine-nvl-chunk',type=int,default=None,help='UCCL combine config (default: the dispatch chunks)')
    p.add_argument('--combine-rdma-chunk',type=int,default=None)
    p.add_argument('--warmup',type=int,default=20)
    p.add_argument('--iters',type=int,default=100)
    p.add_argument('--nic-iters',type=int,default=100)
    p.add_argument('--profile-steps',type=int,default=0)
    _a=p.parse_args()
    if _a.combine_nvl_chunk is None: _a.combine_nvl_chunk=_a.nvl_chunk
    if _a.combine_rdma_chunk is None: _a.combine_rdma_chunk=_a.rdma_chunk
    with torch.inference_mode(): main(_a)
