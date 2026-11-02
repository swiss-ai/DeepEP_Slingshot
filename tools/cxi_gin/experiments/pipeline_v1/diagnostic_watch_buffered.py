"""Buffered host phase history; the submitting thread performs no file I/O.

The observer only reads mapped CXI diagnostics. It never advances NIC queues or
calls CUDA. Timings remain diagnostic, not ordinary benchmark evidence.
"""
import ctypes
import json
import os
import threading
import time
from collections import deque
from pathlib import Path

_file=None
_lock=threading.Lock()
_stop=threading.Event()
_thread=None
_context={}
_pending=deque()
_error=None
_sequence=0
_limit=65536


def mark(phase, **context):
    global _sequence
    if _file is None:return
    with _lock:
        if _error is not None:raise RuntimeError('diagnostic writer failed: '+repr(_error))
        if len(_pending)>=_limit:raise RuntimeError('diagnostic buffer overflow; no records silently dropped')
        _context.update(context)
        _pending.append(dict(_context,phase=phase,monotonic_ns=time.monotonic_ns(),sequence=_sequence))
        _sequence+=1


def drain():
    with _lock:
        rows=list(_pending);_pending.clear()
    if rows:
        _file.write(''.join(json.dumps(row)+'\n' for row in rows));_file.flush()


def start(output,rank):
    global _file,_thread
    if os.environ.get('CXI_DIAGNOSTIC_WATCHDOG')!='1':return
    assert _file is None and _thread is None
    library=ctypes.CDLL(os.environ['NCCL_GIN_PLUGIN'])
    query=library.cxiGinLastDiagnostic;query.argtypes=[];query.restype=ctypes.c_uint64
    _file=(Path(output)/('diagnostic-watch-rank%d.jsonl'%rank)).open('x')
    mark('observer_started',rank=rank,purpose='buffered host diagnostics only; no NIC progress',buffered=True)
    def observe():
        global _error
        diagnosed=False
        try:
            while True:
                stopping=_stop.wait(.1)
                if not stopping and not diagnosed:
                    code=int(query())
                    if code:
                        mark('gpu_diagnostic_observed',diagnostic_code=code)
                        diagnosed=True
                drain()
                if stopping:return
        except Exception as error:
            with _lock:_error=error
    _thread=threading.Thread(target=observe,name='buffered-read-only-cxi-diagnostics',daemon=True)
    _thread.start()


def finish():
    global _file
    if _file is None:return
    _stop.set();_thread.join(timeout=10)
    if _thread.is_alive():raise RuntimeError('diagnostic writer did not stop; log is incomplete')
    mark('observer_stopped',thread_stopped=True)
    drain();_file.close();_file=None
