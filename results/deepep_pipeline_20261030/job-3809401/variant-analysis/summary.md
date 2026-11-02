# Qualified untraced results

Medians of per-iteration rank-max latency. Three repeats are required per configuration; pending groups are not inferred from completed groups. Same node pair; not cross-allocation replication.

| Snapshot / variant | Experiment | Contexts / interval | Model / tokens / dtype / routing | Operation | Repeats | Median ms | Range ms |
|---|---|---|---|---|---:|---:|---|
| source-credit-cache-v2 / credit-control | credit-control | 129 / 3 | v4flash / 4096 / fp8 / mixed | combine | 1/3 | 3.3690 | 3.3690–3.3690 |
| source-credit-cache-v2 / credit-control | credit-control | 129 / 3 | v4flash / 4096 / fp8 / mixed | dispatch_cached | 1/3 | 2.8491 | 2.8491–2.8491 |
| source-credit-cache-v2 / credit-control | credit-control | 129 / 3 | v4flash / 4096 / fp8 / mixed | dispatch_fresh | 1/3 | 2.8586 | 2.8586–2.8586 |
| source-credit-cache-v2 / credit-control | credit-control | 129 / 3 | v4flash / 16384 / fp8 / mixed | combine | 1/3 | 12.9757 | 12.9757–12.9757 |
| source-credit-cache-v2 / credit-control | credit-control | 129 / 3 | v4flash / 16384 / fp8 / mixed | dispatch_cached | 1/3 | 10.5999 | 10.5999–10.5999 |
| source-credit-cache-v2 / credit-control | credit-control | 129 / 3 | v4flash / 16384 / fp8 / mixed | dispatch_fresh | 1/3 | 10.6094 | 10.6094–10.6094 |
| source-delivery-v3 / delivery-batched | delivery-batched | 129 / 3 | v4flash / 4096 / fp8 / mixed | combine | 3/3 | 3.3436 | 3.3264–3.3708 |
| source-delivery-v3 / delivery-batched | delivery-batched | 129 / 3 | v4flash / 4096 / fp8 / mixed | dispatch_cached | 3/3 | 2.8363 | 2.8327–2.8380 |
| source-delivery-v3 / delivery-batched | delivery-batched | 129 / 3 | v4flash / 4096 / fp8 / mixed | dispatch_fresh | 3/3 | 2.8458 | 2.8429–2.8462 |
| source-delivery-v3 / delivery-batched | delivery-batched | 129 / 3 | v4flash / 16384 / fp8 / mixed | combine | 3/3 | 12.8534 | 12.8302–12.8640 |
| source-delivery-v3 / delivery-batched | delivery-batched | 129 / 3 | v4flash / 16384 / fp8 / mixed | dispatch_cached | 3/3 | 10.5911 | 10.5892–10.5952 |
| source-delivery-v3 / delivery-batched | delivery-batched | 129 / 3 | v4flash / 16384 / fp8 / mixed | dispatch_fresh | 3/3 | 10.6006 | 10.5963–10.6097 |
| source-delivery-v3 / delivery-control | delivery-control | 129 / 3 | v4flash / 4096 / fp8 / mixed | combine | 3/3 | 3.8562 | 3.7244–3.8704 |
| source-delivery-v3 / delivery-control | delivery-control | 129 / 3 | v4flash / 4096 / fp8 / mixed | dispatch_cached | 3/3 | 2.8303 | 2.8219–2.8354 |
| source-delivery-v3 / delivery-control | delivery-control | 129 / 3 | v4flash / 4096 / fp8 / mixed | dispatch_fresh | 3/3 | 2.8420 | 2.8420–2.8507 |
| source-delivery-v3 / delivery-control | delivery-control | 129 / 3 | v4flash / 16384 / fp8 / mixed | combine | 3/3 | 14.7360 | 14.6432–14.8229 |
| source-delivery-v3 / delivery-control | delivery-control | 129 / 3 | v4flash / 16384 / fp8 / mixed | dispatch_cached | 3/3 | 10.7026 | 10.7021–10.7117 |
| source-delivery-v3 / delivery-control | delivery-control | 129 / 3 | v4flash / 16384 / fp8 / mixed | dispatch_fresh | 3/3 | 10.7061 | 10.6985–10.7167 |
| source-hw-fence-v3 / fence-batched | fence-batched | 129 / 3 | v4flash / 4096 / fp8 / mixed | combine | 3/3 | 3.3324 | 3.3316–3.3354 |
| source-hw-fence-v3 / fence-batched | fence-batched | 129 / 3 | v4flash / 4096 / fp8 / mixed | dispatch_cached | 3/3 | 2.8147 | 2.8074–2.8216 |
| source-hw-fence-v3 / fence-batched | fence-batched | 129 / 3 | v4flash / 4096 / fp8 / mixed | dispatch_fresh | 3/3 | 2.8181 | 2.8156–2.8182 |
| source-hw-fence-v3 / fence-batched | fence-batched | 129 / 3 | v4flash / 16384 / fp8 / mixed | combine | 3/3 | 12.8814 | 12.8538–12.9656 |
| source-hw-fence-v3 / fence-batched | fence-batched | 129 / 3 | v4flash / 16384 / fp8 / mixed | dispatch_cached | 3/3 | 10.6139 | 10.6039–10.6255 |
| source-hw-fence-v3 / fence-batched | fence-batched | 129 / 3 | v4flash / 16384 / fp8 / mixed | dispatch_fresh | 3/3 | 10.5982 | 10.5896–10.6463 |
| source-hw-fence-v3 / fence-control | fence-control | 129 / 3 | v4flash / 4096 / fp8 / mixed | combine | 3/3 | 3.8485 | 3.8345–3.8613 |
| source-hw-fence-v3 / fence-control | fence-control | 129 / 3 | v4flash / 4096 / fp8 / mixed | dispatch_cached | 3/3 | 2.8357 | 2.8346–2.8373 |
| source-hw-fence-v3 / fence-control | fence-control | 129 / 3 | v4flash / 4096 / fp8 / mixed | dispatch_fresh | 3/3 | 2.8413 | 2.8398–2.8464 |
| source-hw-fence-v3 / fence-control | fence-control | 129 / 3 | v4flash / 16384 / fp8 / mixed | combine | 3/3 | 14.7341 | 14.7044–14.8658 |
| source-hw-fence-v3 / fence-control | fence-control | 129 / 3 | v4flash / 16384 / fp8 / mixed | dispatch_cached | 3/3 | 10.7168 | 10.7094–10.7177 |
| source-hw-fence-v3 / fence-control | fence-control | 129 / 3 | v4flash / 16384 / fp8 / mixed | dispatch_fresh | 3/3 | 10.7233 | 10.7222–10.7235 |
| source-hw-fence-v3 / fence-dc | fence-dc | 129 / 3 | v4flash / 4096 / fp8 / mixed | combine | 3/3 | 3.8456 | 3.8096–3.8464 |
| source-hw-fence-v3 / fence-dc | fence-dc | 129 / 3 | v4flash / 4096 / fp8 / mixed | dispatch_cached | 3/3 | 2.6811 | 2.6808–2.6815 |
| source-hw-fence-v3 / fence-dc | fence-dc | 129 / 3 | v4flash / 4096 / fp8 / mixed | dispatch_fresh | 3/3 | 2.6804 | 2.6726–2.6849 |
| source-hw-fence-v3 / fence-dc | fence-dc | 129 / 3 | v4flash / 16384 / fp8 / mixed | combine | 3/3 | 14.8342 | 14.8279–14.9590 |
| source-hw-fence-v3 / fence-dc | fence-dc | 129 / 3 | v4flash / 16384 / fp8 / mixed | dispatch_cached | 3/3 | 10.4864 | 10.4732–10.5672 |
| source-hw-fence-v3 / fence-dc | fence-dc | 129 / 3 | v4flash / 16384 / fp8 / mixed | dispatch_fresh | 3/3 | 10.4547 | 10.4538–10.4829 |
| source-v1 / threshold | interval16 | 129 / 16 | v4flash / 4096 / fp8 / mixed | combine | 1/3 | 3.7702 | 3.7702–3.7702 |
| source-v1 / threshold | interval16 | 129 / 16 | v4flash / 4096 / fp8 / mixed | dispatch_cached | 1/3 | 2.4443 | 2.4443–2.4443 |
| source-v1 / threshold | interval16 | 129 / 16 | v4flash / 4096 / fp8 / mixed | dispatch_fresh | 1/3 | 2.4975 | 2.4975–2.4975 |
| source-v1 / threshold | interval16 | 129 / 16 | v4flash / 16384 / fp8 / mixed | combine | 1/3 | 14.2588 | 14.2588–14.2588 |
| source-v1 / threshold | interval16 | 129 / 16 | v4flash / 16384 / fp8 / mixed | dispatch_cached | 1/3 | 9.6984 | 9.6984–9.6984 |
| source-v1 / threshold | interval16 | 129 / 16 | v4flash / 16384 / fp8 / mixed | dispatch_fresh | 1/3 | 9.7327 | 9.7327–9.7327 |
| source-v1 / threshold | interval3 | 129 / 3 | v4flash / 4096 / fp8 / mixed | combine | 1/3 | 3.6632 | 3.6632–3.6632 |
| source-v1 / threshold | interval3 | 129 / 3 | v4flash / 4096 / fp8 / mixed | dispatch_cached | 1/3 | 2.7729 | 2.7729–2.7729 |
| source-v1 / threshold | interval3 | 129 / 3 | v4flash / 4096 / fp8 / mixed | dispatch_fresh | 1/3 | 2.7616 | 2.7616–2.7616 |
| source-v1 / threshold | interval3 | 129 / 3 | v4flash / 16384 / fp8 / mixed | combine | 1/3 | 14.0644 | 14.0644–14.0644 |
| source-v1 / threshold | interval3 | 129 / 3 | v4flash / 16384 / fp8 / mixed | dispatch_cached | 1/3 | 10.4931 | 10.4931–10.4931 |
| source-v1 / threshold | interval3 | 129 / 3 | v4flash / 16384 / fp8 / mixed | dispatch_fresh | 1/3 | 10.4811 | 10.4811–10.4811 |
| source-v1 / threshold | interval6 | 129 / 6 | v4flash / 4096 / fp8 / mixed | combine | 1/3 | 3.6559 | 3.6559–3.6559 |
| source-v1 / threshold | interval6 | 129 / 6 | v4flash / 4096 / fp8 / mixed | dispatch_cached | 1/3 | 2.5402 | 2.5402–2.5402 |
| source-v1 / threshold | interval6 | 129 / 6 | v4flash / 4096 / fp8 / mixed | dispatch_fresh | 1/3 | 2.5582 | 2.5582–2.5582 |
| source-v1 / threshold | interval6 | 129 / 6 | v4flash / 16384 / fp8 / mixed | combine | 1/3 | 14.1222 | 14.1222–14.1222 |
| source-v1 / threshold | interval6 | 129 / 6 | v4flash / 16384 / fp8 / mixed | dispatch_cached | 1/3 | 10.0727 | 10.0727–10.0727 |
| source-v1 / threshold | interval6 | 129 / 6 | v4flash / 16384 / fp8 / mixed | dispatch_fresh | 1/3 | 10.0681 | 10.0681–10.0681 |
| source-v1 / threshold | interval8 | 129 / 8 | v4flash / 4096 / fp8 / mixed | combine | 1/3 | 3.7132 | 3.7132–3.7132 |
| source-v1 / threshold | interval8 | 129 / 8 | v4flash / 4096 / fp8 / mixed | dispatch_cached | 1/3 | 2.5191 | 2.5191–2.5191 |
| source-v1 / threshold | interval8 | 129 / 8 | v4flash / 4096 / fp8 / mixed | dispatch_fresh | 1/3 | 2.5298 | 2.5298–2.5298 |
| source-v1 / threshold | interval8 | 129 / 8 | v4flash / 16384 / fp8 / mixed | combine | 1/3 | 14.2219 | 14.2219–14.2219 |
| source-v1 / threshold | interval8 | 129 / 8 | v4flash / 16384 / fp8 / mixed | dispatch_cached | 1/3 | 9.9632 | 9.9632–9.9632 |
| source-v1 / threshold | interval8 | 129 / 8 | v4flash / 16384 / fp8 / mixed | dispatch_fresh | 1/3 | 9.9758 | 9.9758–9.9758 |
