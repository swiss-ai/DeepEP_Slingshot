#!/usr/bin/env python3
"""Retain ptxas register/spill reports; inject pointer only for private traces."""
import os,subprocess,sys,uuid
from pathlib import Path
args=sys.argv[1:]
if '--version' not in args:
    args=['--ptxas-options=-v']+args
    merge_final=int(os.environ.get('CXI_EP_MERGE_FINAL_TAIL','0'))
    assert merge_final in (0,1)
    args=['-DCXI_EP_MERGE_FINAL_TAIL='+str(merge_final)]+args
    packc=int(os.environ.get('CXI_EP_PACK_COMBINE','0')); batch=int(os.environ.get('CXI_EP_COMBINE_BATCH','16'))
    first_batch=int(os.environ.get('CXI_EP_COMBINE_FIRST_BATCH',str(batch))); first_interval=int(os.environ.get('CXI_EP_FIRST_INTERVAL',os.environ.get('CXI_EP_UPDATE_INTERVAL','3')))
    assert 1 <= first_batch <= batch and 1 <= first_interval <= 64
    args=['-DCXI_EP_COMBINE_FIRST_BATCH='+str(first_batch),'-DCXI_EP_FIRST_INTERVAL='+str(first_interval)]+args
    skip_flush=int(os.environ.get('CXI_EP_SKIP_COMBINE_FLUSH','0')); self_signal=int(os.environ.get('CXI_EP_LOCAL_SELF_SIGNAL','0'))
    assert skip_flush in (0,1) and self_signal in (0,1)
    args=['-DCXI_EP_SKIP_COMBINE_FLUSH='+str(skip_flush),'-DCXI_EP_LOCAL_SELF_SIGNAL='+str(self_signal)]+args
    first_tail=int(os.environ.get('CXI_EP_COMBINE_FIRST_TAIL','0')); split_barrier=int(os.environ.get('CXI_EP_COMBINE_SPLIT_BARRIER','0'))
    assert 0<=first_tail<=3 and split_barrier in (0,1)
    args=['-DCXI_EP_COMBINE_FIRST_TAIL='+str(first_tail),'-DCXI_EP_COMBINE_SPLIT_BARRIER='+str(split_barrier)]+args
    double_tma=int(os.environ.get('CXI_EP_COMBINE_DOUBLE_TMA','0')); assert double_tma in (0,1)
    args=['-DCXI_EP_COMBINE_DOUBLE_TMA='+str(double_tma)]+args
    assert packc in (0,1) and 1 <= batch <= 64
    channels=4*int(os.environ.get('CXI_EP_SMS','64'))
    args=['-DCXI_EP_PACK_COMBINE='+str(packc),'-DCXI_EP_COMBINE_BATCH='+str(batch),'-DCXI_EP_PACK_COMBINE_CHANNELS='+str(channels)]+args
    packed=int(os.environ.get('CXI_EP_PACK_ROWS','0'))
    assert packed in (0,1)
    args=['-DCXI_EP_PACK_ROWS='+str(packed)]+args
    interval=int(os.environ.get('CXI_EP_UPDATE_INTERVAL','3'))
    forward=int(os.environ.get('CXI_EP_FORWARD_CHUNK',str(interval)))
    assert 1 <= interval <= 64 and 1 <= forward <= 64
    args=['-DCXI_EP_UPDATE_INTERVAL='+str(interval),'-DCXI_EP_FORWARD_CHUNK='+str(forward)]+args
    pointer=int(os.getenv('EP_TRACE_DEVICE_PTR','0'))
    if pointer:args=['-DEP_TRACE_PTR='+str(pointer)+'ULL']+args
p=subprocess.run(['/usr/local/cuda/bin/nvcc']+args,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
sys.stdout.buffer.write(p.stdout);sys.stderr.buffer.write(p.stderr)
if '--version' not in args:
    d=Path(os.environ['EP_JIT_CACHE_DIR'])/'compiler-reports';d.mkdir(parents=True,exist_ok=True)
    (d/(uuid.uuid4().hex+'.txt')).write_bytes((' '.join(args)+'\n').encode()+p.stdout+p.stderr)
sys.exit(p.returncode)
