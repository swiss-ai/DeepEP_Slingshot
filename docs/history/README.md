# Engineering logs

Dated logs written during development, oldest first. They are the primary record; the summaries in
[../design.md](../design.md), [../results.md](../results.md) and [../limitations.md](../limitations.md)
are derived from them.

| Log | Covers |
|---|---|
| [10_26_DeepEP_v2_Slingshot.md](10_26_DeepEP_v2_Slingshot.md) | Bring-up: raw libcxi probes on Clariden, first GPU-issued NIC commands, the decision to build on libcxi rather than the kernel-initiated libfabric extension. |
| [10_29_DeepEP_v2_Slingshot.md](10_29_DeepEP_v2_Slingshot.md) | First GIN backend following the GDAKI model; comparison of the required GIN operations against IB/RoCE and CXI. |
| [10_30_DeepEP_v2_Slingshot.md](10_30_DeepEP_v2_Slingshot.md) | Transport qualification ladder: batched publication, batched delivery, native CQ fence, credit cache (quarantined), packed dispatch rows, trace attribution. |
| [11_01_DeepEP_v2_Slingshot.md](11_01_DeepEP_v2_Slingshot.md) | Final campaign: packed combine, first interval, release matrix on three models, SGLang gates, the 128-byte alignment probe, closing summary. |
| [11_02_DeepEP_v2_Slingshot.md](11_02_DeepEP_v2_Slingshot.md) | Trace-based decomposition of the remaining overhead, prioritized improvement plan for dispatch and combine, the `cxi_write_bw` link-rate measurement (NIC ceiling 24.2 / 22.5 GB/s; alignment cliff not a NIC property), and the signal-path implementation round (§4: lean transport, no combine flush, no self-signal, double-buffered staging; wall-time gains and the end-skew metric caveat). |

Paths cited inside the logs (`tools/cxi_gin/...`, `results/...`) refer to the original working-tree
layout, which is preserved on the `debug` branch of this repository.
