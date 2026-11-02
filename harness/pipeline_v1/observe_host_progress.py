"""Read own benchmark process state and tmpfs journals; no CUDA/NIC operations.

Run inside the existing allocation as a small overlapping CPU-only step. Only
the matching benchmark's RANK environment value is reported, never its full
environment or command line. Process roots locate the container's tmpfs journal.
"""
import argparse,json,os,socket,time
from pathlib import Path

p=argparse.ArgumentParser();p.add_argument('--snapshot',required=True)
p.add_argument('--duration',type=int,default=20);p.add_argument('--interval',type=float,default=2)
args=p.parse_args();assert Path(args.snapshot).name==args.snapshot
assert 1<=args.duration<=50 and .5<=args.interval<=10
target='/sources/'+args.snapshot+'/backend/tests/ep_benchmark.py'
host=socket.gethostname();until=time.monotonic()+args.duration;previous={}
while True:
 for proc in Path('/proc').iterdir():
  if not proc.name.isdigit():continue
  try:
   if proc.stat().st_uid!=os.getuid():continue
   command=(proc/'cmdline').read_bytes().split(b'\0')
   if b'-u' not in command or not any(x.decode(errors='replace').endswith(target) for x in command):continue
   # Whitelist one nonsecret field from the identified benchmark process.
   rank=None
   for field in (proc/'environ').read_bytes().split(b'\0'):
    if field.startswith(b'RANK='):rank=int(field[5:]);break
   if rank is None:continue
   state=dict(host=host,pid=int(proc.name),rank=rank,wchan=(proc/'wchan').read_text().strip())
   if b'--output' in command:
    result_dir=command[command.index(b'--output')+1].decode(errors='replace')
    if '/deepep-pipeline-20261030/jobs/' in result_dir:state['result_directory']=result_dir
   try:state['syscall']=(proc/'syscall').read_text().strip()
   except OSError as error:state['syscall_error']=str(error)
   # An earlier failed attempt can leave a same-rank tmpfs journal behind.
   # Only attribute a journal that this exact process currently has open.
   files=[];results=[]
   for fd in (proc/'fd').iterdir():
    try:name=os.readlink(str(fd))
    except OSError:continue
    if name.startswith('/dev/shm/deepep-phase-rank%d-'%rank) and name.endswith('.jsonl'):
     files.append(proc/'root'/name.lstrip('/'))
    if name.startswith('/dev/shm/deepep-results-rank%d-'%rank) and name.endswith('.jsonl'):
     results.append(proc/'root'/name.lstrip('/'))
   for result in results:
    with result.open('rb') as f:
     f.seek(0,2);size=f.tell();f.seek(max(0,size-32768));lines=f.read().splitlines()
    for line in reversed(lines):
     try:entry=json.loads(line.decode());break
     except (ValueError,UnicodeError):continue
    else:entry={}
    row=entry.get('record',{})
    state['local_result_tail']=dict(sequence=entry.get('sequence'),name=entry.get('name'),
     **{key:row.get(key) for key in ['tokens_per_gpu','dispatch_dtype','routing','seed','operation']})
   if files:
    latest=max(files,key=lambda f:f.stat().st_mtime_ns)
    with latest.open('rb') as f:
     f.seek(0,2);size=f.tell();f.seek(max(0,size-16384));lines=f.read().splitlines()
    for line in reversed(lines):
     try:row=json.loads(line.decode());break
     except (ValueError,UnicodeError):continue
    else:row={}
    state.update(phase=row.get('phase'),operation=row.get('operation'),call_index=row.get('call_index'),sequence=row.get('sequence'),tokens=row.get('tokens'),dtype=row.get('dtype'),routing=row.get('routing'),journal=str(latest))
   opened=[];kernels={}
   for fd in (proc/'fd').iterdir():
    try:name=os.readlink(str(fd))
    except OSError:continue
    owned='/deepep-pipeline-20261030/' in name or name.startswith('/dev/shm/deepep-jit-')
    if owned and any(x in Path(name).name for x in ['timings-rank','correctness-rank','kernel.','compiler','smoke.log']):
     opened.append(name)
     if Path(name).name=='kernel.cu':
      try:
       # Only generated kernel identity, never arbitrary process/file contents.
       with fd.open('rb') as src:code=src.read(4096).decode(errors='replace')
       kernels[name]=[line.strip() for line in code.splitlines() if '#include <deep_ep/impls/' in line or 'auto ptr = reinterpret_cast' in line]
      except OSError:pass
   state['open_result_files']=sorted(set(opened))
   state['generated_kernel_identity']=kernels
   key=(host,rank)
   if previous.get(key)!=state:
    previous[key]=state
    print(json.dumps(dict(state,observed_monotonic_ns=int(time.monotonic()*1e9))),flush=True)
  except (OSError,ValueError) as error:
   # Process exit and restricted proc visibility are observation limits.
   if 'state' in locals() and state.get('pid')==int(proc.name):
    print(json.dumps(dict(host=host,pid=int(proc.name),observation_error=str(error))),flush=True)
 if time.monotonic()>=until:break
 time.sleep(args.interval)
