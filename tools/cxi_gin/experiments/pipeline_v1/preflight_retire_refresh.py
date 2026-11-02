"""Compile the lifecycle-only host delta; audit unchanged GPU/runtime inputs."""
import hashlib,json,os,subprocess,sys
from pathlib import Path

source=Path(sys.argv[1]).resolve();campaign=source.parent.parent
parent=campaign/'sources/source-marker-probe-v3'
assert (campaign/'preflight'/parent.name/'PASS').is_file()
def verify(root,name):
 d=json.loads((root/name).read_text())
 for k,h in d['files'].items():assert hashlib.sha256((root/k).read_bytes()).hexdigest()==h,(root,k)
 return d
a=verify(parent,'manifest.json')['files'];b=verify(source,'manifest.json')['files']
assert set(a)==set(b)
assert {k for k in a if a[k]!=b[k]}=={'backend/host/cxi_resources.cc','runner/validate_gate.py','sequence.json'}
compile((source/'runner/validate_gate.py').read_text(),'validate_gate.py','exec')
runtime=campaign/'runtime'/source.name
if runtime.is_symlink():
 assert runtime.resolve()==(campaign/'runtime'/parent.name).resolve()
else:
 assert not runtime.exists()
 runtime.symlink_to(parent.name,target_is_directory=True)
for variant in json.loads((source/'variants.json').read_text()):
 assert (runtime/variant).resolve()==(campaign/'runtime'/parent.name/variant).resolve()
 verify(runtime/variant,'runtime-manifest.json')
out=campaign/'preflight'/source.name;out.mkdir(exist_ok=True)
temporary=out/'tmp';temporary.mkdir(exist_ok=True);os.environ['TMPDIR']=str(temporary)
sdk=Path('/iopsstor/scratch/cscs/zyu/deepep-direct-20261026/cuda-sdk/usr/local/cuda-13.0')
command=['g++','-std=c++17','-Wall','-Wextra','-Werror','-Wno-misleading-indentation',
 '-I'+str(sdk/'include'),'-I'+str(source/'backend/include'),'-c',str(source/'backend/host/cxi_resources.cc'),'-o',str(out/'resources.o')]
subprocess.check_call(command)
check=out/'cq_status_check.cc'
check.write_text('''#include <cstring>
#include <libcxi/libcxi.h>
#include <cstdint>
#include <cstring>
#include <cassert>
static bool valid(uint64_t raw) {
  c_cq_status s{};static_assert(sizeof(s)==sizeof(raw), "CQ status ABI");
  memcpy(&s,&raw,sizeof(s));
  return !s.num_write_cmds_rejected && !s.fail_command && s.return_code==C_RC_OK;
}
int main() {
  // Actual status captured from gate1603; successful queue consumption.
  assert(valid(281474976710916ULL));
  c_cq_status s{};uint64_t raw=0;s.return_code=C_RC_OK;s.rd_ptr=130;
  memcpy(&raw,&s,sizeof(raw));assert(valid(raw));
  s.return_code=C_RC_UNDELIVERABLE;memcpy(&raw,&s,sizeof(raw));assert(!valid(raw));
  s.return_code=C_RC_OK;s.num_write_cmds_rejected=1;memcpy(&raw,&s,sizeof(raw));assert(!valid(raw));
  s.num_write_cmds_rejected=0;s.fail_command=1;memcpy(&raw,&s,sizeof(raw));assert(!valid(raw));
  assert(!valid(0));return 0;
}
''')
subprocess.check_call(['g++','-std=c++17','-Wall','-Wextra','-Werror',str(check),'-o',str(out/'cq_status_check')])
subprocess.check_call([str(out/'cq_status_check')])
(out/'compile-equivalence.json').write_text(json.dumps(dict(parent=str(parent),changed=['backend/host/cxi_resources.cc','runner/validate_gate.py','sequence.json'],
 command=command,runtime_alias=str(runtime.resolve()),scope='Host teardown-only delta compiled; every GPU/ABI/DeepEP/runtime input unchanged; GPU lifecycle qualification pending'),indent=2)+'\n')
(out/'PASS').write_text('Host lifecycle delta compiles; unchanged GPU/runtime inputs verified; no GPU qualification asserted\n')
print('PASS host retirement refresh compiles; GPU datapath and runtimes unchanged',flush=True)
