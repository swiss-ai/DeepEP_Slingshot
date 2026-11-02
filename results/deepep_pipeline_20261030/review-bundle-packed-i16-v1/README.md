# Tested-snapshot source review bundle

`DeepEP.patch` applies to pinned DeepEP bd1e1669. The exporter applied it to
a clean checkout and verified every ordinary source file against the immutable
experiment archive, including the separately pinned fmt submodule. The complete
host plugin, device transport, benchmark and runner are under `snapshot/`.

This is not a standalone installer or a clean GPU rebuild result. The runner
requires the matching private NCCL type-6 host library/device headers, CSCS
container, libcxi interface and job-specific Slingshot service allocation.
`review-manifest.json` records the required library hash. Existing snapshot
documentation contains historical development paths; the current deployment
procedure is `snapshot/runner/install.py` followed by `snapshot/runner/node.sh`
under the bounded retained-allocation executor. Do not invoke it on a login node.

The selected ordinary EP configuration is 64 SMs, 129 contexts,
CXI_EP_UPDATE_INTERVAL=16, CXI_EP_FORWARD_CHUNK=3 and CXI_EP_PACK_ROWS=1.
The marker-zero transport definitions are in snapshot/variants.json. Tracing is
disabled; the private tracing snapshot is separate. GPU submission/completion
uses CXI, not the mlx5/GDAKI implementation, and CPU resource setup/teardown
remains necessary. Combine batching has not been added.

Consult 10_30_DeepEP_v2_Slingshot.md and the immutable gate results for actual
correctness, timing and SGLang qualification. The source bundle does not upgrade
pending checks to passes. No upstream PR or shared installation was changed.
