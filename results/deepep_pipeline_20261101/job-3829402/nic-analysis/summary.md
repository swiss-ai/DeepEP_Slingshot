# Measured NIC octet rates

Median across eight ports within each repeat, then median across available repeats. Each direction is separate; TX and RX are not added. All eight ranks must have passed the EP gate.

| Snapshot / variant | Experiment | Operation | Direction | Repeats | GB/s per port | MB per call per port | Window ms/call |
|---|---|---|---|---:|---:|---:|---:|
| source-1101-combine-pack-v2 / marker-zero | both / v4flash / 4096 tokens / fp8 | combine | RX | 3/3 | 19.856 | 35.583 | 1.7913 |
| source-1101-combine-pack-v2 / marker-zero | both / v4flash / 4096 tokens / fp8 | combine | TX | 3/3 | 19.830 | 35.520 | 1.7913 |
| source-1101-combine-pack-v2 / marker-zero | both / v4flash / 4096 tokens / fp8 | cycle | RX | 3/3 | 19.227 | 54.173 | 2.8176 |
| source-1101-combine-pack-v2 / marker-zero | both / v4flash / 4096 tokens / fp8 | cycle | TX | 3/3 | 19.210 | 54.127 | 2.8176 |
| source-1101-combine-pack-v2 / marker-zero | both / v4flash / 4096 tokens / fp8 | dispatch_cached | RX | 3/3 | 18.400 | 18.629 | 1.0124 |
| source-1101-combine-pack-v2 / marker-zero | both / v4flash / 4096 tokens / fp8 | dispatch_cached | TX | 3/3 | 18.378 | 18.606 | 1.0124 |
| source-1101-combine-pack-v2 / marker-zero | both / v4flash / 4096 tokens / fp8 | dispatch_fresh | RX | 3/3 | 18.283 | 18.622 | 1.0181 |
| source-1101-combine-pack-v2 / marker-zero | both / v4flash / 4096 tokens / fp8 | dispatch_fresh | TX | 3/3 | 18.278 | 18.608 | 1.0181 |
| source-1101-combine-pack-v2 / marker-zero | combine / v4flash / 4096 tokens / fp8 | combine | RX | 3/3 | 19.848 | 35.540 | 1.7906 |
| source-1101-combine-pack-v2 / marker-zero | combine / v4flash / 4096 tokens / fp8 | combine | TX | 3/3 | 19.837 | 35.520 | 1.7906 |
| source-1101-combine-pack-v2 / marker-zero | combine / v4flash / 4096 tokens / fp8 | cycle | RX | 3/3 | 19.050 | 54.201 | 2.8458 |
| source-1101-combine-pack-v2 / marker-zero | combine / v4flash / 4096 tokens / fp8 | cycle | TX | 3/3 | 19.031 | 54.160 | 2.8458 |
| source-1101-combine-pack-v2 / marker-zero | combine / v4flash / 4096 tokens / fp8 | dispatch_cached | RX | 3/3 | 17.935 | 18.652 | 1.0400 |
| source-1101-combine-pack-v2 / marker-zero | combine / v4flash / 4096 tokens / fp8 | dispatch_cached | TX | 3/3 | 17.923 | 18.639 | 1.0400 |
| source-1101-combine-pack-v2 / marker-zero | combine / v4flash / 4096 tokens / fp8 | dispatch_fresh | RX | 3/3 | 17.800 | 18.652 | 1.0479 |
| source-1101-combine-pack-v2 / marker-zero | combine / v4flash / 4096 tokens / fp8 | dispatch_fresh | TX | 3/3 | 17.788 | 18.640 | 1.0479 |
| source-1101-combine-pack-v2 / marker-zero | control / v4flash / 4096 tokens / fp8 | combine | RX | 3/3 | 11.004 | 36.100 | 3.2795 |
| source-1101-combine-pack-v2 / marker-zero | control / v4flash / 4096 tokens / fp8 | combine | TX | 3/3 | 10.948 | 35.903 | 3.2795 |
| source-1101-combine-pack-v2 / marker-zero | control / v4flash / 4096 tokens / fp8 | cycle | RX | 3/3 | 12.699 | 54.749 | 4.3112 |
| source-1101-combine-pack-v2 / marker-zero | control / v4flash / 4096 tokens / fp8 | cycle | TX | 3/3 | 12.652 | 54.543 | 4.3112 |
| source-1101-combine-pack-v2 / marker-zero | control / v4flash / 4096 tokens / fp8 | dispatch_cached | RX | 3/3 | 17.899 | 18.658 | 1.0424 |
| source-1101-combine-pack-v2 / marker-zero | control / v4flash / 4096 tokens / fp8 | dispatch_cached | TX | 3/3 | 17.881 | 18.639 | 1.0424 |
| source-1101-combine-pack-v2 / marker-zero | control / v4flash / 4096 tokens / fp8 | dispatch_fresh | RX | 3/3 | 17.741 | 18.651 | 1.0514 |
| source-1101-combine-pack-v2 / marker-zero | control / v4flash / 4096 tokens / fp8 | dispatch_fresh | TX | 3/3 | 17.729 | 18.640 | 1.0514 |
| source-1101-combine-pack-v2 / marker-zero | merge / v4flash / 4096 tokens / fp8 | combine | RX | 3/3 | 10.991 | 36.075 | 3.2829 |
| source-1101-combine-pack-v2 / marker-zero | merge / v4flash / 4096 tokens / fp8 | combine | TX | 3/3 | 10.936 | 35.903 | 3.2829 |
| source-1101-combine-pack-v2 / marker-zero | merge / v4flash / 4096 tokens / fp8 | cycle | RX | 3/3 | 12.741 | 54.703 | 4.2929 |
| source-1101-combine-pack-v2 / marker-zero | merge / v4flash / 4096 tokens / fp8 | cycle | TX | 3/3 | 12.698 | 54.510 | 4.2930 |
| source-1101-combine-pack-v2 / marker-zero | merge / v4flash / 4096 tokens / fp8 | dispatch_cached | RX | 3/3 | 18.413 | 18.627 | 1.0116 |
| source-1101-combine-pack-v2 / marker-zero | merge / v4flash / 4096 tokens / fp8 | dispatch_cached | TX | 3/3 | 18.392 | 18.606 | 1.0116 |
| source-1101-combine-pack-v2 / marker-zero | merge / v4flash / 4096 tokens / fp8 | dispatch_fresh | RX | 3/3 | 18.306 | 18.631 | 1.0188 |
| source-1101-combine-pack-v2 / marker-zero | merge / v4flash / 4096 tokens / fp8 | dispatch_fresh | TX | 3/3 | 18.265 | 18.608 | 1.0188 |

Rates use the telemetry counter timestamps, recomputed from before/after octets. Windows include repeated operations, readiness/barrier and protocol traffic. They are not instantaneous link utilization, useful-payload throughput, or isolated transfer time. The port CSV retains directional imbalance and window duration; no cross-node clock alignment is assumed.
