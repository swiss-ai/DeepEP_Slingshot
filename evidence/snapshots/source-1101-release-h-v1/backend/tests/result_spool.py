"""Append benchmark records to tmpfs; a separate process persists them to Lustre.

No CUDA, NCCL or CXI calls. finish() is required before the final result barrier.
The source journal survives copier failure, and completion fails closed.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

_stream = None
_child = None
_local = None
_root = None
_size = 0
_count = 0
_limit = 64 * 1024 * 1024


def record(path, obj):
    global _stream, _child, _local, _root, _size, _count
    path = Path(path).resolve()
    if _stream is None:
        _root = path.parent
        fd, name = tempfile.mkstemp(prefix='deepep-results-rank%s-' % os.environ['RANK'],
                                    suffix='.jsonl', dir='/dev/shm')
        _local = Path(name)
        _stream = os.fdopen(fd, 'wb', buffering=0)
        _child = subprocess.Popen([sys.executable, __file__, '--copy', str(_local),
                                   str(_root), str(os.getpid())], stdin=subprocess.DEVNULL)
    if path.parent != _root or path.suffix != '.jsonl':
        raise ValueError('Result spool accepts JSONL files in one result directory')
    if _child.poll() is not None:
        raise RuntimeError('Result copier exited early; retained journal: ' + str(_local))
    payload = (json.dumps(dict(sequence=_count, name=path.name, record=obj)) + '\n').encode()
    if _size + len(payload) > _limit:
        raise RuntimeError('Result journal exceeded bounded capacity')
    view = memoryview(payload)
    while view:
        n = _stream.write(view)
        if not n:
            raise RuntimeError('Result journal write made no progress')
        view = view[n:]
    _size += len(payload)
    _count += 1


def finish():
    global _stream
    if _stream is None:
        return
    _stream.close()
    _stream = None
    stop = Path(str(_local) + '.stop')
    stop.write_text(str(_count))
    if _child.wait(timeout=120) != 0:
        raise RuntimeError('Result copier failed; retained journal: ' + str(_local))
    ack = Path(str(_local) + '.ack')
    if int(ack.read_text()) != _count:
        raise RuntimeError('Incomplete result persistence')
    _local.unlink()
    stop.unlink()
    ack.unlink()


def copy_records(local, root, parent):
    local, root = Path(local), Path(root)
    stop = Path(str(local) + '.stop')
    count = 0
    pending = b''
    with local.open('rb', buffering=0) as src:
        while True:
            ending = stop.exists() or os.getppid() != parent
            while True:
                block = src.read(1024 * 1024)
                if not block:
                    break
                pending += block
                lines = pending.split(b'\n')
                pending = lines.pop()
                for line in lines:
                    row = json.loads(line.decode())
                    name = row['name']
                    assert Path(name).name == name and name.endswith('.jsonl')
                    assert row['sequence'] == count
                    with (root / name).open('a') as dst:
                        dst.write(json.dumps(row['record']) + '\n')
                    count += 1
            if ending:
                if stop.exists():
                    assert not pending and count == int(stop.read_text())
                # If the parent was killed mid-write, retain the partial journal
                # and persist only complete records; no PASS is manufactured.
                Path(str(local) + '.ack').write_text(str(count))
                return
            time.sleep(.1)


if __name__ == '__main__':
    assert len(sys.argv) == 5 and sys.argv[1] == '--copy'
    copy_records(sys.argv[2], sys.argv[3], int(sys.argv[4]))
