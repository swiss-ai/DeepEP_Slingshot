"""Exact received-row skew, with two distinct destination ranks per token.

This synthetic calibration is intentionally separate from router replay. Half of
the K experts reside on each destination. Total assignments AND transmitted rows
stay fixed when skew changes; random expert logits would not ensure this.
"""
import numpy as np

ROUTING_CHOICES = ['uniform', 'mixed', 'local', 'remote', 'skew1.2', 'skew1.6', 'skew2', 'skew4', 'hot_rank']


def routes(n, ep, experts, topk, skew, seed, locality='mixed'):
    assert topk % 2 == 0 and experts % ep == 0
    if not 1 <= skew <= ep / 2:
        raise ValueError('Two distinct destination ranks per token require 1 <= skew <= EP/2')
    total = n * ep
    degrees = np.full(ep, (2 * total - round(2 * n * skew)) // (ep - 1), dtype=np.int64)
    degrees[0] = round(2 * n * skew)
    degrees[1:1 + 2 * total - int(degrees.sum())] += 1
    assert degrees.sum() == 2 * total and degrees.max() <= total
    deck = np.repeat(np.arange(ep), degrees)
    pairs = np.stack([deck[:total], deck[total:]], axis=1)
    assert np.all(pairs[:, 0] != pairs[:, 1])
    rng = np.random.default_rng(seed)
    pairs = pairs[rng.permutation(total)]
    # At balanced EP8, additionally isolate local-only and remote-only traffic.
    if locality != 'mixed':
        assert ep == 8 and skew == 1
        src = np.arange(total) // n
        offset = (np.arange(total) % 4)
        node = src // 4 if locality == 'local' else 1 - src // 4
        pairs = np.stack([node * 4 + offset, node * 4 + (offset + 1) % 4], axis=1)
    local_e = experts // ep
    offsets = (np.arange(total)[:, None] + np.arange(topk // 2)[None, :]) % local_e
    idx = np.concatenate([pairs[:, j:j+1] * local_e + offsets for j in range(2)], axis=1)
    assert np.all(np.diff(np.sort(idx, axis=1), axis=1) != 0)
    matrix = np.zeros((ep, ep), dtype=np.int64)
    for src in range(ep):
        matrix[src] = np.bincount(pairs[src*n:(src+1)*n].ravel(), minlength=ep)
    received = matrix.sum(axis=0)
    assert matrix.sum() == total * 2
    assert abs(received.max() / received.mean() - skew) <= 1 / n
    return idx, matrix


def nic_routes(n, ep, experts, topk, skew, seed, locality='nic_skew'):
    """Vary NIC-source max/mean; fix total remote rows, GPU rows and NVLink rows.

    Each node sends 2.5*N unique remote tokens, mean .625*N per source GPU.
    The hot local GPU is index zero on both nodes. Whole four-token groups
    ensure every destination GPU receives exactly 2*N rows at all skew levels.
    """
    assert ep == 8 and n % 16 == 0 and topk % 2 == 0
    total_quads = 5 * n // 8
    hot = round((5*n/8) * skew / 4)
    others = (total_quads-hot)//3
    quads = np.array([hot,others,others,others])
    quads[1:1+total_quads-int(quads.sum())] += 1
    assert quads.sum()==total_quads and quads.max() <= n//4
    rng=np.random.default_rng(seed)
    pairs=np.empty((ep*n,2),dtype=np.int64)
    for src in range(ep):
        remote=np.zeros(n//4,dtype=bool)
        remote[rng.permutation(n//4)[:quads[src%4]]] = True
        remote=np.repeat(remote,4)
        node=np.where(remote,1-src//4,src//4)
        offset=np.arange(n)%4
        pairs[src*n:(src+1)*n,0]=node*4+offset
        pairs[src*n:(src+1)*n,1]=node*4+(offset+1)%4
    local_e=experts//ep
    offsets=(np.arange(n*ep)[:,None]+np.arange(topk//2)[None,:])%local_e
    idx=np.concatenate([pairs[:,j:j+1]*local_e+offsets for j in range(2)],axis=1)
    matrix=np.array([np.bincount(pairs[s*n:(s+1)*n].ravel(),minlength=ep) for s in range(ep)])
    assert np.all(matrix.sum(0)==2*n)
    nv=np.array([sum(matrix[s,d] for s in range(ep) if s%4!=d%4) for d in range(ep)])
    assert np.all(nv==3*n//2)
    assert abs(quads.max()/quads.mean()-skew) <= 4/n
    return idx,matrix
