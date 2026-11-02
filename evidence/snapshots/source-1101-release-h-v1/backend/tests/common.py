import os
import json
import math
import torch
import torch.distributed as dist

def record(path, obj):
    if os.getenv('CXI_LOCAL_RESULTS') == '1':
        import result_spool
        return result_spool.record(path, obj)
    with path.open('a') as f:
        f.write(json.dumps(obj) + '\n')


def bind_cpu(local_rank):
    import pynvml
    pynvml.nvmlInit()
    visible = os.getenv('CUDA_VISIBLE_DEVICES', '0,1,2,3').split(',')[local_rank]
    h = (pynvml.nvmlDeviceGetHandleByIndex(int(visible)) if visible.isdigit()
         else pynvml.nvmlDeviceGetHandleByUUID(visible))
    words = pynvml.nvmlDeviceGetCpuAffinity(h, (os.cpu_count() + 63) // 64)
    near = {i for i in range(os.cpu_count()) if words[i // 64] & (1 << (i % 64))}
    selected = near & os.sched_getaffinity(0)
    assert selected
    os.sched_setaffinity(0, selected)
    pynvml.nvmlShutdown()
    return sorted(selected)


def equal(a, b, label):
    if a.dtype == torch.float8_e4m3fn:
        a, b = a.view(torch.uint8), b.view(torch.uint8)
    assert a.shape == b.shape and torch.equal(a, b), f'{label}: {a.shape} vs {b.shape}'


def reference_dispatch(x, idx, weights, experts, source_stride=None):
    """Independent variable-size NCCL all-to-all, source-rank/token ordered."""
    rank, world = dist.get_rank(), dist.get_world_size()
    n = idx.shape[0]
    source_stride = n if source_stride is None else source_stride
    if source_stride < n:
        raise ValueError('Source ID stride cannot be smaller than the input token count')
    local_e = experts // world
    selections = [((idx // local_e) == r).any(1).nonzero().flatten() for r in range(world)]
    send_sizes = torch.tensor([s.numel() for s in selections], dtype=torch.int64, device='cuda')
    recv_sizes = torch.empty_like(send_sizes)
    dist.all_to_all_single(recv_sizes, send_sizes)
    sends, recvs = send_sizes.tolist(), recv_sizes.tolist()
    selected = torch.cat(selections)
    def exchange(t):
        src = t[selected].contiguous()
        dst = torch.empty((sum(recvs), *src.shape[1:]), dtype=src.dtype, device='cuda')
        # NCCL byte transport avoids FP8 type support/version differences.
        # Explicit row width also handles zero received/sent rows. reshape(0,-1)
        # is ambiguous and would fail the reference before testing empty buckets.
        width = math.prod(src.shape[1:])
        dist.all_to_all_single(dst.reshape(dst.shape[0], width).view(torch.uint8),
                               src.reshape(src.shape[0], width).view(torch.uint8), recvs, sends)
        return dst
    rx = tuple(exchange(t) for t in x) if isinstance(x, tuple) else exchange(x)
    ri = exchange(idx)
    rw = exchange(weights)
    src = exchange(torch.arange(n, device='cuda', dtype=torch.int64) + rank * source_stride)
    ri = torch.where(ri // local_e == rank, ri % local_e, -1)
    return rx, ri, rw, src, recvs

