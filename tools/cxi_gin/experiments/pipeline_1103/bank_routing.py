"""Bank-consistent routing for the EP8 DeepEP benchmark (2026-11-03 evening).

A trace-bank unit is one 4096-token prefill bucket with its per-layer per-expert token counts
(V4 Flash: 40 MoE layers x 256 experts, every unit sums to 4096 x 6). Eight consecutive units form
one EP8 forward, unit 8f + r is rank r's input. `bank_routes` realises a unit's counts for one layer
as a (4096, 6) table of distinct expert ids per token, so the benchmark's exact reference dispatch
applies unchanged; `placements` map logical experts to physical expert ids (rank = physical // 32
in DeepEP's expert-to-rank rule), so a placement is a permutation of expert ids.

Routing names: bank_f<forward>_l<layer>_<placement>, placement in {vanilla, greedy, random}.
This file is shared by the subset builder (local) and the benchmark (snapshot backend/tests/).
"""
import re
import numpy as np

NAME = re.compile(r'^bank_f(\d+)_l(\d+)_(vanilla|greedy|random)$')
EXPERTS_PER_RANK = 32  # V4 Flash at EP8: 256 experts on 8 ranks


def parse_bank_name(name):
    m = NAME.match(name)
    return (int(m.group(1)), int(m.group(2)), m.group(3)) if m else None


def bank_routes(counts, n, k, seed):
    """Distinct expert ids per token with exact per-expert counts (sum of counts must be n*k, no count
    above n). Construction: the copies of every expert are laid out contiguously, in a random expert
    order, into a (k, n) array that is then transposed; a run of at most n copies never meets the same
    token twice, so every token's k experts are distinct. Rows are then shuffled."""
    counts = np.asarray(counts, dtype=np.int64); e = counts.size
    deficit = n * k - int(counts.sum())  # bank units with tokens that route to fewer than k experts
    assert 0 <= deficit <= n and counts.max() <= n, (int(counts.sum()), n * k, int(counts.max()))
    full = np.append(counts, deficit)  # virtual expert e = "no expert" (-1 in DeepEP's topk_idx)
    rng = np.random.default_rng(seed)
    order = rng.permutation(e + 1)
    deck = np.repeat(order, full[order])
    idx = deck.reshape(k, n).T.copy()
    idx = idx[rng.permutation(n)]
    assert np.all(np.diff(np.sort(idx, axis=1), axis=1) != 0)
    assert np.array_equal(np.bincount(idx.ravel(), minlength=e + 1), full)
    idx[idx == e] = -1
    return idx


def greedy_placement(load, experts_per_rank=EXPERTS_PER_RANK):
    """Balanced partition without replicas: experts sorted by training load, each placed on the
    least-loaded rank that still has a free slot. Returns perm[logical] = physical id."""
    load = np.asarray(load, dtype=np.float64); e = load.size; ranks = e // experts_per_rank
    order = np.argsort(-load, kind='stable')
    rank_load = np.zeros(ranks); rank_fill = np.zeros(ranks, dtype=np.int64)
    perm = np.empty(e, dtype=np.int64)
    for x in order:
        cands = np.nonzero(rank_fill < experts_per_rank)[0]
        r = cands[np.argmin(rank_load[cands])]
        perm[x] = r * experts_per_rank + rank_fill[r]; rank_fill[r] += 1; rank_load[r] += load[x]
    assert np.array_equal(np.sort(perm), np.arange(e))
    return perm


def random_placement(e, seed):
    return np.random.default_rng(seed).permutation(e)


def route_matrix(idx, ranks, experts_per_rank=EXPERTS_PER_RANK):
    """Per destination rank: number of this rank's tokens with at least one expert there."""
    dest = np.where(idx >= 0, idx // experts_per_rank, -1)
    return np.array([(dest == d).any(axis=1).sum() for d in range(ranks)], dtype=np.int64)


def nic_rows(idx, ranks, rank, ranks_per_node=4, experts_per_rank=EXPERTS_PER_RANK):
    """Tokens of this rank with at least one expert on the other node: one NIC row each under the
    hybrid path (dispatch FP8 row out, BF16 reduced row back)."""
    dest = np.where(idx >= 0, idx // experts_per_rank, -1)
    other = (dest >= 0) & ((dest // ranks_per_node) != (rank // ranks_per_node))
    return int(other.any(axis=1).sum())


def traffic_stats(matrix, nic, ranks_per_node=4):
    """matrix[s][d] = tokens of source s with an expert on destination d (rows landing on d);
    nic[s] = NIC rows of source s. Per rail pair (s, s + 4) the wire carries max(nic[s], nic[s+4])."""
    m = np.asarray(matrix); nic = np.asarray(nic); ranks = m.shape[0]
    dest_rows = m.sum(axis=0)
    pairs = [max(int(nic[s]), int(nic[s + ranks_per_node])) for s in range(ranks_per_node)]
    ratio = lambda v: round(float(np.max(v) / np.mean(v)), 4) if np.mean(v) > 0 else 0.0
    return dict(dest_rows=dest_rows.tolist(), dest_rows_max_over_mean=ratio(dest_rows),
                nic_rows=nic.tolist(), nic_rows_max_over_mean=ratio(nic),
                pair_rows=pairs, pair_rows_max_over_mean=ratio(pairs))
