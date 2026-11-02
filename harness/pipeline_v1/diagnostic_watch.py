"""Read-only host diagnostics for a failing run; never advances NIC queues.

Phase records describe host entry/return, not GPU completion. This observer is
for reproduction only, and its timings must not be promoted as performance.
"""
import ctypes
import json
import os
import threading
import time
from pathlib import Path

_file = None
_lock = threading.Lock()
_stop = threading.Event()
_thread = None
_context = {}


def mark(phase, **context):
    if _file is None:
        return
    with _lock:
        _context.update(context)
        row = dict(_context, phase=phase, monotonic_ns=time.monotonic_ns())
        _file.write(json.dumps(row) + '\n')
        _file.flush()


def start(output, rank):
    global _file, _thread
    if os.environ.get('CXI_DIAGNOSTIC_WATCHDOG') != '1':
        return
    assert _file is None
    library = ctypes.CDLL(os.environ['NCCL_GIN_PLUGIN'])
    query = library.cxiGinLastDiagnostic
    query.argtypes = []
    query.restype = ctypes.c_uint64
    _file = (Path(output) / ('diagnostic-watch-rank%d.jsonl' % rank)).open('x')
    mark('observer_started', rank=rank, purpose='diagnostic only; host timestamps; no NIC progress')

    def observe():
        # The exported query only reads mapped diagnostic pages and holds the
        # plugin's resource-lifetime lock. It does not call CUDA or ring a NIC.
        while not _stop.wait(.1):
            code = int(query())
            if code:
                mark('gpu_diagnostic_observed', diagnostic_code=code)
                print('CXI_DIAGNOSTIC_WATCH rank=%d code=%d' % (rank, code), flush=True)
                return

    _thread = threading.Thread(target=observe, name='read-only-cxi-diagnostics', daemon=True)
    _thread.start()


def finish():
    global _file
    if _file is None:
        return
    _stop.set()
    _thread.join(timeout=2)
    mark('observer_stopped', thread_stopped=not _thread.is_alive())
    if not _thread.is_alive():
        _file.close()
        _file = None
