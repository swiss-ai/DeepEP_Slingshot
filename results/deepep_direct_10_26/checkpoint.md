## Latest collected checkpoint

Updated UTC: 2026-10-26T17:22:47.590585+00:00

Allocation: **3754974 / COMPLETED**.

**CPU-free DeepEP EP8 has not been demonstrated. Raw GPU/CXI prerequisite tests are reported separately below.**

Job artifacts: `results/deepep_direct_10_26/job-3754974`

| Probe | Collected evidence |
|---|---|
| proxy | 8/8 readable property records; 8/8 create+destroy success; selected types `[2]`; supported `[2]` |
| auto | 8/8 readable property records; 8/8 create+destroy success; selected types `[2]`; supported `[2]` |
| direct | 8/8 readable property records; 0/8 create+destroy success; selected types `[]`; supported `[]` |
| KI provider | DEPENDENCY_CHECK_FAILED; DEPENDENCY_CHECK_FAILED |
| Doorbell mapping | 2/2 nodes report a mapped device pointer; no NIC command was issued |
| Portable barrier patch | 8 passing correctness records; 8/8 DONE markers; proxy transport |

Per-node exit codes:

- `step-status-node1.tsv`: inventory=2, compile=0, map=0, proxy=0, auto=0, direct=1, portable=0
- `step-status-node0.tsv`: inventory=2, compile=0, map=0, proxy=0, auto=0, direct=1, portable=0

GPU NIC-NOOP follow-up: **3755312 / COMPLETED**.

`nop-3755312`: **8/8 GPUs** completed 10,000 NIC queue NOOPs. No network payload was transferred; this is not a GIN/EP8 correctness result.

Bounded GPU-issued cross-node mapped-memory put probe: **8/8 GPUs** passed. Completion events are drained after the GPU kernel. This is not a sustained-completion or NCCL GIN/DeepEP test.

Bounded GPU-issued cross-node HBM put probe: **8/8 GPUs** passed. This bounded variant drains events after the kernel; the separate counter test below checks GPU-only completion. NCCL GIN and DeepEP EP8 remain unverified.

Counter prerequisite probe: **8/8 GPUs** passed. 32768 HBM puts with GPU-polled NIC completion counters; constant payload, no signal-ordering/source-reuse or NCCL GIN proof.

Atomic prerequisite probe: **8/8 GPUs** passed. 128 GPU-issued remote HBM atomic adds per peer pair; single remote writer, no NCCL GIN ordering proof.

Ordering/source-reuse follow-up: **3756020 / COMPLETED**.

`order-3756020`: **8/8 GPUs** passed 128 changing-payload, source-poison, READY/ACK rounds using conservative delivery-complete writes. This remains a single-producer raw-CXI test, not an implemented NCCL GIN backend.

