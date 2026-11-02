# CPU-free CXI bring-up from current CLIC

Starting point: `pinxuezhao/CLIC_SwissAI`, revision
`e80f60c059e1e5f272fc630eb15d60b5b09d8391`, local branch `clariden-cxi-gin`.
The upstream MIT-licensed source is staged unchanged in `CLIC_SwissAI/`.
Target: qualify its GPU-driven Cassini primitives, then expose the required
NCCL GIN semantics to our pinned DeepEP v2 EP8 implementation. This directory
does **not** yet contain an implemented GIN backend.

## Current result

The October 25 Clariden login preflight returned `DEPENDENCY_CHECK_FAILED`:
no `fi_cxi_gpu_ext.h` in our private libfabric or the checked system prefixes
(Cray 1.15.2.0, 1.22.0, 2.3.1, host, /usr, /usr/local, /opt/libfabric).
See `../../results/cxi_gin_20261025/login-preflight.json`.
This is a login-visible file audit, not a compute-node runtime capability test.
No CLIC build job was submitted with this known missing dependency. October 26
capability job 3754974 subsequently checked two compute nodes: the same KI
dependency gate failed, but a public-libcxi CUDA doorbell-mapping probe passed
on both. Subsequently, job **3755312** completed on nid006760/nid007658 in
46 seconds: all eight GPUs passed 10,000 GPU-issued NIC NOOPs, cross-node HBM
puts, 32,768 puts with GPU-polled NIC ACK counters and 128 remote HBM atomic
adds. These public-libcxi probes execute no CPU posting/progress during their
kernels. The counter test suppresses success CQ events and requires no CPU
CQ drain. Source snapshots and results are in
`../../results/deepep_direct_10_26/nop-3755312/` and the live investigation log.
This validates raw prerequisites, **not an implemented NCCL GIN/DeepEP backend**.
Ordering/source-reuse and concurrent-context tests remain separate gates.

The missing item is the **existing CLIC branch's matching KI-enabled libfabric
provider/source**, not a newer CLIC branch. Public code search found consumers
of the header, but no implementation we could retrieve. A standalone copied
header would not provide the provider operations or establish ABI compatibility.
That dependency still applies to building CLIC unchanged. The successful raw
public-SDK route means it is not an absolute blocker to a new CXI backend on
the tested nodes. No access to the
author's restricted directories has been bypassed.

## Dependency audit

```bash
python3 tools/cxi_gin/preflight.py --output /tmp/cxi-preflight.json
```

Once a matching provider is accessible, run inside the allocated compute container:

```bash
python3 tools/cxi_gin/preflight.py \
  --libfabric /accessible/ki-libfabric \
  --require-compute --require-toolchain --compile-check \
  --output /tmp/cxi-compile-preflight.json
```

The probe checks headers and a linkable library from the selected prefix and
compiles a small API-use check when requested. It never initializes a GPU or
selects a proxy fallback. Passing these checks does not establish that the
runtime provider supports KI or that communication progresses without a CPU.

## Isolated build

Deployed workspace: `/iopsstor/scratch/cscs/zyu/cxi-gin-20261025`.
After the dependency and eligible-node gate is satisfied, submit from Clariden:

```bash
export CXI_KI_PREFIX=/accessible/ki-libfabric
export CLIC_OPENMPI_PREFIX=/accessible/matching-openmpi
sbatch /iopsstor/scratch/cscs/zyu/cxi-gin-20261025/tools/build.sbatch
```

Add the CSCS-provided node constraint to sbatch if required. `build.sbatch`
uses our existing CUDA 13 container and must be adjusted if the KI provider
requires a different agreed environment. Python defaults to the container's
Python; upstream setup accepts >=3.8, but this particular build remains untested.

`build.sh` requires a new output directory, verifies the upstream revision,
archives its source, creates a private venv with the container dependencies,
builds CLIC with eight build workers, and records package versions, linked
libraries and a runtime environment script. It does not install into the shared
SGLang or DeepEP environments. Build success is distinct from runtime KI success.

## Next runtime gates

1. Use the upstream `tests/run_validation.sh correctness 2` with the generated
   runtime environment and an exclusive two-node allocation. BF16 is the current
   supported CLIC token format. Preserve independent reference checks and teardown.
2. Repeat with `CLIC_KI_CQ_DRAIN=0`, then exercise queue wraparound and repeated
   allocation/destruction. This is necessary but not sufficient CPU-free evidence.
3. Add a persistent GPU primitive stress test with no host progress calls during
   the test interval; measure CPU activity separately from posting/progress.
4. Implement the exact DeepEP hybrid GIN subset: puts, VA signal adds, indexed
   signals, flush, context ordering and backpressure. Audit reachable call sites;
   do not advertise unsupported operations.
5. Replace DeepEP's private GDAKI signal-buffer-layout assumption with supported
   signal access/wait operations, preserving bounded diagnostics. Build matching
   NCCL host/device components. Validate EP8 before tuning 4096-token/GPU cases.

Do not treat upstream `--skip-destroy`, a short two-iteration run, or successful
CPU-assisted CQ draining as a completed CPU-free milestone. Our full milestone
and acceptance plan is in `../../10_22_MoonEP.md`, section 15.

## October 26 source audit and development trees

Historical EP8 job 3725346 explicitly recorded `NCCL_GIN_TYPE=2`,
`EP_DISABLE_GIN=0`, `FI_PROVIDER=cxi`, NCCL runtime 23203 and the private OFI
plugin. This is CPU-proxy GIN. The payload can still use GPU-direct RDMA.

The original `../../DeepEP` remains clean at bd1e1669. Local commit bd1e1669
adds benchmark diagnostics on top of d4f41e4e; it is not the latest upstream
main. Current upstream checked October 26 is f6aa38fe (October 21), now v2.5:
170 changed files against our tree, ElasticBuffer replaced with EPBuffer,
DeepJIT/CUDA >=13.1/C++20 requirements, and a GDAKI-only assertion plus explicit
`reqs.ginType = NCCL_GIN_TYPE_GDAKI` in csrc/kernels/comm/context.cpp. An in-place
update would break compatibility with our current proxy configuration and
benchmark API. It is not a Slingshot support upgrade.

Two isolated Git worktrees now exist:
- `DeepEP-upstream-f6aa38f`: detached upstream reference, unbuilt, submodule
  uninitialized; inspect portable waitSignal/readSignal implementation here.
- `DeepEP-cxi-dev`: branch cxi-gin-bringup-20261026 based on the measured
  bd1e1669 tree. Contains a draft replacement of the private GDAKI signal-table
  cast with NCCL's bounded waitSignal/readSignal APIs. This is a portability
  prerequisite, not a GPU-CXI implementation or a measured performance fix.

Patch: `patches/deepep-bd1e166-portable-signal-wait.patch`. It passes diff checks
and git apply --check against the baseline. Its API signatures were checked
against the installed NCCL 2.32.3 headers. Initially it had not been compiled,
deployed or tested on GPUs; the subsequent limited validation is recorded below.
Require an isolated build, repeated EP8 barrier and
dispatch/combine correctness tests, timeout/abort checks and unprofiled baseline
comparison before use. It requires those NCCL APIs; no older-header compatibility
is claimed. Update: job 3754974 JIT-compiled the isolated patch and passed the
4096-token/GPU EP8 V4-Flash mixed-route FP8/BF16 correctness case on all eight
ranks with proxy GIN, including DONE markers. This does not establish timeout
handling, broader lifecycle coverage or direct-backend correctness. See
../../10_26_DeepEP_v2_Slingshot.md for the active investigation. Upstream SM90 and device-communicator ABI fixes should be reviewed
separately before any broader migration.

`reference/nccl-v2.32.3-1` contains verbatim upstream proxy/GDAKI device headers,
host proxy source and developer guide. Device-header SHA256s exactly match the
headers in our Clariden NCCL installation (host-library identity is a separate
check). Proxy: GPU descriptor FIFO -> CPU RMA plugin -> NIC. GDAKI: GPU DOCA
verbs operations -> supported NVIDIA NIC queues, with host resource setup.
CXI needs its own full host/device GIN backend using qualified CXI primitives
(through KI or the public libcxi route), rather than mlx5 WQEs. Environment
selection does not create that implementation.

The actual private CXI host RMA tables route into src/rdma/gin, including CPU
receive-side metadata/completion processing and a GDRCopy signal-delivery
worker. See `../ep8_profile/README.md` for corrected hooks and hypotheses.

Source URLs:
- https://github.com/deepseek-ai/DeepEP/commit/f6aa38fe06cd4a0489e7730365d4e0114970a2f3
- https://github.com/deepseek-ai/DeepEP/blob/f6aa38fe06cd4a0489e7730365d4e0114970a2f3/csrc/kernels/comm/context.cpp
- https://github.com/NVIDIA/nccl/blob/v2.32.3-1/plugins/gin/README.md
- https://github.com/NVIDIA/nccl/blob/v2.32.3-1/src/include/nccl_device/gin/proxy/gin_proxy.h
- https://github.com/NVIDIA/nccl/blob/v2.32.3-1/src/include/nccl_device/gin/gdaki/gin_gdaki.h
- https://github.com/NVIDIA/nccl/blob/v2.32.3-1/src/gin/gin_host_proxy.cc

## Local dependency checks

```bash
python -m unittest discover -s tools/cxi_gin -p 'test_*.py' -v
bash -n tools/cxi_gin/build.sh tools/cxi_gin/build.sbatch
```

The dependency tests ensure an ordinary CXI installation and a broken library
symlink cannot pass the KI file gate. They do not replace compilation or GPU tests.
