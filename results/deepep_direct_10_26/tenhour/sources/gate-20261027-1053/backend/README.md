# Experimental direct CXI GIN for pinned DeepEP v2

This is a private development backend for Clariden GH200/Cassini nodes. It is
not an upstream-supported NCCL plugin or a generally qualified transport.
The authoritative qualification log is
[`10_26_DeepEP_v2_Slingshot.md`](../../../10_26_DeepEP_v2_Slingshot.md).

## Components

| Component | Responsibility |
|---|---|
| `host/cxi_resources.cc` | Slurm service/VNI, libcxi resources, CUDA memory registration, GPU queue/doorbell mappings, explicit teardown |
| `host/cxi_bootstrap.cc` | Setup-only TCP metadata exchange over the allocated nodes |
| `host/gin_plugin.cc` | NCCL GIN v14 host callbacks; GPU descriptors; no progress callback |
| `device/cxi_primitives.cuh` | GPU command posting, doorbells, completion-counter polling and remote atomics |
| `device/gin_cxi.cuh` | Public NCCL GIN operations implemented using CXI primitives |
| `../nccl-cxi-dev` | Matching NCCL host/device integration, based on `12df1a11afad322be5a204a2db890161cbf8131d` |
| `../DeepEP-cxi-dev` | DeepEP `bd1e1669` with the backend-independent barrier and runtime-library guard patches |
| `sglang/deepep_v2_cxi.py` | Unqualified opt-in SGLang normal-mode adapter using `ElasticBuffer` |

Private backend **type 6** identifies this implementation. Type 3 remains
NCCL's GDAKI backend. Stock NCCL does not understand this private type: the
matching host library and installed device headers are both required.

## Runtime requirements

- An actual Slurm allocation supplies `SLINGSHOT_DEVICES`, `SLINGSHOT_SVC_IDS`
  and `SLINGSHOT_VNIS`. Never borrow another job's service identifiers.
- Use the existing container EDF and installed host libcxi/device interface.
  The tested nodes permit GPU mapping of the application's allocated command
  queues and doorbells. Raw probes must be repeated on a materially different
  driver/NIC configuration; GH200 alone is not sufficient evidence.
- Load exactly one NCCL runtime. The test scripts use an isolated Python
  `nvidia/nccl/lib` overlay because PyTorch explicitly preloads that package's
  library; `LD_PRELOAD` alone did not prevent a duplicate NCCL runtime.
- For a clean-prefix rerun, set both `CXI_NCCL_PREFIX` (installed headers/lib)
  and `CXI_NCCL_SOURCE` (matching reconstructed source/internal plugin headers).
  Set `CXI_DEEPEP_SOURCE` to the intended private DeepEP deployment. The tests'
  `common.py` is bundled; later snapshots need no helper from an older run.
- Keep `EP_SUPPRESS_NCCL_CHECK=0`. Select `NCCL_GIN_TYPE=6`, the absolute private
  plugin path, `NCCL_GIN_NCONNECTIONS=1`, and initially `NCCL_ALGO=Ring`.
- CPU setup, allocation, bootstrap, kernel launch, and host synchronization are
  allowed. GPU kernels post and complete payload transfers without per-transfer
  CPU progress. A null progress callback does not establish model correctness.
- NCCL VMM allocations reject the legacy pointer-level `SYNC_MEMOPS` setter on
  the tested driver. The guarded fallback verifies RDMA capability and enables
  the equivalent synchronous-operation contract at CUDA context scope, retaining
  existing flags. This setup policy must be recorded in performance comparisons.

## Test sequence

Use immutable source snapshots and the bounded `tools/lease_driver.py` request
interface. `tools/direct_node.sh` selects a test through `CXI_TEST_KIND`:

| Kind | Purpose |
|---|---|
| `smoke` | Public put/value/signal/counter/flush, optional reset, self-signal and delayed-peer tests |
| `producer` | Same-warp and multi-CTA producers sharing one context |
| `bad_offset` | Expected terminal bounds failure; requires exact diagnostic 11, not merely a failed process |
| `bounds` | Five bounds/peer rejection cases using isolated guard state, without posting invalid NIC commands |
| `ep` | Independent-reference DeepEP dispatch/combine; optional matched proxy control |
| `sglang` | Actual SGLang dispatcher; optional real scatter/gather or real expert kernels with an analytic reference |

The controller executes requests serially and reserves cleanup time. A
controller-refused request is not an executed test. Likewise, an allocation's
COMPLETED state does not mean that every individual step passed.
The controller reads the current Slurm end time because the exported
`SLURM_JOB_END_TIME` can retain the backfill minimum after a longer limit is
granted. A failed query falls back to that export; an unknown deadline admits
no test. It never extends the scheduler allocation itself.

`CXI_TRANSPORT=proxy` is available only for the standalone `ep` comparison;
it selects the existing OFI/CXI GIN type 2 with the same NCCL build and DeepEP
source. The standalone output records the selected type, token count, routing,
SM/QP settings, correctness, per-rank samples, source hashes and loaded paths.
Fresh dispatch is primary; cached dispatch is a separate diagnostic.
Set `CXI_EP_DEBUG=0` for timing runs: the pinned DeepEP C++ dispatch otherwise
prints on every call. Correctness runs retain the debug output by default.

`CXI_SGLANG_GEMM=1` additionally exercises the actual SGLang DeepGEMM expert
runner with diagonal BF16/FP8 weights, SwiGLU, real scatter/gather, and a
numerical reference. Its FFN width is reduced to 128 while the communication
hidden width/expert count stay unchanged. This is a prepared integration smoke,
not full model execution or representative expert-compute timing. See the log
for actual runtime qualification; merely enabling this option is not a pass.

## Current limitations

See the dated log for what has actually run. Compilation does not imply a pass.
The initial GPU implementation deliberately waits for queue consumption and
uses conservative completion ordering; it has not been optimized for line rate.
GET/Engram is unsupported and traps explicitly. General mixed-memory transfers,
arbitrary topology, automatic backend selection, full serving lifecycle, SGLang
LL/AUTO/overlap/EPLB recording, and transparent fault recovery are not qualified.

Positive tests must explicitly destroy resources. If CUDA is poisoned or NIC
teardown fails, the experimental plugin terminates the isolated process with
exit 86 instead of freeing memory that may still be live. The launcher's peer
termination and a fresh process group are required. This is a documented fatal
error policy, not a successful teardown or recoverable network failover.

No NIC firmware, driver, privileged service configuration, or shared serving
installation is modified by these scripts. Preserve failed attempts and their
source snapshots when preparing any eventual upstream review.
