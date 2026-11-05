# Evidence

Everything quoted in [docs/results.md](../docs/results.md) and the README is backed by a file here.
The complete records (per-rank timing and correctness journals, logs, device traces, all snapshots)
are on the `debug` branch under `results/deepep_pipeline_20261101/job-<id>/`.

## Snapshots (`snapshots/`)

A snapshot is the immutable unit the harness runs: `backend/`, the DeepEP source archives, a
`sequence.json` of gates, `variants.json` and a `manifest.json` with the SHA-256 of every file.

| Snapshot | Ran as | Content here |
|---|---|---|
| `source-1101-first-batch-v1` | job 3830101 (98 gates), the 2026-11-01 candidate | complete: backend, `DeepEP.tar.gz`, `DeepEP-trace.tar.gz`, runner, manifest, sequence |
| `source-1101-release-h-v1` | release harness of 2026-11-02 (SGLang gates, size sweeps) | complete |
| `source-1102-lean-v1` | job 3835100 (45 gates), **the release matrix of the release candidate** | manifest, sequence, variants; its DeepEP tree = `scripts/apply_patches.sh --profile release`, its backend = `backend/` of `main` at commit `30f20a8`'s lean patch (hashes in the manifest) |
| `source-1105-ucclcmp-v1` | job 3865330 (UCCL comparison) | manifest, sequence, variants; parent ep8skew-v3, differs in the four files under `harness/pipeline_1105/snapshot-files/` |
| `source-1103-ep8skew-v3` | job 3845070 (EP8 skew ladder); parent of nothing later; its code is the current `backend/` and `--profile full` DeepEP tree | manifest, sequence, variants; `backend/` on this branch matches every hashed backend file except `README.md` |

## Gate records (`gates-<job>/<gate>/`)

Per gate: `STARTED.json` and `FINISHED.json` (the request with its full environment, the verdict
and the per-rank qualification), `direct/ep/summary.csv` (per case: `median_rank_max_us`, the
harness headline; `max_host_us_per_iteration`, the slowest rank's wall time per iteration quoted as
the throughput metric) and `direct/ep/repeatability.json` (the headline's median over repeats).

| Directory | Job, date, nodes | What it establishes |
|---|---|---|
| `gates-3830101/` | 2026-11-02, 98 gates | the 2026-11-01 candidate: correctness ladders on three geometries, FP8 and BF16, size sweeps, cadence sweep, six SGLang gates, all PASS |
| `gates-3835100/` | 2026-11-03, nid007560/007561, 54 gates | release matrix of lean-b + kernel knobs (45 gates 9000–9802, all PASS: stress, 4K, dropped-token and sustained-16K ladders for the `kern`, `lean-a`, `lean-b` and `dbuf` arms, nine `lean-b` repeats behind the README table) plus staged diagnostic gates: ring registration (`9A1x`, ATS ring access, PASS) and traced gates `A100`/`A101`/`A110`/`A111` marked FAIL by the holder's older controller, whose inline trace rule predates the skip-flush knob; they were validated offline with the knob-aware validator (`harness/runner-trace/validate_trace.py`), see history log 11_03 §3. `A116` FAIL = killed by a 150 s request budget during a knob rebuild (resubmitted as job 3841702). |
| `gates-3843956/`, `gates-3844086/` | 2026-11-03, nid007481/007499 and nid007656/007666 | combine pre-wire levers: `tail1fb2` −16 µs at 4K vs `lean-b`, `fb2` alone nothing, `fb1` 4× slower (alignment cliff); all PASS |
| `gates-3844569/` | 2026-11-03, nid007649/007656 | EP8 with real OpenSWE routing: 18 bank cases FP8 (`X100`), BF16 (`X101`), with the early tail (`X102`), repeat (`X103`); all PASS |
| `gates-3865330/` | 2026-11-05, nid007536/007542, 7 gates | UCCL-EP CPU proxy (swiss-ai/uccl@54ef064) vs direct GIN, same benchmark in one allocation; `uccl/ep/summary.csv` holds the UCCL cases, `direct/ep/` ours; `uccl/node0/node-inventory.txt` records the UCCL extension hash, libcxi and libfabric; all PASS |
| `gates-3845070/` | 2026-11-03, nid007648/007658 | synthetic receiver-skew ladder and two more bank forwards; `S103` FAIL = the BF16 skew-4 case after a destination reached receive capacity (the stress corner in docs/limitations.md) |

## Probes

- `link-rate/`: HPE `cxi_write_bw` outputs of jobs 3832897, 3833183, 3833451 (NIC ceiling 24.2 GB/s
  unidirectional, 22.5 GB/s bidirectional per direction; `harness/link_rate_1102/collect_write_bw.py`).
- `alignment-probe/`: the raw single-queue probe showing the 128-byte PUT-address cliff of the
  GPU-issued path (`harness/pipeline_1101/offset_probe.cu`).
