# Qualification harness

- `pipeline_v1/`: snapshot packaging (`package.py`), launcher, the Slurm controller and node
  scripts (`runner/`), gate validation and analysis scripts. A snapshot is an immutable copy of
  the backend plus the DeepEP archive, a `sequence.json` of gates and a hashed `manifest.json`.
  The controller runs gates serially inside one allocation, validates exact correctness before any
  timing, and writes `STARTED.json` / `FINISHED.json` per gate.
- `pipeline_1101/`: packagers for the final campaign's snapshots (`package_*_1101.py`), the knob
  preparation scripts (`prepare_packed_combine.py`, `prepare_first_batch.py`), the raw NIC probe
  (`offset_probe.cu`) and analysis entry points: `summarize_arms.py` (per-arm medians across
  repeat gates), `fit_size_sweep.py` (bound ratios and least-squares fits), `trace_timeline.py`
  (device-trace milestones).

- `pipeline_1102/`: the signal-path round (prepare/package scripts for the lean, double-buffer, debug,
  isolation and trace snapshots; `prestage_requests.py` to queue gates into an allocation before it
  starts; `effective_rate.py` (headline and `--wall` throughput metrics against the 22.5 GB/s bound);
  `rank_hist.py` (per-rank timing histograms); `launch_debug_1102.py` (25-minute debug-partition
  launcher), the evening slice packagers (`package_*_dbg*_1102.py`, `package_credit_trace_1102.py`),
  `prepare_credit_1102.py` / `prepare_prewarm_1102.py`, and the trace analyses `wire_curve.py`,
  `receiver_duty.py`, `combine_prewire.py`, `put_split.py`). The 2026-11-03 additions are
  `prepare_ringdiag_1103.py` (ring mapping diagnostics and `CXI_RING_ACCESS=ats`, host code only) with
  its timing and trace packagers `package_ringdiag_1103.py` / `package_ringdiag_trace_1103.py`, and
  `prepare_stagger_1103.py` with `package_stagger_trace_1103.py` / `package_stagger_dbg_1103.py` (dispatch
  channel start stagger, `CXI_EP_STAGGER_NS`, traced and untraced) and `stagger_split.py` (first PUT by
  channel band).
  The afternoon's combine round adds `prepare_combine_1103.py` (kernel knobs `CXI_EP_COMBINE_FIRST_TAIL`
  and `CXI_EP_COMBINE_SPLIT_BARRIER`), its packagers `package_combine_1103.py` / `package_combine_trace_1103.py`
  / `package_combine2..4_1103.py` (rounds 1–4), and `combine_captures.py` (per-capture combine timeline from
  the device traces: barrier end, first local token, first/last PUT, tail arrivals, kernel end, wire phase).
- `link_rate_1102/`: the `cxi_write_bw` link-rate measurement (sbatch drivers for the three
  jobs, a wrapper with connect retry and service-ID handling, node inventory, and
  `collect_write_bw.py` which fetches a job's outputs and tabulates them).

These scripts were written for the original working-tree layout (`tools/cxi_gin/experiments/...`
next to `results/...`) and the campaign root on Clariden scratch. Run them from the `debug` branch,
which keeps that layout, or adjust the path constants at the top of each script.
