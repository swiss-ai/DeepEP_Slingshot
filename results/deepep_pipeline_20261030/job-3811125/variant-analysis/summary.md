# Qualified untraced results

Medians of per-iteration rank-max latency. Three repeats are required per configuration; pending groups are not inferred from completed groups. Same node pair; not cross-allocation replication.

| Snapshot / variant | Experiment | Contexts / SMs / interval | Model / tokens / dtype / routing | Operation | Repeats | Median ms | Range ms |
|---|---|---|---|---|---:|---:|---|
| source-zero-packed-v7 / marker-zero | allocation2-packed-i16-q129 | 129 / 64 / 16 | v4flash / 4096 / fp8 / mixed | combine | 1/3 | 3.3822 | 3.3822–3.3822 |
| source-zero-packed-v7 / marker-zero | allocation2-packed-i16-q129 | 129 / 64 / 16 | v4flash / 4096 / fp8 / mixed | dispatch_cached | 1/3 | 1.0511 | 1.0511–1.0511 |
| source-zero-packed-v7 / marker-zero | allocation2-packed-i16-q129 | 129 / 64 / 16 | v4flash / 4096 / fp8 / mixed | dispatch_fresh | 1/3 | 1.0656 | 1.0656–1.0656 |
| source-zero-packed-v7 / marker-zero | allocation2-packed-i16-q129 | 129 / 64 / 16 | v4flash / 16384 / fp8 / mixed | combine | 1/3 | 13.0246 | 13.0246–13.0246 |
| source-zero-packed-v7 / marker-zero | allocation2-packed-i16-q129 | 129 / 64 / 16 | v4flash / 16384 / fp8 / mixed | dispatch_cached | 1/3 | 3.4934 | 3.4934–3.4934 |
| source-zero-packed-v7 / marker-zero | allocation2-packed-i16-q129 | 129 / 64 / 16 | v4flash / 16384 / fp8 / mixed | dispatch_fresh | 1/3 | 3.4942 | 3.4942–3.4942 |
| source-zero-packed-v7 / marker-zero | allocation2-packed-i16-q257 | 257 / 64 / 16 | v4flash / 4096 / fp8 / mixed | combine | 1/3 | 3.4874 | 3.4874–3.4874 |
| source-zero-packed-v7 / marker-zero | allocation2-packed-i16-q257 | 257 / 64 / 16 | v4flash / 4096 / fp8 / mixed | dispatch_cached | 1/3 | 1.1987 | 1.1987–1.1987 |
| source-zero-packed-v7 / marker-zero | allocation2-packed-i16-q257 | 257 / 64 / 16 | v4flash / 4096 / fp8 / mixed | dispatch_fresh | 1/3 | 1.1870 | 1.1870–1.1870 |
| source-zero-packed-v7 / marker-zero | allocation2-packed-i16-q257 | 257 / 64 / 16 | v4flash / 16384 / fp8 / mixed | combine | 1/3 | 13.0695 | 13.0695–13.0695 |
| source-zero-packed-v7 / marker-zero | allocation2-packed-i16-q257 | 257 / 64 / 16 | v4flash / 16384 / fp8 / mixed | dispatch_cached | 1/3 | 3.6716 | 3.6716–3.6716 |
| source-zero-packed-v7 / marker-zero | allocation2-packed-i16-q257 | 257 / 64 / 16 | v4flash / 16384 / fp8 / mixed | dispatch_fresh | 1/3 | 3.7007 | 3.7007–3.7007 |
