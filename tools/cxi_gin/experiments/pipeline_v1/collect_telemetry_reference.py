"""Read-only NIC/header inventory on allocated hosts; not a performance sample."""
import hashlib
import json
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path


def main():
    root=Path(sys.argv[1])/socket.gethostname();root.mkdir(parents=True,exist_ok=False)
    headers=['cassini-telemetry-items.h','cassini-telemetry-sysfs-defs.h',
             'cassini_cntr_defs.h','cassini_cntr_desc.h']
    hashes={}
    for name in headers:
        source=Path('/usr/include')/name;shutil.copyfile(source,root/name)
        hashes[name]=hashlib.sha256((root/name).read_bytes()).hexdigest()
    ports={}
    for nic in sorted(Path('/sys/class/cxi').glob('cxi[0-9]*')):
        directory=nic/'device/telemetry'
        ports[nic.name]=dict(telemetry_names=sorted(p.name for p in directory.iterdir()),
            cxi_stat=subprocess.check_output(['cxi_stat','-d',nic.name]).decode())
    record=dict(host=socket.gethostname(),epoch=time.time(),headers=hashes,ports=ports,
                scope='Installed counter descriptions, available names and link configuration only; no measured operation window')
    (root/'inventory.json').write_text(json.dumps(record,indent=2)+'\n')
    print(json.dumps(dict(host=record['host'],ports=list(ports),output=str(root))))


if __name__=='__main__':main()
