#!/usr/bin/env python3
"""Inject a process-specific trace pointer into an isolated JIT cache only."""
import os
import sys
from pathlib import Path
args=sys.argv[1:]
if '--version' not in args:
    pointer=int(os.environ['EP_TRACE_DEVICE_PTR'])
    assert pointer>0 and pointer%8==0
    args=['-include',str(Path(__file__).with_name('device_trace.cuh')),
          '-DEP_TRACE_PTR='+str(pointer)+'ULL']+args
os.execv('/usr/local/cuda/bin/nvcc',['nvcc']+args)
