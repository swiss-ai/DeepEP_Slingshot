#!/usr/bin/env python3
"""Retain ptxas register/spill reports; inject pointer only for private traces."""
import os,subprocess,sys,uuid
from pathlib import Path
args=sys.argv[1:]
if '--version' not in args:
    args=['--ptxas-options=-v']+args
    pointer=int(os.getenv('EP_TRACE_DEVICE_PTR','0'))
    if pointer:args=['-DEP_TRACE_PTR='+str(pointer)+'ULL']+args
p=subprocess.run(['/usr/local/cuda/bin/nvcc']+args,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
sys.stdout.buffer.write(p.stdout);sys.stderr.buffer.write(p.stderr)
if '--version' not in args:
    d=Path(os.environ['EP_JIT_CACHE_DIR'])/'compiler-reports';d.mkdir(parents=True,exist_ok=True)
    (d/(uuid.uuid4().hex+'.txt')).write_bytes((' '.join(args)+'\n').encode()+p.stdout+p.stderr)
sys.exit(p.returncode)
