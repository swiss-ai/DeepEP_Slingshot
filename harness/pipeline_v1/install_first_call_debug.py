"""Audit and reuse identical compiled inputs for a host journal diagnostic."""
import hashlib,json,subprocess,sys
from pathlib import Path

source=Path(sys.argv[1]).resolve();job=sys.argv[2];assert job.isdigit()
campaign=source.parent.parent;parent=campaign/'sources/source-retire-refresh-v2'
runtime=campaign/'runtime'/source.name;assert not runtime.exists()
runtime.symlink_to(parent.name,target_is_directory=True)
subprocess.check_call([sys.executable,str(campaign/'preflight_diagnostic_update_v2.py'),str(source),str(parent)])
base=campaign/'jobs'/job/'builds';dest=base/source.name/'marker-zero';assert not dest.exists()
dest.mkdir(parents=True);records=[]
for node in range(2):
 old=base/parent.name/'marker-zero'/('node%d'%node)
 assert (old/'PASS').is_file()
 record=json.loads((old/'build.json').read_text());binary=Path(record['extension'])
 assert hashlib.sha256(binary.read_bytes()).hexdigest()==record['sha256']
 (dest/('node%d'%node)).symlink_to(old,target_is_directory=True)
 records.append(dict(node=node,parent=str(old),binary_sha256=record['sha256']))
(dest/'NATIVE_BUILD_REUSE.json').write_text(json.dumps(dict(records=records,
 scope='Observer-only Python changes; unchanged native compilation and runtime inputs'),indent=2)+'\n')
print('PASS exact native/runtime equivalence; host phase journal GPU replay pending')
