# Direct CXI pipeline campaign

Pinned DeepEP bd1e1669. Start from the qualified threshold-completion transport.
First isolate progress publication frequency (3/6/8/16 tokens) before changing
transport aggregation or asynchronous completion. All source snapshots and
runtimes are private and immutable; request-specific JIT caches and compiler
reports record the actual compile-time settings.

`package.py OUTPUT` creates 20 correctness, timing and trace gates. `launch.py`
stages, compile-checks, submits a four-hour two-node allocation and starts a
detached read-only collector. The controller holds the allocation for debugging,
pauses on failure, and accepts additional immutable requests after a reasoned
resume. It does not diagnose or patch by itself. The active agent handles that.

`analyze.py JOB_DIRECTORY` summarizes qualified ordinary timing runs and rejects
missing compiler evidence. It labels incomplete repeats as partial. Traces use
the existing per-rank role/wait analysis and are not ordinary performance data.

The 24-hour campaign window is recorded in `results/deepep_pipeline_20261030/campaign.json`.
Detailed findings and decisions belong in `10_30_DeepEP_v2_Slingshot.md`.

Additional controlled experiments:

- `package_ladder.py`: prepacked public-GIN transfers, varying PUT granularity,
  progress frequency and context count. `analyze_ladder.py` reports payload
  correctness, rank-max CUDA latency and local producer timestamps. This is not
  complete EP performance and does not include NVLink forwarding.
- `prepare_aggregation.py` / `package_aggregation.py`: bounded TX doorbell
  publication; preserve per-PUT completion, descriptor fences and context locking.
- `prepare_delivery.py` / `package_delivery.py`: matched ABI-v3 control versus
  CT_SEND payloads followed by same-destination-window delivery completion.
  Source lifetime extends through flush. The discarded scratch-window v1 design
  must not be deployed: separate registrations have different destination PIDs.
- `run_external.py JOB SNAPSHOT SEQUENCE`: use a candidate's own qualification
  code inside a deliberately held allocation. Requires a planned pause with
  `external_executor: true`, all completed original gates passing, no competing
  executor, and sufficient allocation time. Never launches alongside the main
  sequence. It records executor and sequence hashes, stops on failure, and does
  not automatically resume the original controller.
- `analyze_variants.py`: separate snapshot, variant, context count, progress
  interval, experiment family, model, datatype and routing when summarizing
  untraced repeats. Geometry and size-sweep repeats must not be merged.
- `prepare_hw_fence.py` / `package_hw_fence.py`: native CQ fence before strong
  signals; explicit completion still waits for CT observation. Each variant
  requires its own GPU correctness gates before timing is interpreted.
- `prepare_credit_cache.py` / `package_credit_cache.py`: conservative cached TX
  credits, with the installed libcxi low-water refresh policy. ABI4 uses existing
  context padding; cached credits never imply delivery completion.
- `prepare_cq_policy.py` / `package_cq_policy.py`: matched host-side TX queue
  writeback policy, using identical GPU code. CT trigger queues retain ALWAYS;
  validation requires the requested policy in every GPU's allocation inventory.
  The default remains ALWAYS. Compilation does not qualify the new policy on GPU.
- `prepare_idc_state.py` / `package_idc_state.py`: private ABI5 matched control
  versus reuse of unchanged IDC command state under the existing context lock.
  Retains native fencing, delivery completion and uncached TX credit checks.
  Field changes reprogram state; fresh queues invalidate it. Requires public GIN,
  queue reuse, wrap/producers and sustained EP qualification before timing.
- `package_packed_debug.py`: reproduce the tiny-token unpacked-control timeout
  with read-only host diagnostics and separate cycle dispatch/combine markers.
  `preflight_diagnostic_update.py` requires byte-identical GPU/transport/runtime
  compilation inputs; diagnostic timings are not ordinary performance samples.
- `prepare_packed_rows.py` / `package_packed_rows.py`: separate EP8 dispatch
  staging/PUT-coalescing experiment, with unchanged CXI transport, combine and
  progress notification cadence. Uses exact per-channel capacities in the
  existing source allocation. Requires irregular-size, dropped-token and normal
  routing correctness checks. Ordinary builds only: the runner rejects tracing
  until relocated-PUT instrumentation is adapted. `preflight_packed_rows.py`
  compiles actual fresh/cached FP8/BF16 templates with explicit GCC 13; its
  compile success does not establish GPU correctness.
- `prepare_probe_readiness.py`: raw wrap-test host readiness handshake after
  allocation and kernel loading, before its bounded GPU protocol timeout.
  `preflight_probe_update.py` rebuilds that probe and verifies all other source
  and runtime compilation inputs against its qualified parent.
- `run_followup.py JOB SNAPSHOT_NAME...`: execute declared immutable phases in
  the planned hold, stop on any failure, and request the main controller's
  health-checked resume only after all declared gates pass.
- `run_after_trace.py`: wait for the declared trace boundary, claim a planned
  hold without interrupting a GPU step, verify prerequisite gates and run the
  immutable post-trace plan with each candidate's validator. Stop on failure or
  insufficient allocation time; never run alongside another executor.
- `analyze_nic_windows.py`: verify and summarize separate TX/RX telemetry octet
  rates for the independent repeated-operation windows. These rates include
  protocol/control traffic and are not instantaneous link occupancy.
- `summarize_fence.py`: compare the native-fence variants only after all three
  qualified ordinary repeats are collected. Reports latency, repeat range and
  matched-control improvement separately from NIC measurement windows.
- `analyze_trace.py GATE_DIRECTORY`: require a qualified complete eight-rank
  trace, compare recording-disabled before/after with enabled latency, and
  report per-role clipped wait unions. Category intervals overlap; none is
  interpreted as isolated wire time. Disabled instrumented builds remain
  separate from ordinary performance results.
- `repair_trace_decoder.py` / `preflight_decoder_update.py`: synchronize the
  actual benchmark-imported decoder with the runner copy, preserve GPU source
  and runtime identity, and test valid/invalid event records before recapture.
- `package_credit_debug.py`: prepare a diagnostic-only reproduction with host
  phase markers and an observer of existing GPU diagnostic pages. It submits
  no NIC work and does not change GPU code; its timings are not performance.
- `analyze_lock_owners.py`: intersect a selected warp's lock waits with another
  warp's lock-held stages on the same GPU/context. Reconcile the lock union with
  the role analysis and retain per-context waiter/owner pairs. Overlap evidence
  is not a claim about NIC wire time or fully recoverable latency.
- `compare_traces.py`: require all five repaired trace gates and their ordinary
  timing repeats, then generate timing bars and overlapping stage heatmaps.
- `validate_trace.py`: require events appropriate to compiled native-fence and
  delivery-batching settings. Native dispatch uses event 211 instead of GPU
  flush/writeback events 203/207; combine retains explicit completion checks.
- `run_ready_plan.py`: run hashed sequences through the configuration-aware
  external executor inside an explicitly owned pause; stop on failure/deadline
  and health-check resume only after every phase passes.
- `prepare_release_checks.py`: prepare, without submitting, geometry correctness,
  three timing/size repeats and actual SGLang integration checks for a candidate
  with three qualified ordinary repeats. The reduced-width expert smoke is not
  full-model serving qualification. Copy request files individually; the output
  inventory is metadata, not a controller request.

The delivery raw-wrap gate counts its added completion-marker commands. It must
use its candidate's validator, not the original controller's older fixed count.
All candidates must pass public GIN, queue-wrap/source-reuse, concurrent producer
and full-EP correctness gates before performance comparisons are promoted.

Recent diagnostic extensions:

- `diagnostic_watch_local.py` records host call boundaries in bounded local
  tmpfs and uses an independent subprocess to copy them to shared storage.
  `test_local_watch.py` verifies progress while the parent holds the GIL. GPU
  diagnostic polling remains advisory; these host times are not NIC timestamps.
- `package_marker_probe.py` / `marker_mutation_probe.cuh` test whether a late
  delivery-completion marker rewrites a consumed/cleared notification. The
  legacy replay case deliberately expects corruption and is a negative
  diagnostic, never a transport qualification. The zero-byte marker is a new
  experimental transport choice requiring all correctness gates.
- `package_nic_telemetry.py` / `nic_extra.py` capture source-described NIC command,
  packet and stall counters during separate repeated-operation windows. Counter
  cycles are not added together or treated as GPU critical-path milliseconds.
