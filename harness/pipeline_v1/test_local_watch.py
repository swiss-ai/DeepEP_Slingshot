import ctypes
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

with tempfile.TemporaryDirectory() as tmp:
    root=Path(tmp)
    (root/'diag.c').write_text('unsigned long long cxiGinLastDiagnostic(void){return 0;}')
    subprocess.check_call(['cc','-shared','-fPIC',str(root/'diag.c'),'-o',str(root/'diag.so')])
    os.environ.update(CXI_DIAGNOSTIC_WATCHDOG='1',NCCL_GIN_PLUGIN=str(root/'diag.so'))
    spec=importlib.util.spec_from_file_location('watch',Path(__file__).with_name('diagnostic_watch_local.py'))
    w=importlib.util.module_from_spec(spec);spec.loader.exec_module(w)
    w.start(root,0)
    for i in range(10000):w.mark('sample',call_index=i)
    # PyDLL retains the GIL: the independent copier must still drain the journal.
    libc=ctypes.PyDLL(None);libc.usleep.argtypes=[ctypes.c_uint]
    w.mark('before_gil_hold');before=time.time_ns();libc.usleep(800000)
    destination=root/'diagnostic-watch-rank0.jsonl'
    rows=[json.loads(x) for x in destination.read_text().splitlines()]
    assert rows[-1]['phase']=='before_gil_hold'
    assert before<=destination.stat().st_mtime_ns
    w.finish()
    rows=[json.loads(x) for x in destination.read_text().splitlines()]
    assert len(rows)==10003 and [r['sequence'] for r in rows]==list(range(10003))
    assert rows[-1]['phase']=='observer_stopped' and w._child.returncode==0
    assert not w._local.exists()
    print('PASS 10000 ordered markers, independent copy during GIL-held call, clean drain')
