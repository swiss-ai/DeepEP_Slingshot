# Qualification harness

The harness runs immutable **snapshots** (backend + DeepEP archives + `sequence.json` of gates +
hashed `manifest.json`) inside one Slurm allocation: a serial controller validates exact correctness
before any timing, writes `STARTED.json` / `FINISHED.json` per gate, pauses on failure and resumes
only on an explicit `RESUME.json`. It produced every number in [docs/results.md](../docs/results.md).

| Directory | Content |
|---|---|
| `runner/` | The controller and node scripts of the latest snapshot (`source-1103-ep8skew-v3`): `run.sbatch` (two nodes, 4 h), `controller.py`, `node.sh` (per-node clean DeepEP build from the snapshot archive, then `backend/tools/direct_node.sh`), `install.py` (one NCCL runtime prefix per transport variant: copies the tested NCCL build, replaces the `gin/cxi` headers with the snapshot's, prepends the variant's `#define`s to `cxi_primitives.cuh`), `preflight.sh` (login-node compile checks and host-side unit tests), `validate_gate.py` (verdicts), `monitor.py` (read-only collector), `burst_probe.cu` (queue-wrap / source-reuse probe), `package.py`, `launch.py`. |
| `runner-trace/` | The same runner as used by the traced snapshots (`source-1103-combine-trace-v1`): trace-aware `node.sh`, `controller.py`, `preflight.sh`, `prepare_trace.py`, `trace_capture.py`, and the knob-aware `validate_trace.py` that qualifies trace gates built with `CXI_EP_SKIP_COMBINE_FLUSH` / `CXI_EP_LOCAL_SELF_SIGNAL`. |
| `pipeline_v1/` | The 2026-10-30 campaign's packagers, preflights, launch and analysis scripts (transport ladder, delivery batching, native fence, credit cache, packed rows, traces). |
| `pipeline_1101/` | The 2026-11-01 final campaign: snapshot packagers (`package_*_1101.py`), knob preparation (`prepare_packed_combine.py`, `prepare_first_batch.py`), the raw NIC alignment probe (`offset_probe.cu`), `summarize_arms.py`, `fit_size_sweep.py`, `trace_timeline.py`. |
| `pipeline_1102/` | The 2026-11-02/03 rounds: lean signal path, double-buffered staging, cached credits, prewarm, ring diagnostics and ATS, start stagger, combine levers; `effective_rate.py` (headline and `--wall` metrics against the 22.5 GB/s bound), `rank_hist.py`, `launch_debug_1102.py` (25-minute debug-partition launcher), `prestage_requests.py`, and the trace analyses `wire_curve.py`, `receiver_duty.py`, `combine_prewire.py`, `put_split.py`, `stagger_split.py`, `combine_captures.py`. |
| `pipeline_1103/` | The EP8 real-routing demo: `bank_routing.py` and the OpenSWE bank subset `bank_v4flash_openswe_ep8.npz` (same file as `backend/tests/`), `prepare_ep8bank_1103.py`, packagers for the bank, skew-ladder and padded-stride jobs, `bank_table.py`. |
| `link_rate_1102/` | The `cxi_write_bw` NIC ceiling measurement (sbatch drivers, wrapper, `collect_write_bw.py`). |

## Running it

The packagers and launchers were written for the author's working tree (`tools/cxi_gin/experiments/...`
next to `results/...`, the campaign root `/iopsstor/scratch/cscs/zyu/deepep-pipeline-20261030` on
Clariden and the tested NCCL release there). Run them from the `debug` branch, which keeps that
layout, or adjust the constants at the top of each script (`ROOT`, `NEW`, `REMOTE`, `CAMPAIGN`,
`TESTED`). A gate's request is a JSON file; the environment it carries is exactly what
`backend/tools/direct_node.sh` reads (see [docs/usage.md](../docs/usage.md) for the variables), so a
gate can also be reproduced by hand without the controller.

Analysis of a finished job (results mirrored to `job-<id>/results/results/<gate>/`):

```bash
python3 harness/pipeline_1102/effective_rate.py job-3835100/results/results 'leanb-repeat' --ref leanb --wall
python3 harness/pipeline_1101/summarize_arms.py job-3830101/results/results '^85[456]\d-' --ref cand
```
