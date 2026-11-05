# pipeline_1105: UCCL-EP CPU proxy vs direct GIN, same benchmark (job 3865330, 2026-11-05)

- `package_ucclcmp_1105.py`: builds snapshot `source-1105-ucclcmp-v1` from `source-1103-ep8skew-v3` (transport code
  unchanged): adds a `CXI_TEST_KIND=uccl` gate kind that runs `backend/tests/ep_benchmark.py --backend uccl` against
  the Swiss AI UCCL reference build (`swiss-ai/uccl@54ef064`, native CPU proxy over libfabric/CXI, 24 SMs, dispatch
  chunks 32/32, combine 4/32, one buffer per process), the validator kind `uccl_ep`, and the seven-gate sequence
  (direct and UCCL alternating, V4 Flash / Qwen3 / MiniMax, 4096 tokens, FP8/BF16, uniform and mixed, three seeds).
- `launch_ucclcmp_1105.py`: install and submit to the debug partition (40 min), asserting that only the four
  non-compiled files differ from the parent.
- `compare_ucclcmp_1105.py RESULTS_DIR --md`: the comparison table (wall time per iteration and headline per backend,
  UCCL/direct ratio, effective rate against the 22.5 GB/s bound, NIC octet rates).
- `snapshot-files/`: the four files the packager changes or adds, as they ran (`runner/uccl_node.sh`,
  `runner/node.sh`, `runner/validate_gate.py`, `backend/tests/ep_benchmark.py`), for reading; `backend/` on this
  branch stays the unmodified transport snapshot.

Results: [docs/results.md](../../docs/results.md) section "UCCL-EP CPU proxy vs direct GIN", records under
[evidence/gates-3865330/](../../evidence/gates-3865330/), full write-up [docs/history/11_05_UCCL_Comparison.md](../../docs/history/11_05_UCCL_Comparison.md).
