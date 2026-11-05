#!/usr/bin/env python3
"""Apples-to-apples EP8 comparison: DeepEP v2 over the direct-CXI GIN (release candidate, lean-b + kernel
knobs) against UCCL-EP's native CPU proxy over libfabric/CXI (swiss-ai/uccl@54ef064, the Swiss AI
reference build of 2026-10-28), in ONE allocation, with the SAME benchmark (backend/tests/ep_benchmark.py),
the SAME inputs (routing, seeds, dtypes, token counts) and the SAME metric (full-call CUDA events per
rank, headline = median of the per-iteration rank maximum; wall time per iteration of the slowest rank).

Snapshot changes against the parent (source-1103-ep8skew-v3; transport code untouched):
- backend/tests/ep_benchmark.py, UCCL path only: one persistent UCCL buffer per process (upstream's
  benchmark lifetime; the October per-case destroy faulted in UcclProxy's scratch ownership), separate
  dispatch and combine configs (upstream tunes them separately), buffer sizes as upstream's
  compute_buffer_sizes, provenance from UCCL_WORK/source-manifest.json, os._exit after DONE.
- runner/node.sh: CXI_TEST_KIND=uccl hands the gate to runner/uccl_node.sh (new), which sources the UCCL
  runtime, unsets the NCCL GIN selection, points at the reference build and runs the benchmark.
- runner/validate_gate.py: qualification kind uccl_ep (same matrix/DONE/correctness checks as ep, backend uccl).

usage: package_ucclcmp_1105.py results/deepep_pipeline_20261101/source-1105-ucclcmp-v1 [--parent source-1103-ep8skew-v3]
"""
import argparse, copy, hashlib, json, shutil, sys
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'pipeline_v1')); sys.path.insert(0, str(HERE))
from package import replace  # noqa: E402
ROOT = HERE.parents[3]; NEW = ROOT / 'results/deepep_pipeline_20261101'
REMOTE = '/iopsstor/scratch/cscs/zyu/deepep-pipeline-20261030'
UCCL_BUILD = '/iopsstor/scratch/cscs/zyu/uccl-ep8-live-20261028/builds/apertus-54ef064-v1'
UCCL_RUNTIME = '/iopsstor/scratch/cscs/zyu/uccl-ep-20261023/tools/runtime.sh'
UCCL_COMMIT = '54ef06429dde1c2debd3dbfb565530020650f7fd'
UCCL_SO_SHA = 'dcce642bedc055ab8cf5a9a4297eb297f236e23b12980f19f33aeaeb857d874c'
# upstream tuning (job 3783795, bench/test_internode.py): 24 SMs; FP8 dispatch best at NVL chunk 28-44 / RDMA 32
# (V4 Flash), 16-32 / 32 (Qwen3), 4-8 / 32 (MiniMax); combine best at NVL chunk 3-7 / RDMA 32. One setting for
# all geometries here, within the flat part of each sweep; capture.py of 2026-10-29 ran 24/32/32 successfully.
UCCL_SMS, UCCL_DISPATCH, UCCL_COMBINE = 24, (32, 32), (4, 32)
ap = argparse.ArgumentParser(); ap.add_argument('out', type=Path); ap.add_argument('--parent', default='source-1103-ep8skew-v3')
a = ap.parse_args(); out = a.out.resolve(); assert not out.exists(), out
parent = NEW / a.parent
shutil.copytree(parent, out, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))

# ---- ep_benchmark.py: UCCL path -------------------------------------------------------------------------
f = out / 'backend/tests/ep_benchmark.py'
replace(f, """import diagnostic_watch
""", """import diagnostic_watch

# UCCL: one buffer per process, as in upstream's benchmark. Destroying and recreating the buffer per case
# faulted the next case in October (UcclProxy and the DLPack deleter both freed the scratch allocation).
_UCCL_BUFFERS = {}
""")
replace(f, """        if args.backend=='uccl':
            from uccl import ep
            from buffer import Buffer
            Buffer.set_num_sms(args.sms)
            self.config=ep.Config(args.sms,args.nvl_chunk,512,args.rdma_chunk,512)
            align=lambda x: ((int(x*1.2)+127)//128)*128
            nv=align(self.config.get_nvl_buffer_size_hint(h*2,dist.get_world_size()))
            rd=align(self.config.get_rdma_buffer_size_hint(h*2,dist.get_world_size())) if dist.get_world_size()>4 else 0
            self.buf=Buffer(dist.group.WORLD,nv,rd,explicitly_destroy=True)
            if rd: assert self.buf.scratch.is_cuda
            self.sms=args.sms; self.qps=None
""", """        if args.backend=='uccl':
            from uccl import ep
            from buffer import Buffer
            Buffer.set_num_sms(args.sms)
            # Buffer sizes exactly as upstream bench/test_internode.py compute_buffer_sizes (hint config 8/512/16/512,
            # margin 1.2, 128-byte alignment); dispatch and combine get their own chunk configs as upstream tunes them.
            hint=ep.Config(args.sms,8,512,16,512)
            align=lambda x: ((int(x*1.2)+127)//128)*128
            nv=align(hint.get_nvl_buffer_size_hint(h*2,dist.get_world_size()))
            rd=align(hint.get_rdma_buffer_size_hint(h*2,dist.get_world_size())) if dist.get_world_size()>4 else 0
            self.config=ep.Config(args.sms,args.nvl_chunk,512,args.rdma_chunk,512)
            self.combine_config=ep.Config(args.sms,args.combine_nvl_chunk,512,args.combine_rdma_chunk,512)
            key=(nv,rd)
            if key not in _UCCL_BUFFERS:
                assert not _UCCL_BUFFERS, ('one UCCL buffer geometry per process', key, list(_UCCL_BUFFERS))
                _UCCL_BUFFERS[key]=Buffer(dist.group.WORLD,nv,rd,explicitly_destroy=True)
            self.buf=_UCCL_BUFFERS[key]
            if rd: assert self.buf.scratch.is_cuda
            self.sms=args.sms; self.qps=None; self.buffer_bytes=dict(nvl=nv,rdma=rd)
""")
replace(f, """        if self.args.backend=='uccl':
            return self.buf.combine(y,handle,topk_weights=w,config=self.config,async_finish=False)
""", """        if self.args.backend=='uccl':
            return self.buf.combine(y,handle,topk_weights=w,config=self.combine_config,async_finish=False)
""")
replace(f, """        requested_sms=args.sms,nvl_chunk=args.nvl_chunk,rdma_chunk=args.rdma_chunk,
""", """        requested_sms=args.sms,nvl_chunk=args.nvl_chunk,rdma_chunk=args.rdma_chunk,
        combine_nvl_chunk=args.combine_nvl_chunk,combine_rdma_chunk=args.combine_rdma_chunk,
""")
replace(f, """    b=Backend(args,n,h,e,k); case.update(actual_sms=b.sms,qps=b.qps)
""", """    b=Backend(args,n,h,e,k); case.update(actual_sms=b.sms,qps=b.qps,**(dict(uccl_buffer_bytes=b.buffer_bytes) if args.backend=='uccl' else {}))
""")
replace(f, """    diagnostic_watch.mark('buffer_destroy_enter')
    b.buf.destroy()
    diagnostic_watch.mark('buffer_destroy_return')
""", """    diagnostic_watch.mark('buffer_destroy_enter')
    if args.backend!='uccl': b.buf.destroy()   # the UCCL buffer lives until the process exits (see _UCCL_BUFFERS)
    diagnostic_watch.mark('buffer_destroy_return')
""")
replace(f, """        **source_metadata(source,os.environ.get('DEEPEP_WORK','')+'/source-manifest.json','DeepEP'),
""", """        **(source_metadata(source,os.environ['UCCL_WORK']+'/source-manifest.json','UCCL') if args.backend=='uccl' else
           source_metadata(source,os.environ.get('DEEPEP_WORK','')+'/source-manifest.json','DeepEP')),
""")
replace(f, """    if rank==0:
        from summarize import summarize
        summarize(out)
    dist.destroy_process_group()
""", """    if rank==0:
        from summarize import summarize
        summarize(out)
    if args.backend=='uccl':
        # Upstream's own benchmark never tears the UCCL buffer down either: results are written and
        # synchronised, then the process exits without destroying the proxy or the process group.
        dist.barrier(); torch.cuda.synchronize(); os._exit(0)
    dist.destroy_process_group()
""")
replace(f, """    p.add_argument('--rdma-chunk',type=int,default=16)
""", """    p.add_argument('--rdma-chunk',type=int,default=16)
    p.add_argument('--combine-nvl-chunk',type=int,default=None,help='UCCL combine config (default: the dispatch chunks)')
    p.add_argument('--combine-rdma-chunk',type=int,default=None)
""")
replace(f, """    with torch.inference_mode(): main(p.parse_args())
""", """    _a=p.parse_args()
    if _a.combine_nvl_chunk is None: _a.combine_nvl_chunk=_a.nvl_chunk
    if _a.combine_rdma_chunk is None: _a.combine_rdma_chunk=_a.rdma_chunk
    with torch.inference_mode(): main(_a)
""")

# ---- runner/node.sh: hand UCCL gates to uccl_node.sh ------------------------------------------------------
replace(out / 'runner/node.sh', """: "${CAMPAIGN:?}" "${SNAPSHOT:?}" "${OUT:?}" "${CXI_VARIANT:?}"
""", """if [ "${CXI_TEST_KIND:-smoke}" = uccl ]; then
  # UCCL-EP CPU-proxy comparison gate: no NCCL GIN runtime, no DeepEP build; see runner/uccl_node.sh.
  exec bash "${SNAPSHOT:?}/runner/uccl_node.sh"
fi
: "${CAMPAIGN:?}" "${SNAPSHOT:?}" "${OUT:?}" "${CXI_VARIANT:?}"
""")
(out / 'runner/uccl_node.sh').write_text(f'''#!/usr/bin/env bash
# UCCL-EP (native CPU proxy over libfabric/CXI) side of the EP8 comparison. Same benchmark, inputs and
# metric as the direct-GIN gates (backend/tests/ep_benchmark.py); the transport is the Swiss AI reference
# build {UCCL_COMMIT[:7]} of 2026-10-28 (job 3783795), untouched.
set -euo pipefail
ulimit -c 0
: "${{SNAPSHOT:?}}" "${{OUT:?}}" "${{MASTER_ADDR:?}}" "${{MASTER_PORT:?}}"
source {UCCL_RUNTIME}
unset NCCL_GIN_TYPE NCCL_GIN_PLUGIN EP_NCCL_ROOT_DIR LD_PRELOAD EP_JIT_NVCC_COMPILER
build={UCCL_BUILD}
base="$OUT/uccl/node$SLURM_PROCID"; work="$OUT/uccl/work"
mkdir -p "$base" "$work"
printf 'UCCL gate: inventory\\n' > "$OUT/node$SLURM_PROCID.STAGE" 2>/dev/null || true
{{
  date -u +%FT%TZ; hostname; uname -r
  nvidia-smi --query-gpu=name,uuid,driver_version,pci.bus_id --format=csv
  sha256sum "$build/python/uccl/"ep*.so /host_usr/lib64/libcxi.so "$DEPS/lf-install/lib/libfabric.so"* 2>/dev/null || true
  python -c 'import torch,sys;print("torch",torch.__version__,"python",sys.version)'
}} > "$base/node-inventory.txt" 2>&1
# Provenance for the benchmark's source_metadata: the extracted reference tree plus its pinned commit.
if [ "$SLURM_PROCID" = 0 ]; then
  ln -sfn "$build/source" "$work/source"
  printf '%s\\n' '{{"sources": {{"UCCL": {{"sha": "{UCCL_COMMIT}", "repository": "https://github.com/swiss-ai/uccl", "build": "{UCCL_BUILD}", "extension_sha256": "{UCCL_SO_SHA}"}}}}}}' > "$work/source-manifest.json"
fi
for i in $(seq 1 60); do [ -f "$work/source-manifest.json" ] && [ -e "$work/source" ] && break; sleep 1; done
grep -q "{UCCL_SO_SHA}" "$base/node-inventory.txt" || {{ printf 'UCCL extension hash differs from the qualified reference build\\n' >&2; exit 2; }}
export UCCL_WORK="$work"
export PYTHONPATH="$SNAPSHOT/backend/tests:$build/python:$build/source/ep/bench"
export UCCL_EP_TRANSPORT=cxi
export EP_JIT_CACHE_DIR="$base/jit"; mkdir -p "$EP_JIT_CACHE_DIR"
read -r -a models <<< "${{CXI_EP_MODELS:-v4flash}}"
read -r -a tokens <<< "${{CXI_EP_TOKENS:-4096}}"
read -r -a dtypes <<< "${{CXI_EP_DTYPES:-fp8}}"
read -r -a routing <<< "${{CXI_EP_ROUTING:-mixed}}"
read -r -a seeds <<< "${{CXI_EP_SEEDS:-1}}"
export MASTER_PORT=$((MASTER_PORT+2))
printf 'UCCL gate: benchmark\\n' > "$OUT/node$SLURM_PROCID.STAGE" 2>/dev/null || true
if timeout --signal=TERM --kill-after=10s "${{CXI_TEST_TIMEOUT:-300}}s" python -m torch.distributed.run \\
  --nnodes=2 --nproc_per_node=4 --node_rank="$SLURM_PROCID" \\
  --master_addr="$MASTER_ADDR" --master_port="$MASTER_PORT" "$SNAPSHOT/backend/tests/ep_benchmark.py" \\
  --backend uccl --output "$OUT/uccl/ep" \\
  --models "${{models[@]}}" --tokens "${{tokens[@]}}" --dtypes "${{dtypes[@]}}" --routing "${{routing[@]}}" --seeds "${{seeds[@]}}" \\
  --warmup "${{CXI_EP_WARMUP:-20}}" --iters "${{CXI_EP_ITERS:-100}}" --nic-iters "${{CXI_EP_NIC_ITERS:-0}}" --profile-steps 0 \\
  --sms {UCCL_SMS} --nvl-chunk {UCCL_DISPATCH[0]} --rdma-chunk {UCCL_DISPATCH[1]} \\
  --combine-nvl-chunk {UCCL_COMBINE[0]} --combine-rdma-chunk {UCCL_COMBINE[1]} \\
  > "$base/benchmark.log" 2>&1; then rc=0; else rc=$?; fi
[ "$rc" = 0 ] || exit "$rc"
date -u +%FT%TZ > "$base/PASS"
''')

# ---- runner/validate_gate.py: qualification kind uccl_ep --------------------------------------------------
replace(out / 'runner/validate_gate.py', """    if mode == 'sglang':
        require(transport in ('direct', 'proxy'), 'unqualified SGLang transport')
""", """    if mode == 'uccl_ep':
        # UCCL-EP CPU-proxy comparison gate: the ep checks that do not concern our transport or JIT knobs.
        ep = Path(destination) / 'uccl' / 'ep'
        validation = json.loads((ep / 'validation.json').read_text())
        require(validation['status'] == 'PASS' and validation['ep'] == 8, 'EP summary failed')
        require(not list(ep.glob('failures-rank*.jsonl')), 'EP failure records exist')
        models = env.get('CXI_EP_MODELS', 'v4flash').split()
        tokens = [int(v) for v in env.get('CXI_EP_TOKENS', '4096').split()]
        dtypes = env.get('CXI_EP_DTYPES', 'fp8').split()
        routing = env.get('CXI_EP_ROUTING', 'mixed').split()
        seeds = [int(v) for v in env.get('CXI_EP_SEEDS', '1').split()]
        expected = {(m, n, d, r, s) for m in models for n in tokens for d in dtypes for r in routing for s in seeds}
        for rank in range(8):
            require((ep / ('DONE-rank%d' % rank)).is_file(), 'EP rank not done')
            rows = json_lines(ep / ('correctness-rank%d.jsonl' % rank))
            keys = {(r['model'], r['tokens_per_gpu'], r['dispatch_dtype'], r['routing'], r['seed']) for r in rows}
            require(len(rows) == len(expected) and keys == expected, 'EP matrix incomplete')
            require(all(r['rank'] == rank and r['ep'] == 8 and r['status'] == 'PASS' and r['backend'] == 'uccl'
                        and r.get('gin_type') is None for r in rows), 'EP wrong rank/backend or failed correctness')
        for node in range(2):
            require((Path(destination) / 'uccl' / ('node%d' % node) / 'PASS').is_file(), 'UCCL node script did not pass')
        return {'status': 'PASS', 'kind': 'uccl_ep', 'ranks': 8, 'cases_per_rank': len(expected), 'backend': 'uccl',
                'transport': 'uccl_native_cpu_proxy_cxi'}
    if mode == 'sglang':
        require(transport in ('direct', 'proxy'), 'unqualified SGLang transport')
""")

changed = sorted(str(p.relative_to(out)) for p in out.rglob('*') if p.is_file() and p.name not in ('sequence.json', 'manifest.json')
                 and '__pycache__' not in p.parts and (not (parent / p.relative_to(out)).exists() or p.read_bytes() != (parent / p.relative_to(out)).read_bytes()))
assert changed == ['backend/tests/ep_benchmark.py', 'runner/node.sh', 'runner/uccl_node.sh', 'runner/validate_gate.py'], changed

# ---- gates --------------------------------------------------------------------------------------------------
X = {g['name']: g for g in json.loads((NEW / 'source-1103-ep8bank-v1/sequence.json').read_text())}
snapshot = REMOTE + '/sources/' + out.name
SETUP, ALLOC = 10, 40 * 60
seq = []; budget = []
def deepep(name, models, seeds, timeout, expected):
    g = copy.deepcopy(X['X100-leanb-bank-fp8']); g['name'] = name; g['snapshot'] = snapshot; g['requires'] = []
    e = g['environment']; e.update(CXI_EP_MODELS=models, CXI_EP_TOKENS='4096', CXI_EP_DTYPES='fp8', CXI_EP_ROUTING='uniform mixed',
                                   CXI_EP_SEEDS=seeds, CXI_EP_WARMUP='20', CXI_EP_ITERS='100', CXI_EP_NIC_ITERS='600')
    assert e['CXI_VARIANT'] == 'lean-b' and e['CXI_EP_SKIP_COMBINE_FLUSH'] == '1' and e['CXI_EP_LOCAL_SELF_SIGNAL'] == '1'
    g['timeout_seconds'] = timeout; e['CXI_TEST_TIMEOUT'] = str(timeout - 60)
    seq.append(g); budget.append(expected)
def uccl(name, models, seeds, timeout, expected):
    env = dict(CXI_TEST_KIND='uccl', CXI_TRANSPORT='uccl', CXI_EP_MODELS=models, CXI_EP_TOKENS='4096', CXI_EP_DTYPES='fp8',
               CXI_EP_ROUTING='uniform mixed', CXI_EP_SEEDS=seeds, CXI_EP_WARMUP='20', CXI_EP_ITERS='100', CXI_EP_NIC_ITERS='600',
               CXI_TEST_TIMEOUT=str(timeout - 60), CXI_DEVICE_TRACE='0')
    seq.append(dict(name=name, snapshot=snapshot, node_script='runner/node.sh', qualification='uccl_ep',
                    timeout_seconds=timeout, environment=env, requires=[])); budget.append(expected)
deepep('C100-deepep-v4flash', 'v4flash', '1 2 3', 540, 300)
uccl('C101-uccl-v4flash', 'v4flash', '1 2 3', 480, 180)
deepep('C102-deepep-qwen3-minimax', 'qwen3 minimax', '1 2 3', 720, 480)
uccl('C103-uccl-qwen3', 'qwen3', '1 2 3', 360, 120)
uccl('C104-uccl-minimax', 'minimax', '1 2 3', 360, 120)
deepep('C105-deepep-v4flash-repeat', 'v4flash', '1 2 3', 540, 300)
uccl('C106-uccl-v4flash-repeat', 'v4flash', '1 2 3', 420, 150)
t = SETUP
for g, expected in zip(seq, budget):
    remaining = ALLOC - t; fits = g['timeout_seconds'] + 180 < remaining
    print('%-30s start %5.1f min  remaining %4d s  timeout %3d  %s' % (g['name'], t / 60, remaining, g['timeout_seconds'], 'ok' if fits else 'DOES NOT FIT'))
    assert fits, g['name']; t += expected
print('expected end of the last gate: %.1f min of %d' % (t / 60, ALLOC // 60))
(out / 'sequence.json').write_text(json.dumps(seq, indent=2) + '\n')
m = json.loads((parent / 'manifest.json').read_text())
m.update(source_parent=str(parent), scope='2026-11-05 apples-to-apples EP8: DeepEP v2 direct-CXI GIN (lean-b release candidate) vs UCCL-EP native CPU proxy '
         f'(swiss-ai/uccl@{UCCL_COMMIT[:7]}, {UCCL_SMS} SMs, dispatch NVL/RDMA chunks {UCCL_DISPATCH}, combine {UCCL_COMBINE}) with the same benchmark, inputs and metric; '
         f'4096 tokens/rank, FP8 dispatch/BF16 combine, uniform and mixed routing, three seeds, three geometries; transport code identical to {a.parent}',
         uccl=dict(commit=UCCL_COMMIT, build=UCCL_BUILD, extension_sha256=UCCL_SO_SHA, sms=UCCL_SMS, dispatch_chunks=UCCL_DISPATCH, combine_chunks=UCCL_COMBINE))
m['files'] = {str(p.relative_to(out)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(out.rglob('*')) if p.is_file() and p.name != 'manifest.json'}
(out / 'manifest.json').write_text(json.dumps(m, indent=2) + '\n')
print(len(seq), 'gates'); print([g['name'] for g in seq]); print(out)
