"""Deterministic real SGLang expert-kernel smoke, with a small FFN width.

Communication uses the requested full hidden width and expert count. The FFN
has width 128 so this is an integration check, never a model GEMM/TTFT result.
Sparse diagonal weights give an independent analytic numerical reference.
"""
import torch


def expert_factor(ids):
    return torch.pow(2.0, -((ids % 4) + 1).float())


def make_quant_info(local_experts, rank, hidden, dtype):
    from sglang.srt.layers.moe.moe_runner.deep_gemm import DeepGemmMoeQuantInfo
    intermediate = 128
    weight_dtype = torch.float8_e4m3fn if dtype == 'fp8' else torch.bfloat16
    # Construct in BF16 because FP8 indexed writes are not uniformly supported.
    w13 = torch.zeros(local_experts, 2 * intermediate, hidden, device='cuda', dtype=torch.bfloat16)
    w2 = torch.zeros(local_experts, hidden, intermediate, device='cuda', dtype=torch.bfloat16)
    diagonal = torch.arange(intermediate, device='cuda')
    w13[:, diagonal, diagonal] = 1
    w13[:, diagonal + intermediate, diagonal] = 1
    ids = torch.arange(local_experts, device='cuda') + rank * local_experts
    w2[:, diagonal, diagonal] = expert_factor(ids)[:, None].bfloat16()
    kwargs = dict(w13_weight=w13.to(weight_dtype), w2_weight=w2.to(weight_dtype), use_fp8=dtype == 'fp8')
    if dtype == 'fp8':
        kwargs.update(w13_scale=torch.ones(local_experts, 2, hidden // 128, device='cuda'),
                      w2_scale=torch.ones(local_experts, hidden // 128, 1, device='cuda'),
                      block_shape=[128, 128])
    return DeepGemmMoeQuantInfo(**kwargs)


def analytic_base(x, dtype):
    from sglang.srt.layers.moe.token_dispatcher.deepep import sglang_per_token_group_quant_fp8
    values = x[:, :128].float()
    activation = (torch.nn.functional.silu(values) * values).bfloat16()
    if dtype == 'fp8':
        quantized, scales = sglang_per_token_group_quant_fp8(
            activation, 128, column_major_scales=False, scale_tma_aligned=False, scale_ue8m0=False)
        activation = (quantized.float() * scales).bfloat16()
    base = torch.zeros_like(x)
    base[:, :128] = activation
    return base
