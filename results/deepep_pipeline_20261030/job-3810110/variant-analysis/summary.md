# Qualified untraced results

Medians of per-iteration rank-max latency. Three repeats are required per configuration; pending groups are not inferred from completed groups. Same node pair; not cross-allocation replication.

| Snapshot / variant | Experiment | Contexts / SMs / interval | Model / tokens / dtype / routing | Operation | Repeats | Median ms | Range ms |
|---|---|---|---|---|---:|---:|---|
| source-local-logs-v1 / marker-zero | local-logs | 129 / 64 / 3 | v4flash / 4096 / fp8 / mixed | combine | 3/3 | 3.3283 | 3.2975–3.3513 |
| source-local-logs-v1 / marker-zero | local-logs | 129 / 64 / 3 | v4flash / 4096 / fp8 / mixed | dispatch_cached | 3/3 | 2.7582 | 2.7519–2.7607 |
| source-local-logs-v1 / marker-zero | local-logs | 129 / 64 / 3 | v4flash / 4096 / fp8 / mixed | dispatch_fresh | 3/3 | 2.7678 | 2.7524–2.7691 |
| source-local-logs-v1 / marker-zero | local-logs | 129 / 64 / 3 | v4flash / 16384 / fp8 / mixed | combine | 3/3 | 12.8561 | 12.8476–12.9399 |
| source-local-logs-v1 / marker-zero | local-logs | 129 / 64 / 3 | v4flash / 16384 / fp8 / mixed | dispatch_cached | 3/3 | 10.3866 | 10.3772–10.3871 |
| source-local-logs-v1 / marker-zero | local-logs | 129 / 64 / 3 | v4flash / 16384 / fp8 / mixed | dispatch_fresh | 3/3 | 10.3708 | 10.3648–10.4159 |
| source-local-runtime-v1 / marker-control | marker-matched-control | 129 / 64 / 3 | v4flash / 4096 / fp8 / mixed | combine | 3/3 | 3.7847 | 3.7731–3.7946 |
| source-local-runtime-v1 / marker-control | marker-matched-control | 129 / 64 / 3 | v4flash / 4096 / fp8 / mixed | dispatch_cached | 3/3 | 2.6619 | 2.6501–2.6627 |
| source-local-runtime-v1 / marker-control | marker-matched-control | 129 / 64 / 3 | v4flash / 4096 / fp8 / mixed | dispatch_fresh | 3/3 | 2.6699 | 2.6616–2.6762 |
| source-local-runtime-v1 / marker-control | marker-matched-control | 129 / 64 / 3 | v4flash / 16384 / fp8 / mixed | combine | 3/3 | 14.7147 | 14.6501–14.7343 |
| source-local-runtime-v1 / marker-control | marker-matched-control | 129 / 64 / 3 | v4flash / 16384 / fp8 / mixed | dispatch_cached | 3/3 | 10.6428 | 10.6261–10.6578 |
| source-local-runtime-v1 / marker-control | marker-matched-control | 129 / 64 / 3 | v4flash / 16384 / fp8 / mixed | dispatch_fresh | 3/3 | 10.6232 | 10.5710–10.6537 |
| source-local-runtime-v1 / marker-zero | marker-matched-zero | 129 / 64 / 3 | v4flash / 4096 / fp8 / mixed | combine | 3/3 | 3.3093 | 3.2880–3.3122 |
| source-local-runtime-v1 / marker-zero | marker-matched-zero | 129 / 64 / 3 | v4flash / 4096 / fp8 / mixed | dispatch_cached | 3/3 | 2.7638 | 2.7483–2.7678 |
| source-local-runtime-v1 / marker-zero | marker-matched-zero | 129 / 64 / 3 | v4flash / 4096 / fp8 / mixed | dispatch_fresh | 3/3 | 2.7639 | 2.7577–2.7640 |
| source-local-runtime-v1 / marker-zero | marker-matched-zero | 129 / 64 / 3 | v4flash / 16384 / fp8 / mixed | combine | 3/3 | 12.7245 | 12.7143–12.8585 |
| source-local-runtime-v1 / marker-zero | marker-matched-zero | 129 / 64 / 3 | v4flash / 16384 / fp8 / mixed | dispatch_cached | 3/3 | 10.3781 | 10.3756–10.3849 |
| source-local-runtime-v1 / marker-zero | marker-matched-zero | 129 / 64 / 3 | v4flash / 16384 / fp8 / mixed | dispatch_fresh | 3/3 | 10.3883 | 10.3783–10.4110 |
| source-zero-packed-v7 / marker-zero | packed-i16 | 129 / 64 / 16 | v4flash / 4096 / fp8 / mixed | combine | 3/3 | 3.3099 | 3.2986–3.3617 |
| source-zero-packed-v7 / marker-zero | packed-i16 | 129 / 64 / 16 | v4flash / 4096 / fp8 / mixed | dispatch_cached | 3/3 | 1.0527 | 1.0504–1.0547 |
| source-zero-packed-v7 / marker-zero | packed-i16 | 129 / 64 / 16 | v4flash / 4096 / fp8 / mixed | dispatch_fresh | 3/3 | 1.0606 | 1.0602–1.0619 |
| source-zero-packed-v7 / marker-zero | packed-i16 | 129 / 64 / 16 | v4flash / 16384 / fp8 / mixed | combine | 3/3 | 12.8010 | 12.7468–12.8089 |
| source-zero-packed-v7 / marker-zero | packed-i16 | 129 / 64 / 16 | v4flash / 16384 / fp8 / mixed | dispatch_cached | 3/3 | 3.4908 | 3.4901–3.4926 |
| source-zero-packed-v7 / marker-zero | packed-i16 | 129 / 64 / 16 | v4flash / 16384 / fp8 / mixed | dispatch_fresh | 3/3 | 3.4981 | 3.4930–3.5031 |
| source-zero-packed-v7 / marker-zero | packed-i16-q129 | 129 / 64 / 16 | v4flash / 4096 / fp8 / mixed | combine | 3/3 | 3.3002 | 3.2730–3.3454 |
| source-zero-packed-v7 / marker-zero | packed-i16-q129 | 129 / 64 / 16 | v4flash / 4096 / fp8 / mixed | dispatch_cached | 3/3 | 1.0419 | 1.0409–1.0541 |
| source-zero-packed-v7 / marker-zero | packed-i16-q129 | 129 / 64 / 16 | v4flash / 4096 / fp8 / mixed | dispatch_fresh | 3/3 | 1.0594 | 1.0577–1.0687 |
| source-zero-packed-v7 / marker-zero | packed-i16-q129 | 129 / 64 / 16 | v4flash / 16384 / fp8 / mixed | combine | 3/3 | 12.7615 | 12.7188–12.8398 |
| source-zero-packed-v7 / marker-zero | packed-i16-q129 | 129 / 64 / 16 | v4flash / 16384 / fp8 / mixed | dispatch_cached | 3/3 | 3.4810 | 3.4682–3.4876 |
| source-zero-packed-v7 / marker-zero | packed-i16-q129 | 129 / 64 / 16 | v4flash / 16384 / fp8 / mixed | dispatch_fresh | 3/3 | 3.4986 | 3.4739–3.5015 |
| source-zero-packed-v7 / marker-zero | packed-i16-q257 | 257 / 64 / 16 | v4flash / 4096 / fp8 / mixed | combine | 3/3 | 3.4147 | 3.3944–3.4439 |
| source-zero-packed-v7 / marker-zero | packed-i16-q257 | 257 / 64 / 16 | v4flash / 4096 / fp8 / mixed | dispatch_cached | 3/3 | 1.1912 | 1.1905–1.2102 |
| source-zero-packed-v7 / marker-zero | packed-i16-q257 | 257 / 64 / 16 | v4flash / 4096 / fp8 / mixed | dispatch_fresh | 3/3 | 1.2004 | 1.1947–1.2010 |
| source-zero-packed-v7 / marker-zero | packed-i16-q257 | 257 / 64 / 16 | v4flash / 16384 / fp8 / mixed | combine | 3/3 | 12.8051 | 12.7589–12.8906 |
| source-zero-packed-v7 / marker-zero | packed-i16-q257 | 257 / 64 / 16 | v4flash / 16384 / fp8 / mixed | dispatch_cached | 3/3 | 3.6562 | 3.6556–3.6595 |
| source-zero-packed-v7 / marker-zero | packed-i16-q257 | 257 / 64 / 16 | v4flash / 16384 / fp8 / mixed | dispatch_fresh | 3/3 | 3.6763 | 3.6703–3.6806 |
| source-zero-packed-v7 / marker-zero | rows-i16 | 129 / 64 / 16 | v4flash / 4096 / fp8 / mixed | combine | 3/3 | 3.3141 | 3.3117–3.3304 |
| source-zero-packed-v7 / marker-zero | rows-i16 | 129 / 64 / 16 | v4flash / 4096 / fp8 / mixed | dispatch_cached | 3/3 | 2.3192 | 2.3180–2.3324 |
| source-zero-packed-v7 / marker-zero | rows-i16 | 129 / 64 / 16 | v4flash / 4096 / fp8 / mixed | dispatch_fresh | 3/3 | 2.3761 | 2.3747–2.3865 |
| source-zero-packed-v7 / marker-zero | rows-i16 | 129 / 64 / 16 | v4flash / 16384 / fp8 / mixed | combine | 3/3 | 12.7595 | 12.7440–12.8080 |
| source-zero-packed-v7 / marker-zero | rows-i16 | 129 / 64 / 16 | v4flash / 16384 / fp8 / mixed | dispatch_cached | 3/3 | 8.9151 | 8.8667–8.9283 |
| source-zero-packed-v7 / marker-zero | rows-i16 | 129 / 64 / 16 | v4flash / 16384 / fp8 / mixed | dispatch_fresh | 3/3 | 8.9123 | 8.9093–8.9516 |
| source-zero-packed-v7 / marker-zero | zero-packed | 129 / 64 / 3 | v4flash / 4096 / fp8 / mixed | combine | 3/3 | 3.3213 | 3.2810–3.3236 |
| source-zero-packed-v7 / marker-zero | zero-packed | 129 / 64 / 3 | v4flash / 4096 / fp8 / mixed | dispatch_cached | 3/3 | 2.2059 | 2.2026–2.2089 |
| source-zero-packed-v7 / marker-zero | zero-packed | 129 / 64 / 3 | v4flash / 4096 / fp8 / mixed | dispatch_fresh | 3/3 | 2.1980 | 2.1898–2.2034 |
| source-zero-packed-v7 / marker-zero | zero-packed | 129 / 64 / 3 | v4flash / 16384 / fp8 / mixed | combine | 3/3 | 12.7922 | 12.7293–12.8042 |
| source-zero-packed-v7 / marker-zero | zero-packed | 129 / 64 / 3 | v4flash / 16384 / fp8 / mixed | dispatch_cached | 3/3 | 8.7089 | 8.6770–8.7134 |
| source-zero-packed-v7 / marker-zero | zero-packed | 129 / 64 / 3 | v4flash / 16384 / fp8 / mixed | dispatch_fresh | 3/3 | 8.6983 | 8.6860–8.6991 |
| source-zero-packed-v7 / marker-zero | zero-rows | 129 / 64 / 3 | v4flash / 4096 / fp8 / mixed | combine | 3/3 | 3.3129 | 3.2920–3.3350 |
| source-zero-packed-v7 / marker-zero | zero-rows | 129 / 64 / 3 | v4flash / 4096 / fp8 / mixed | dispatch_cached | 3/3 | 2.7678 | 2.7610–2.7734 |
| source-zero-packed-v7 / marker-zero | zero-rows | 129 / 64 / 3 | v4flash / 4096 / fp8 / mixed | dispatch_fresh | 3/3 | 2.7558 | 2.7518–2.7573 |
| source-zero-packed-v7 / marker-zero | zero-rows | 129 / 64 / 3 | v4flash / 16384 / fp8 / mixed | combine | 3/3 | 12.8579 | 12.7674–12.8655 |
| source-zero-packed-v7 / marker-zero | zero-rows | 129 / 64 / 3 | v4flash / 16384 / fp8 / mixed | dispatch_cached | 3/3 | 10.3689 | 10.3600–10.4145 |
| source-zero-packed-v7 / marker-zero | zero-rows | 129 / 64 / 3 | v4flash / 16384 / fp8 / mixed | dispatch_fresh | 3/3 | 10.3807 | 10.3693–10.4049 |
