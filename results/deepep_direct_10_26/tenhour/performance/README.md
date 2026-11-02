# Direct CXI GIN performance evidence

Only complete eight-rank EP runs with passing correctness/summary validation
enter these tables. API-only transport probes are excluded. A run can still be
a short diagnostic; use its manifest to check warmups, repeats and timed samples.

`latency_payload.csv` reports per-iteration rank-max latency summaries and the
maximum rail's useful activation bytes. Its ideal floor assumes 25 GB/s in one
direction per NIC and the pinned hybrid algorithm's remote-node deduplication.
It excludes scales, routing metadata, packet headers, acknowledgements, NVLink,
packing, synchronization and launch costs. It is a payload-only lower bound,
not a predicted achievable latency or a measured NIC ceiling.

`nic_mac_rates.csv` contains separately sampled TX/RX MAC-counter window rates,
including synchronization/control traffic and gaps between iterations. Do not
add TX and RX and compare that sum with a single-direction 25 GB/s rating.
Useful activation bandwidth and MAC counter bandwidth have different byte counts.

Fresh dispatch is the primary serving comparison. Cached dispatch is diagnostic.
Process CPU core-equivalents include launches and synchronization; they do not
identify a NIC progress thread. Trace-backed kernel costs and unprofiled timing
samples must remain separate. None of these communication-only results is TTFT.

Before forming a proxy/direct speedup, match model, tokens, dtype, routing, seed,
SM/QP count, source snapshot, warmups, iterations, and route/input hashes. Prefer
the same allocation/node pair. A proxy control is not proof of the best possible
CPU-proxy performance without an independent proxy-tuning sweep.
