#!/usr/bin/env python3
"""Prepare an isolated CQ-credit candidate; never modify the qualified backend."""
import argparse
import difflib
import hashlib
import json
from pathlib import Path
import shutil

parser = argparse.ArgumentParser()
parser.add_argument('--base-bundle', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
args = parser.parse_args()
if args.output.exists():
    raise SystemExit('Use a new candidate directory')
manifest = json.loads((args.base_bundle / 'source-manifest.json').read_text())
relative = 'backend/device/cxi_primitives.cuh'
source = args.base_bundle / relative
original = source.read_text()
assert hashlib.sha256(source.read_bytes()).hexdigest() == manifest['backend_sha256'][relative]
start = original.index('// Caller owns the context lock.')
end = original.index('__device__ __forceinline__ bool flush_locked', start)
replacement = '''// Caller owns the context lock. Permit multiple published commands, but never
// overwrite an unconsumed slot. Transfer ACK/flush/signal ordering is unchanged.
__device__ __forceinline__ bool emit(CxiGpuContext& c,const uint64_t* command,bool transfer,
                                   uint32_t* abort=nullptr,uint64_t timeout=default_timeout) {
  uint64_t start=clock64();
  while(true) {
    uint32_t status=load32((uint32_t*)c.tx_queue);
    if(status>>16)return fail(c,3,status);
    int credits=cq_free_slots32(c.tx_size32,c.tx_wp32,(status&65535)*2);
    // Zero is a permitted initial status; its conservative credit count can
    // be negative for a tiny queue, in which case wait for actual writeback.
    if(credits<0 && (status&65535)!=0)return fail(c,46,status,c.tx_wp32);
    if(credits>=2)break;
    if(expired(start,timeout,abort))return fail(c,4,status,c.tx_wp32);
    __nanosleep(64);
  }
  for(unsigned i=0;i<8;i++)c.tx_queue[c.tx_wp32*4+i]=command[i];
  __threadfence_system();unsigned next=c.tx_wp32+2;if(next>=c.tx_size32)next=8;
  store64(c.tx_doorbell,next/2);c.tx_wp32=next;
  if(transfer)c.posted++;return true;
}
'''
candidate = original[:start] + replacement + original[end:]
candidate = candidate.replace('#include "cassini_user_defs.h"',
                              '#include "cassini_user_defs.h"\n#include "cxi_queue_credit.h"', 1)
args.output.mkdir(parents=True)
(args.output / 'cxi_primitives.cuh').write_text(candidate)
shutil.copyfile(Path(__file__).with_name('cxi_queue_credit.h'), args.output / 'cxi_queue_credit.h')
patch = ''.join(difflib.unified_diff(original.splitlines(True), candidate.splitlines(True),
                                   fromfile='a/device/cxi_primitives.cuh', tofile='b/device/cxi_primitives.cuh'))
(args.output / 'candidate.patch').write_text(patch)
record = dict(status='PREPARED_UNQUALIFIED', base_bundle=str(args.base_bundle.resolve()),
              base_primitives_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
              files_sha256={p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                            for p in args.output.iterdir() if p.is_file()},
              change='bounded TX queue credits instead of per-command consumption wait; still ring every command',
              invariants='same ABI, lock, system fence, transfer ACKs, flush-before-signal, host progress policy',
              next='compile in an isolated prefix; raw/public GIN, wrap/concurrency/source-reuse, EP8 and matched profile/timing gates')
(args.output / 'manifest.json').write_text(json.dumps(record, indent=2) + '\n')
print(json.dumps(record, indent=2))
