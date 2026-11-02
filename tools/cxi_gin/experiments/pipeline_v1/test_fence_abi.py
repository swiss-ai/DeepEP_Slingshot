"""Compare private GPU command types with installed libcxi in separate TUs."""
import hashlib
import json
import subprocess
import sys
from pathlib import Path

source, out = map(Path, sys.argv[1:])
out.mkdir(parents=True, exist_ok=False)
(out / 'candidate.cc').write_text('''#include "cxi_fence_command.h"
extern "C" void candidate_fence(uint64_t* words) {cxi_build_fence_command(words);}
''')
(out / 'reference.cc').write_text('''#include <cstring>
#include <cstdio>
#include <libcxi/libcxi.h>
extern "C" void candidate_fence(uint64_t*);
int main() {
  cxi_cmd32 storage[128]{};cxi_cq queue{};
  queue.cmds32=storage;queue.wp32=queue.hw_wp32=queue.rp32=8;queue.size32=128;
  if(cxi_cq_emit_cq_cmd(&queue,C_CMD_CQ_FENCE))return 1;
  uint64_t actual[8];candidate_fence(actual);
  if(queue.wp32!=10 || memcmp(actual,&storage[8],64))return 2;
  for(auto value:actual)printf("%016llx",(unsigned long long)value);
  puts("");
}
''')
common = ['g++', '-std=c++17', '-Wall', '-Wextra', '-Werror']
subprocess.check_call(common + ['-I'+str(source/'backend/device'), '-I'+str(source/'backend/include'),
    '-c', str(out/'candidate.cc'), '-o', str(out/'candidate.o')])
# Deliberately omit the private include paths from the reference translation unit.
subprocess.check_call(common + [str(out/'reference.cc'), str(out/'candidate.o'), '-o', str(out/'compare')])
encoding = subprocess.check_output([str(out/'compare')]).decode().strip()
paths = [source/'backend/include/cassini_user_defs.h', source/'backend/device/cxi_fence_command.h',
         Path('/usr/include/cassini_user_defs.h'), Path('/usr/include/cxi_prov_hw.h')]
result = dict(status='PASS', scope='separate-TU private vs installed command encoding; no hardware ordering test',
              command_words_hex=encoding,
              inputs={str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths})
(out/'result.json').write_text(json.dumps(result, indent=2)+'\n')
print(json.dumps(result, indent=2))
