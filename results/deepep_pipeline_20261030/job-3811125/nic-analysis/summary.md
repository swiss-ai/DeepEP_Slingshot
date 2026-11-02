# Measured NIC octet rates

Median across eight ports within each repeat, then median across available repeats. Each direction is separate; TX and RX are not added. All eight ranks must have passed the EP gate.

| Snapshot / variant | Experiment | Operation | Direction | Repeats | GB/s per port | MB per call per port | Window ms/call |
|---|---|---|---|---:|---:|---:|---:|
| source-zero-packed-v7 / marker-zero | allocation2-packed-i16-q129 / v4flash / 4096 tokens / fp8 | combine | RX | 1/3 | 11.189 | 36.050 | 3.2220 |
| source-zero-packed-v7 / marker-zero | allocation2-packed-i16-q129 / v4flash / 4096 tokens / fp8 | combine | TX | 1/3 | 11.143 | 35.902 | 3.2220 |
| source-zero-packed-v7 / marker-zero | allocation2-packed-i16-q129 / v4flash / 4096 tokens / fp8 | cycle | RX | 1/3 | 12.824 | 54.681 | 4.2640 |
| source-zero-packed-v7 / marker-zero | allocation2-packed-i16-q129 / v4flash / 4096 tokens / fp8 | cycle | TX | 1/3 | 12.791 | 54.542 | 4.2640 |
| source-zero-packed-v7 / marker-zero | allocation2-packed-i16-q129 / v4flash / 4096 tokens / fp8 | dispatch_cached | RX | 1/3 | 18.035 | 18.683 | 1.0359 |
| source-zero-packed-v7 / marker-zero | allocation2-packed-i16-q129 / v4flash / 4096 tokens / fp8 | dispatch_cached | TX | 1/3 | 17.992 | 18.639 | 1.0359 |
| source-zero-packed-v7 / marker-zero | allocation2-packed-i16-q129 / v4flash / 4096 tokens / fp8 | dispatch_fresh | RX | 1/3 | 17.873 | 18.651 | 1.0435 |
| source-zero-packed-v7 / marker-zero | allocation2-packed-i16-q129 / v4flash / 4096 tokens / fp8 | dispatch_fresh | TX | 1/3 | 17.862 | 18.640 | 1.0436 |

Rates use the telemetry counter timestamps, recomputed from before/after octets. Windows include repeated operations, readiness/barrier and protocol traffic. They are not instantaneous link utilization, useful-payload throughput, or isolated transfer time. The port CSV retains directional imbalance and window duration; no cross-node clock alignment is assumed.
