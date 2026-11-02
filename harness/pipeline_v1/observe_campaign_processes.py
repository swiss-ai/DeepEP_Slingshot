"""Read-only host process inventory for this campaign, including child compilers.

No GPU/NIC APIs, environments, arbitrary arguments or file contents are read.
"""
import json
import os
import socket
from pathlib import Path

processes = {}
for root in Path('/proc').iterdir():
    if not root.name.isdigit() or int(root.name) == os.getpid():
        continue
    try:
        if root.stat().st_uid != os.getuid():
            continue
        args = (root/'cmdline').read_bytes().split(b'\0')
        stat = (root/'stat').read_text().rsplit(')', 1)[1].split()
        processes[int(root.name)] = (root, args, int(stat[1]), stat[0])
    except (OSError, ValueError):
        pass
selected = {pid for pid, (_, args, _, _) in processes.items()
            if any(b'/deepep-pipeline-20261030/' in arg for arg in args)}
while True:
    children = {pid for pid, (_, _, ppid, _) in processes.items() if ppid in selected}
    if children <= selected:
        break
    selected |= children
for pid in sorted(selected):
    root, args, ppid, state = processes[pid]
    try:
        files = []
        for fd in (root/'fd').iterdir():
            try:
                path = os.readlink(str(fd))
            except OSError:
                continue
            if '/deepep-pipeline-20261030/' in path or path.startswith('/dev/shm/deepep-'):
                files.append(dict(fd=int(fd.name), path=path))
        print(json.dumps(dict(host=socket.gethostname(), pid=pid, parent=ppid,
            state=state, name=(root/'comm').read_text().strip(),
            wchan=(root/'wchan').read_text().strip(), files=files)), flush=True)
    except OSError:
        pass
