"""Check lossless asynchronous phase logging and read-only diagnostic reporting."""
import importlib.util
import json
import os
import tempfile
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


class Query:
    def __init__(self,code):self.code=code;self.calls=0
    def __call__(self):self.calls+=1;return self.code


def main():
    path=Path(__file__).with_name('diagnostic_watch_buffered.py')
    for code in [0,7]:
        spec=importlib.util.spec_from_file_location('watch_case_'+str(code),path)
        watch=importlib.util.module_from_spec(spec);spec.loader.exec_module(watch)
        query=Query(code)
        with tempfile.TemporaryDirectory(prefix='cxi-buffered-watch-') as directory:
            with patch.dict(os.environ,{'CXI_DIAGNOSTIC_WATCHDOG':'1','NCCL_GIN_PLUGIN':'mock-read-only'}), \
                 patch.object(watch.ctypes,'CDLL',return_value=SimpleNamespace(cxiGinLastDiagnostic=query)):
                watch.start(directory,0)
                wrapped=watch._file;submitting=True
                class ObservedFile:
                    def write(self,value):
                        assert not (submitting and threading.current_thread()==threading.main_thread())
                        return wrapped.write(value)
                    def flush(self):return wrapped.flush()
                    def close(self):return wrapped.close()
                watch._file=ObservedFile()
                for index in range(5000):watch.mark('call',call_index=index)
                time.sleep(.25)
                submitting=False;watch.finish()
            rows=[json.loads(line) for line in (Path(directory)/'diagnostic-watch-rank0.jsonl').read_text().splitlines()]
            assert rows[0]['phase']=='observer_started' and rows[-1]['phase']=='observer_stopped'
            assert rows[-1]['thread_stopped'] and not watch._thread.is_alive()
            assert [r['sequence'] for r in rows]==list(range(len(rows)))
            assert [r['call_index'] for r in rows if r['phase']=='call']==list(range(5000))
            assert all(a['monotonic_ns']<=b['monotonic_ns'] for a,b in zip(rows,rows[1:]))
            assert [r['diagnostic_code'] for r in rows if r['phase']=='gpu_diagnostic_observed']==([code] if code else [])
            assert query.calls>0
    print('PASS 10000 buffered markers, ordered/lossless output, no submitting-thread file writes, diagnostic error observation')


if __name__=='__main__':main()
