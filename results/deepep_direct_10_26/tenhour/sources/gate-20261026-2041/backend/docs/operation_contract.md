# Experimental CXI GIN operation contract

Base: NCCL `12df1a11afad322be5a204a2db890161cbf8131d` (v2.32.3-1),
DeepEP `bd1e1669a9324a4a111e3786658f1a4a43151f1e`.
This describes the candidate implementation, not a hardware qualification.

## Ownership and addressing

- The host allocates the Slurm-assigned CXI service/VNI, LNI/CPs, one EQ,
  registered windows/PTEs, and initially one TX CQ plus CT-read CQ per context.
- Every registered window has its own PID/domain and PTE offset zero. A peer
  descriptor contains NIC NID, PID, PID width, DFA, and index extension.
  Remote offsets are relative to the peer PTE; local DMA addresses use the
  local MD's IOVA and LAC. These are CXI resources, not mlx5 QPs/rkeys/WQEs.
- The host uses TCP only for setup/registration metadata exchange. No callback
  submits payload NIC commands after setup. `needsProxyProgress=0` and a null
  progress callback are required; runtime proof still needs the GIN tests.
- GPU descriptors reference GPU-mapped queues/doorbells, completion writeback,
  GPU signal/counter memory, and GPU copies of registered-window descriptors.
  Mutable queue pointers and posted/completed counts belong to the GPU until
  quiescence. The host reads them only before destruction.
- Private backend type 6 and device ABI 1 match across the plugin, NCCL host,
  and exported device headers. NCCL type 3 remains unchanged GDAKI.

## Required operations and implementation

| Operation | Initial implementation | Validation |
|---|---|---|
| Put, including zero-byte | Full DMA commands, runtime bounds, <=1 MiB chunks; zero payload emits no DMA | Raw dynamic sizes/guards; public GIN |
| PutValue <=8 bytes | IDC state + inline PUT | Public GIN tag before strong signal |
| Indexed/VA add or increment | Delivery-complete wait of prior context operations, then 64-bit SUM atomic | Raw READY/ACK; public indexed and VA signals |
| Strong signal | Waits all preceding context transfers, stronger than same-peer minimum | Prior PutValue plus payload visibility before signal |
| Weak signal | Same conservative implementation as strong | Same reference; optimize only after qualification |
| Flush | GPU CT_GET and WB polling until posted commands are ACKed | Source overwrite after completion |
| Public local counter | Increment once per API put after its conservative flush | waitCounter followed by source overwrite |
| FlushAsync/Wait | FlushAsync completes synchronously, returns a typed context-bound request; Wait validates it | Additional request lifetime test still required |
| Read/wait | Public NCCL signal/counter machinery uses CXI pointers | Public GIN tests with bounded waits |
| Reset | Zero only at application-guaranteed quiescence | Reset/reuse test still required |
| Get | Explicit diagnostic/trap; unsupported in this initial EP subset | Engram excluded; no successful stub |

DeepEP EP kernels call Put/PutValue/VA atomic add/Flush and public barrier
signals. The reachable GET in this pinned tree is in `impls/engram_fetch.cuh`,
which is outside dispatch/combine. Audit remains required when enabling other
SGLang paths. The isolated host collectives initially use `NCCL_ALGO=Ring` to
avoid introducing unrelated symmetric-device algorithms during bring-up.

## Completion and concurrency

NIC queue consumption permits command-slot reuse; it does **not** permit
source-buffer reuse. Only transfer completion counters establish the latter.
NIC counters count network commands, whereas public GIN counters count API
operations. These are deliberately separate.

Initial queue emission waits for consumption after every 64-byte queue slot.
A GPU lock serializes operations within a context; different contexts have
independent resources. Conservative ACK waits establish ordering. This is a
correctness-first candidate and is not expected to be performance-optimal.
All waits have device deadlines; public waits additionally accept timeout/
abort parameters. No claim of complete cancellation/lifecycle safety is made
until the lifecycle and failure gate passes.

## Remaining qualification gaps

Hardware tests must establish dynamic transfer correctness, public GIN
semantics, independent/concurrent producers, exact 129-context capacity,
queue wrap, multiwriter adds, reset/request lifetime, and clean repeated
teardown. Resource exhaustion must lead to a separately tested multiplexing
design rather than silently reducing DeepEP's requested concurrency.
