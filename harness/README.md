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
  `rank_hist.py` (per-rank timing histograms)).
- `link_rate_1102/`: the `cxi_write_bw` link-rate measurement (sbatch drivers for the three
  jobs, a wrapper with connect retry and service-ID handling, node inventory, and
  `collect_write_bw.py` which fetches a job's outputs and tabulates them).

These scripts were written for the original working-tree layout (`tools/cxi_gin/experiments/...`
next to `results/...`) and the campaign root on Clariden scratch. Run them from the `debug` branch,
which keeps that layout, or adjust the path constants at the top of each script.
