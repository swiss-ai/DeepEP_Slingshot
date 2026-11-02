# Bounded asynchronous CXI TX experiment

DeepEP bd1e1669; private direct-CXI GIN type 6; two GH200 nodes / EP8.
The first variant changes TX command-slot reuse only: reserve capacity, publish
one command, ring once, return. Context locking, completion counters, system
fences and flush-before-signal behavior remain conservative. GPU performance
and correctness qualification are required before promotion.

`package.py` snapshots source, DeepEP/fmt, runner and the 16-step sequence.
`install.py` copies the hash-verified baseline NCCL library into two private
prefixes and overlays the candidate headers in `async`. All consuming DeepEP
extensions and test kernels are compiled afresh in private workspaces.
`preflight.sh` in the campaign results directory compiles SM90 probes without
executing GPUs. CPU credit tests include delayed consumer writeback and wrap.

`run.sbatch` requests one four-hour normal allocation (2 nodes, 8 GPUs).
`controller.py` runs sequential srun steps, gates performance on correctness,
records each attempt and pauses on failure. `monitor.py` is a read-only local
collector: every 30 seconds it checks Slurm and pulls live logs/results. It does
not modify code or automatically diagnose/fix failures.

Remote campaign: `/iopsstor/scratch/cscs/zyu/deepep-async-20261029`.
For job J, control directory is `jobs/J`:

- `status.json`: READY, RUNNING_STEP, PAUSED_FOR_DEBUG, IDLE_FOR_DEBUG or FINISHED.
- `results/NAME/STARTED.json`, `FINISHED.json`, `launch.log`: attempt evidence.
- `builds/SNAPSHOT/VARIANT/nodeN/build.log`: native build output.
- `requests/NAME.json`: an atomically published request, with a new unique name.
- `PAUSED.json`: failed attempt and reason. Independent new tests require an
  explicit `RESUME.json` containing a nonempty `reason`; the controller first
  runs a bounded two-node GPU health check. Failed descendants are marked
  BLOCKED; they do not run or qualify. A corrected attempt must name only
  successful prerequisites, and dependent followups must refer to that retry.
- `STOP`: exit after the active bounded attempt. Slurm cancellation is needed
  for immediate interruption. SIGTERM also terminates the active step.

For a patch during the allocation, stage a NEW snapshot and NEW runtime prefix,
verify their manifests, and submit new requests selecting that variant. Never
edit an active attempt's sources or library files. The build cache is separated
by snapshot name, variant and node; JIT output is separated by attempt and node.
The root controller itself remains the submitted snapshot version.

No step may exceed 1800 seconds or the remaining allocation minus 180 seconds.
After completion or failure, the controller stays available for up to 45 idle
minutes, bounded by the actual allocation deadline. It cannot extend Slurm time
or guarantee nodes remain allocated after expiry. Failed hardware/health checks
may end the allocation. Existing request-chain jobs and snapshots are untouched.

This campaign includes fresh and cached dispatch and combine from the existing
EP benchmark. The final SGLang gate exercises the dispatcher and scatter/gather;
it is not a full server/TTFT test and does not qualify real expert GEMMs.
