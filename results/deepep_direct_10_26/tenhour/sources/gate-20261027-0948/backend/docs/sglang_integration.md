# SGLang integration gate: actual container source

Inspected source: `lmsysorg/sglang:v0.5.13-cu130` image already used on
Clariden. Read directly from its squashfs, without changing the image.
Reference copies and SHA256 hashes: `tools/cxi_gin/sglang-reference/`.
The running-job inventory must still confirm its actual import path.

The image's dispatcher is
`sglang/srt/layers/moe/token_dispatcher/deepep.py`. It imports
`deep_ep.Buffer`, and its normal path calls the v1-style
`get_dispatch_layout`, `dispatch(... config=...)`, and `combine` methods.
Merely replacing the Python package with DeepEP 2.0 does not select v2:
the pinned DeepEP package still exports the legacy Buffer, which initializes
NVSHMEM/IBGDA for internode communication. The target requires ElasticBuffer.

## Isolated adapter scope

Keep the normal SGLang dispatcher, stage tracking, hooks, FP8 quantization,
output types, and expert-runner interface. Add an explicit opt-in ElasticBuffer
normal-mode implementation in an isolated SGLang copy. Do not mutate the
shared serving installation or claim low-latency/decode support.

- `_get_buffer`: create/cache ElasticBuffer for the actual process group,
  hidden width, and >=4096 token capacity. Preserve hybrid NVLink/CXI mode;
  validate one eight-rank group and four-GPU local domain. Select the tested
  communication SM/QP configuration explicitly and record it.
- `_dispatch_core`: fresh v2 dispatch with top-k IDs/weights and expert
  alignment; map the returned EPHandle and received expert counts into
  `DeepEPNormalDispatchOutput`. Do not reuse a routing handle across fresh
  serving layers. Preserve recorder hooks with correctly computed metadata
  if enabled, or reject unsupported recorder modes explicitly.
- `_combine_core`: call v2 combine with the same EPHandle. SGLang's expert
  runner already incorporates routing weights in its output; do not multiply
  them a second time. Validate this against a reference expert transform.
- Event semantics: v1 EventOverlap and v2 EventHandle differ. Initially require
  synchronous current-stream dispatch/combine, then separately qualify async
  event dependencies before enabling overlap.
- FP8: verify scale representation/strides and received top-k index semantics
  against the actual GH200 DeepGEMM runner. Communication-only success does not
  qualify a different expert-kernel layout automatically.
- The v1 implementation's <=1024 assertion concerns the LL capacity setting.
  Use an explicit v2 capacity and reject LL/AUTO in the first adapter; do not
  bypass a genuine low-latency bound globally.

## Evidence required

1. Actual SGLang `DeepEPDispatcher.dispatch/combine` invocation, import paths,
   image/source hashes, exact ElasticBuffer class and type-6 backend selection.
2. Eight ranks, fresh 4096 tokens/rank, changing routes; payload/scale/routing
   validation and a deterministic expert-transform/combine reference.
3. Separate quantization/layout/dispatch/expert/combine timings. Report both
   communication-only and wrapper costs; compare the same sources/options
   under proxy and direct GIN where both run.
4. A bounded real model/layer or serving smoke if memory/allocation permits.
   Dispatcher tests alone are not model TTFT or general serving qualification.
