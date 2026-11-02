"""Local phase journal with an independent copier; no CUDA or NIC progress.

GPU diagnostic polling is advisory: its Python thread can be delayed by the GIL.
Phase markers reach tmpfs before entering a blocking extension call. A separate
stdlib-only interpreter copies them to the shared result directory every 100ms.
"""
import ctypes
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time

_fd=None
_thread=None
_child=None
_lock=threading.Lock()
_stop=threading.Event()
_context={}
_sequence=0
_bytes=0
_error=None
_limit=64*1024*1024
_local=None


def mark(phase, **context):
    global _sequence,_bytes
    if _fd is None:return
    with _lock:
        if _error is not None:raise RuntimeError('diagnostic observer failed: '+repr(_error))
        if _child is not None and _child.poll() is not None:
            raise RuntimeError('independent phase copier exited early')
        _context.update(context)
        data=(json.dumps(dict(_context,phase=phase,monotonic_ns=time.monotonic_ns(),sequence=_sequence))+'\n').encode()
        if _bytes+len(data)>_limit:raise RuntimeError('local phase journal capacity exceeded')
        view=memoryview(data)
        while view:
            n=os.write(_fd,view)
            if n<=0:raise RuntimeError('phase journal write made no progress')
            view=view[n:]
        _bytes+=len(data);_sequence+=1


def copy_journal(local,output,parent):
    local=Path(local);stop=Path(str(local)+'.stop')
    with local.open('rb',buffering=0) as src,open(output,'xb',buffering=0) as dst:
        while True:
            ending=stop.exists() or os.getppid()!=parent
            while True:
                block=src.read(1024*1024)
                if not block:break
                view=memoryview(block)
                while view:
                    n=dst.write(view)
                    if not n:raise RuntimeError('shared phase journal write made no progress')
                    view=view[n:]
            if ending:return
            time.sleep(.1)


def start(output,rank):
    global _fd,_thread,_child,_local
    if os.environ.get('CXI_DIAGNOSTIC_WATCHDOG')!='1':return
    assert _fd is None and _thread is None
    library=ctypes.CDLL(os.environ['NCCL_GIN_PLUGIN'])
    query=library.cxiGinLastDiagnostic;query.argtypes=[];query.restype=ctypes.c_uint64
    _fd,path=tempfile.mkstemp(prefix='deepep-phase-rank%d-'%rank,suffix='.jsonl',dir='/dev/shm')
    _local=Path(path)
    output=Path(output)/('diagnostic-watch-rank%d.jsonl'%rank)
    _child=subprocess.Popen([sys.executable,__file__,'--copy',str(_local),str(output),str(os.getpid())],stdin=subprocess.DEVNULL)
    mark('observer_started',rank=rank,local_journal=str(_local),copier_pid=_child.pid,
         purpose='local host phase journal; independent copier; no NIC progress',
         gpu_polling_may_be_delayed_by_gil=True)
    def observe():
        global _error
        try:
            while not _stop.wait(.1):
                code=int(query())
                if code:
                    mark('gpu_diagnostic_observed',diagnostic_code=code)
                    return
        except Exception as error:
            with _lock:_error=error
    _thread=threading.Thread(target=observe,name='advisory-cxi-diagnostic-poll',daemon=True)
    _thread.start()


def finish():
    global _fd
    if _fd is None:return
    _stop.set();_thread.join(timeout=10)
    if _thread.is_alive():raise RuntimeError('diagnostic poller did not stop')
    mark('observer_stopped',thread_stopped=True)
    os.close(_fd);_fd=None
    stop=Path(str(_local)+'.stop');stop.touch(exist_ok=False)
    if _child.wait(timeout=15)!=0:raise RuntimeError('phase copier failed')
    _local.unlink();stop.unlink()


if __name__=='__main__':
    assert len(sys.argv)==5 and sys.argv[1]=='--copy'
    copy_journal(sys.argv[2],sys.argv[3],int(sys.argv[4]))
