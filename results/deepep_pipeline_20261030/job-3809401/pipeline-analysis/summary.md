# Progress batching: PARTIAL

Untraced median of per-iteration rank-max latency; repeats share one node pair.

| Tokens/rank | Update interval | Operation | Repeats | Median ms | Repeat range ms |
|---:|---:|---|---:|---:|---|
| 4096 | 3 | combine | 1 | 3.6632 | 3.6632–3.6632 |
| 4096 | 3 | dispatch_cached | 1 | 2.7729 | 2.7729–2.7729 |
| 4096 | 3 | dispatch_fresh | 1 | 2.7616 | 2.7616–2.7616 |
| 4096 | 6 | combine | 1 | 3.6559 | 3.6559–3.6559 |
| 4096 | 6 | dispatch_cached | 1 | 2.5402 | 2.5402–2.5402 |
| 4096 | 6 | dispatch_fresh | 1 | 2.5582 | 2.5582–2.5582 |
| 4096 | 8 | combine | 1 | 3.7132 | 3.7132–3.7132 |
| 4096 | 8 | dispatch_cached | 1 | 2.5191 | 2.5191–2.5191 |
| 4096 | 8 | dispatch_fresh | 1 | 2.5298 | 2.5298–2.5298 |
| 4096 | 16 | combine | 1 | 3.7702 | 3.7702–3.7702 |
| 4096 | 16 | dispatch_cached | 1 | 2.4443 | 2.4443–2.4443 |
| 4096 | 16 | dispatch_fresh | 1 | 2.4975 | 2.4975–2.4975 |
| 16384 | 3 | combine | 1 | 14.0644 | 14.0644–14.0644 |
| 16384 | 3 | dispatch_cached | 1 | 10.4931 | 10.4931–10.4931 |
| 16384 | 3 | dispatch_fresh | 1 | 10.4811 | 10.4811–10.4811 |
| 16384 | 6 | combine | 1 | 14.1222 | 14.1222–14.1222 |
| 16384 | 6 | dispatch_cached | 1 | 10.0727 | 10.0727–10.0727 |
| 16384 | 6 | dispatch_fresh | 1 | 10.0681 | 10.0681–10.0681 |
| 16384 | 8 | combine | 1 | 14.2219 | 14.2219–14.2219 |
| 16384 | 8 | dispatch_cached | 1 | 9.9632 | 9.9632–9.9632 |
| 16384 | 8 | dispatch_fresh | 1 | 9.9758 | 9.9758–9.9758 |
| 16384 | 16 | combine | 1 | 14.2588 | 14.2588–14.2588 |
| 16384 | 16 | dispatch_cached | 1 | 9.6984 | 9.6984–9.6984 |
| 16384 | 16 | dispatch_fresh | 1 | 9.7327 | 9.7327–9.7327 |

Do not add role intervals or infer NIC wire bandwidth from these end-to-end times.
