# EP8 FP8 token-size sweep

All 24 size/repeat cases passed correctness. Three warmed runs on one node pair; fixed routing seed and fixed SM/context counts.

| Tokens/rank | Dispatch median (ms) | Range across repeats (ms) | Serialization bound (ms) | Effective payload GB/s |
|---:|---:|---:|---:|---:|
| 2048 | 1.4857 | 1.4813–1.4957 | 0.3539 | 5.955 |
| 4096 | 2.7813 | 2.7732–2.7873 | 0.7078 | 6.362 |
| 6144 | 4.0650 | 4.0594–4.0682 | 1.0617 | 6.529 |
| 8192 | 5.3159 | 5.3114–5.3183 | 1.4156 | 6.657 |
| 10240 | 6.6009 | 6.5996–6.6102 | 1.7695 | 6.702 |
| 12288 | 7.9100 | 7.8991–7.9282 | 2.1234 | 6.711 |
| 14336 | 9.1574 | 9.1507–9.1658 | 2.4773 | 6.763 |
| 16384 | 10.4615 | 10.4517–10.4657 | 2.8312 | 6.766 |

Linear fit: intercept 0.2124 ms; slope 0.1447 ms/MB; incremental effective throughput 6.912 GB/s; R² 1.0000.

T = intercept + slope * max per-rail payload MB. Warm per-call intercept, not startup. Slope includes per-token packing/queue/signaling; not NIC DMA bandwidth. Repeat ranges are not confidence intervals.

Inspect residuals and repeat consistency before calling the gap fixed or bandwidth-limited. A size-dependent slope can reflect software per-token work as well as network throughput.
