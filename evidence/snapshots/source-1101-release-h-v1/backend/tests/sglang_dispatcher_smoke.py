"""Exercise the actual SGLang dispatcher with a deterministic expert transform.

This is a communication/adapter test, not a model-serving or GEMM benchmark.
An optional real SGLang expert-kernel path uses a reduced FFN width and an
analytic reference; the default expert transform remains a simple operation.
The isolated overlay must already be enabled; no module or class is mocked.
"""
import datetime
import hashlib
import json
import os
from pathlib import Path
import time
import traceback

import torch
import torch.distributed as dist
from common import bind_cpu, equal, reference_dispatch
from source_metadata import source_metadata

rank = int(os.environ['RANK'])
local = int(os.environ['LOCAL_RANK'])
out = Path(os.environ['CASE_OUT'])
out.mkdir(parents=True, exist_ok=True)
record = {'rank': rank, 'stage': 'starting', 'cpu_affinity': bind_cpu(local), 'cases': [],
          'gin_type': os.getenv('NCCL_GIN_TYPE'), 'plugin': os.getenv('NCCL_GIN_PLUGIN'),
          'local_results': os.getenv('CXI_LOCAL_RESULTS') == '1',
          'local_jit': os.getenv('CXI_LOCAL_JIT') == '1',
          'case_out': str(out), 'deepgemm_cache': os.getenv('SGLANG_DG_CACHE_DIR')}


def save():
    (out / f'rank{rank}.json').write_text(json.dumps(record, indent=2) + '\n')


def tensor_sha(tensor):
    raw = tensor.detach().contiguous().view(torch.uint8).cpu().numpy().tobytes()
    return hashlib.sha256(raw).hexdigest()


def dequantize(x, scales):
    if scales is None:
        return x
    n, h = x.shape
    # GH200 uses FP32 group scales. Reject another layout until it is qualified.
    if scales.dtype != torch.float32 or scales.shape != (n, h // 128):
        raise RuntimeError(f'Unqualified FP8 scale layout: {scales.dtype} {scales.shape}')
    return (x.float().reshape(n, h // 128, 128) * scales[:, :, None]).reshape(n, h).bfloat16()


try:
    torch.cuda.set_device(local)
    # Exercise the private runtime guard against actually loaded OFI/GIN plugins
    # when requested, matching applications that initialize distributed first.
    if os.getenv('CXI_SGLANG_IMPORT_AFTER_INIT') == '1':
        record.update(stage='init_group_before_import', import_after_group_init=True)
        save()
        dist.init_process_group('nccl', device_id=torch.device('cuda', local),
                                timeout=datetime.timedelta(seconds=120))
    from sglang.srt.server_args import ServerArgs, set_global_server_args_for_scheduler
    from sglang.srt.layers.moe.utils import DeepEPMode, initialize_moe_config
    from sglang.srt.layers.dp_attention import set_is_extend_in_batch
    from sglang.srt.layers.moe.topk import StandardTopKOutput
    from sglang.srt.layers.moe.token_dispatcher.deepep import (
        DeepEPDispatcher, DeepEPNormalCombineInput, sglang_per_token_group_quant_fp8,
    )
    from sglang.srt.layers.moe.token_dispatcher.deepep_v2_cxi import DeepEPV2CXINormal
    from sglang.srt.layers import deep_gemm_wrapper
    import sglang
    import deep_ep

    proxy_control = os.getenv('CXI_TRANSPORT', 'direct') == 'proxy'
    expected_type = '2' if proxy_control else '6'
    if (os.getenv('SGLANG_CXI_DEEPEP_V2') != '1' or os.getenv('NCCL_GIN_TYPE') != expected_type
            or (os.getenv('SGLANG_CXI_DEEPEP_V2_ALLOW_PROXY_CONTROL') == '1') != proxy_control):
        raise RuntimeError('Explicit matching CXI direct/proxy opt-in is required')
    record.update(transport='proxy_ofi_cxi' if proxy_control else 'direct_cxi',
                  proxy_control=proxy_control)
    if not deep_gemm_wrapper.ENABLE_JIT_DEEPGEMM or deep_gemm_wrapper.DEEPGEMM_SCALE_UE8M0:
        raise RuntimeError('Initial adapter test requires GH200 DeepGEMM with FP32 group scales')
    record.update(sglang=sglang.__file__, deep_ep=deep_ep.__file__, stage='init_group',
                  overlay_manifest=json.loads((Path(sglang.__file__).parent.parent / 'cxi-sglang-manifest.json').read_text()),
                  test_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                  hostname=os.uname().nodename, job=os.getenv('SLURM_JOB_ID'),
                  source=source_metadata(Path(deep_ep.__file__).parent.parent,
                      Path(os.environ['DEEPEP_WORK']) / 'source-manifest.json', 'DeepEP'),
                  native_extension_sha256=hashlib.sha256(Path(deep_ep._C.__file__).read_bytes()).hexdigest(),
                  nccl_sha256=hashlib.sha256((Path(os.environ['EP_NCCL_ROOT_DIR']) / 'lib/libnccl.so.2.32.3').read_bytes()).hexdigest())
    save()
    if not dist.is_initialized():
        dist.init_process_group('nccl', device_id=torch.device('cuda', local),
                               timeout=datetime.timedelta(seconds=120))
    if dist.get_world_size() != 8:
        raise RuntimeError('Expected EP8')
    set_is_extend_in_batch(True)
    model = os.getenv('CXI_SGLANG_MODEL', 'toy')
    geometries = {'toy': (2048, 64, 4), 'v4flash': (4096, 256, 6),
                  'qwen3': (4096, 128, 8), 'minimax': (3072, 256, 8)}
    hidden, experts, topk = geometries[model]
    record.update(model_geometry=model, hidden=hidden, experts=experts, topk=topk)
    iterations = int(os.getenv('CXI_SGLANG_ROUNDS', '3'))
    warmup = int(os.getenv('CXI_SGLANG_WARMUP', '0'))
    if iterations < 1 or warmup < 0:
        raise ValueError('Invalid SGLang iteration counts')
    record.update(warmup_iterations=warmup, timed_iterations=iterations,
                  exact_dispatch_reference=True,
                  deepgemm_precompile=os.getenv('SGLANG_JIT_DEEPGEMM_PRECOMPILE'),
                  routing='deterministic cyclic balanced synthetic routes',
                  timing_scope='synchronized dispatcher wrappers; dispatch includes SGLang quantization; no expert work in dispatch/combine timers')
    use_gemm = os.getenv('CXI_SGLANG_GEMM') == '1'
    use_permute = os.getenv('CXI_SGLANG_PERMUTE') == '1' or use_gemm
    record['actual_sglang_scatter_gather'] = use_permute
    record['actual_sglang_expert_kernels'] = use_gemm
    if use_permute:
        from sglang.srt.layers.moe.moe_runner.base import MoeRunnerConfig
        from sglang.srt.layers.moe.moe_runner.deep_gemm import (
            DeepGemmRunnerOutput, pre_permute_deepep_normal_to_deep_gemm,
            post_permute_deep_gemm_to_deepep_normal,
        )
        runner_config = MoeRunnerConfig(num_experts=experts, num_local_experts=experts // 8,
                                       hidden_size=hidden, top_k=topk, activation='silu')
        if use_gemm:
            from sglang.srt.layers.moe.moe_runner.deep_gemm import DeepGemmRunnerCore
            from sglang_expert_smoke import make_quant_info, analytic_base, expert_factor
            runner_config.intermediate_size_per_partition = 128
            runner = DeepGemmRunnerCore(runner_config)
            record['expert_kernel_scope'] = 'real SGLang gated expert runner, FFN width 128; not model compute timing'
    for dtype in os.getenv('CXI_SGLANG_DTYPES', 'bf16,fp8').split(','):
        quant_info = make_quant_info(experts // 8, rank, hidden, dtype) if use_gemm else None
        # The image explicitly supports dummy ServerArgs without model downloads.
        args = ServerArgs(model_path='dummy', moe_a2a_backend='deepep',
                          moe_runner_backend='deep_gemm', deepep_mode='normal',
                          deepep_dispatcher_output_dtype=dtype)
        set_global_server_args_for_scheduler(args)
        initialize_moe_config(args)
        dispatcher = DeepEPDispatcher(
            group=dist.group.WORLD, router_topk=topk, num_experts=experts,
            num_local_experts=experts // 8, hidden_size=hidden,
            params_dtype=torch.bfloat16, deepep_mode=DeepEPMode.NORMAL,
            async_finish=False, permute_fusion=False,
        )
        if not isinstance(dispatcher._normal_dispatcher, DeepEPV2CXINormal):
            raise RuntimeError('SGLang did not select the actual v2 adapter')
        for tokens in map(int, os.getenv('CXI_SGLANG_TOKENS', '32,4096').split(',')):
            for step in range(warmup + iterations):
                record.update(stage='dispatcher', dtype=dtype, tokens=tokens, step=step)
                save()
                rows = torch.arange(tokens, device='cuda', dtype=torch.int64)[:, None]
                cols = torch.arange(hidden, device='cuda', dtype=torch.int64)[None, :]
                x = (((rows * 13 + cols * 7 + rank * 29 + step * 19) % 127 - 63) / 64).bfloat16()
                ids = (rows * 7 + rank * 13 + step * 17 + torch.arange(topk, device='cuda')[None, :] * 23) % experts
                weights = torch.arange(1, topk + 1, device='cuda', dtype=torch.float32)[None, :].expand(tokens, -1).contiguous()
                weights /= weights.sum(dim=1, keepdim=True)
                input_hashes = dict(input_sha256=tensor_sha(x), route_sha256=tensor_sha(ids),
                                    weights_sha256=tensor_sha(weights))
                expected_x = x
                reference_input = x
                if dtype == 'fp8':
                    quantized, scales = sglang_per_token_group_quant_fp8(
                        x, 128, column_major_scales=False, scale_tma_aligned=False, scale_ue8m0=False)
                    expected_x = dequantize(quantized, scales)
                    reference_input = (quantized, scales)
                # Independent NCCL all-to-all is outside the timed operation.
                # Check exact bytes/metadata, not just a tolerant final output.
                # DeepEP source IDs use the reserved per-rank token capacity,
                # which can exceed the current batch size (e.g. 32 vs 4096).
                source_stride = dispatcher._normal_dispatcher._capacity
                reference = reference_dispatch(reference_input, ids, weights, experts,
                                               source_stride=source_stride)
                expert_base = analytic_base(expected_x, dtype) if use_gemm else expected_x
                # Match expert output rounding on each destination rank before
                # the cross-rank combine. Unequal routing weights catch accidental
                # double weighting by the adapter.
                expected = torch.zeros_like(x, dtype=torch.float32)
                for owner in range(8):
                    mask = (ids // (experts // 8)) == owner
                    if use_permute:
                        partial = torch.zeros_like(x, dtype=torch.float32)
                        for slot in range(topk):
                            scale = expert_factor(ids[:, slot]) if use_gemm else (ids[:, slot] + 1).float() / experts
                            expert_value = (expert_base.float() * scale[:, None]).bfloat16()
                            partial += expert_value.float() * (weights[:, slot] * mask[:, slot])[:, None]
                        expected += partial.bfloat16().float()
                    else:
                        factor = (weights * (ids + 1).float() / experts * mask).sum(dim=1)
                        expected += (expected_x.float() * factor[:, None]).bfloat16().float()
                expected = expected.bfloat16()
                dist.barrier()
                torch.cuda.synchronize()
                dispatch_start = torch.cuda.Event(enable_timing=True)
                dispatch_end = torch.cuda.Event(enable_timing=True)
                start = time.perf_counter()
                dispatch_start.record()
                received = dispatcher.dispatch(x, StandardTopKOutput(weights, ids, None))
                dispatch_end.record()
                torch.cuda.synchronize()
                dispatch_ms = (time.perf_counter() - start) * 1000
                payload = dequantize(received.hidden_states, received.hidden_states_scale)
                received_tokens = payload.shape[0]
                adapter = dispatcher._normal_dispatcher
                actual_ep_config = dict(sms=adapter._sms, allocated_contexts=adapter._contexts,
                    used_qps=adapter._qps, capacity=adapter._capacity,
                    physical_domain=list(adapter._elastic.get_physical_domain_size()))
                handle = adapter.handle
                source_ids = handle.recv_src_metadata[:received_tokens, 0]
                order = torch.argsort(source_ids)
                if not torch.equal(source_ids[order], reference[3]):
                    record['source_id_mismatch'] = dict(stride=source_stride, tokens=tokens,
                        actual_head=source_ids[order][:16].cpu().tolist(),
                        actual_tail=source_ids[order][-16:].cpu().tolist(),
                        reference_head=reference[3][:16].cpu().tolist(),
                        reference_tail=reference[3][-16:].cpu().tolist())
                    save()
                equal(source_ids[order], reference[3], 'SGLang source IDs')
                equal(received.topk_ids[order], reference[1], 'SGLang expert IDs')
                expected_tensors = reference[0] if isinstance(reference[0], tuple) else (reference[0],)
                actual_tensors = ((received.hidden_states, received.hidden_states_scale)
                                  if dtype == 'fp8' else (received.hidden_states,))
                for actual, target in zip(actual_tensors, expected_tensors):
                    equal(actual[order], target, 'SGLang payload/scales')
                equal(received.topk_weights[order].masked_fill(reference[1] < 0, 0),
                      reference[2].masked_fill(reference[1] < 0, 0), 'SGLang routing weights')
                counts = torch.bincount(reference[1][reference[1] >= 0], minlength=experts // 8).tolist()
                if list(received.num_recv_tokens_per_expert) != [((v + 127) // 128) * 128 for v in counts]:
                    raise RuntimeError('SGLang padded expert counts differ from independent reference')
                local_ids = received.topk_ids
                valid = local_ids >= 0
                if bool((local_ids[valid] >= experts // 8).any()):
                    raise RuntimeError('Dispatcher returned nonlocal expert IDs')
                global_ids = local_ids + rank * (experts // 8)
                factor = (received.topk_weights * (global_ids + 1).float() / experts * valid).sum(dim=1)
                expert_output = (payload.float() * factor[:, None]).bfloat16()
                combine_input = DeepEPNormalCombineInput(expert_output, local_ids, received.topk_weights)
                if use_permute:
                    state = {}
                    # These are the image's real runner layout functions. The
                    # numerical expert transform is intentionally simple; this
                    # qualifies layout/weighting, not DeepGEMM performance.
                    packed = pre_permute_deepep_normal_to_deep_gemm(received, quant_info, runner_config, state)
                    if use_gemm:
                        runner_output = runner.run(packed, quant_info, state)
                    else:
                        values = dequantize(packed.hidden_states,
                                            packed.hidden_states_scale if dtype == 'fp8' else None)
                        factors = (packed.m_indices + rank * (experts // 8) + 1).float() / experts
                        transformed = (values.float() * factors[:, None]).bfloat16()
                        transformed[packed.m_indices < 0] = 0
                        runner_output = DeepGemmRunnerOutput(transformed)
                    combine_input = post_permute_deep_gemm_to_deepep_normal(
                        runner_output, quant_info, runner_config, state)
                torch.cuda.synchronize()
                # Cold expert JIT can finish at different times on different
                # ranks. Do not enter a short-timeout communication kernel until
                # every rank has completed expert work. Outside combine timer.
                dist.barrier()
                combine_start = torch.cuda.Event(enable_timing=True)
                combine_end = torch.cuda.Event(enable_timing=True)
                start = time.perf_counter()
                combine_start.record()
                combined = dispatcher.combine(combine_input)
                combine_end.record()
                torch.cuda.synchronize()
                combine_ms = (time.perf_counter() - start) * 1000
                error = (combined.float() - expected.float()).abs()
                torch.testing.assert_close(combined, expected, atol=0.008, rtol=0.02)
                record['cases'].append(dict(dtype=dtype, tokens=tokens, step=step,
                    warmup=step < warmup,
                    exact_dispatch_reference='PASS',
                    source_token_stride=source_stride,
                    actual_ep_config=actual_ep_config,
                    **input_hashes,
                    received_tokens=received_tokens, max_abs_error=error.max().item(),
                    dispatch_wrapper_ms=dispatch_ms, combine_wrapper_ms=combine_ms,
                    dispatch_cuda_us=dispatch_start.elapsed_time(dispatch_end) * 1000,
                    combine_cuda_us=combine_start.elapsed_time(combine_end) * 1000,
                    timing_scope='cold/debug diagnostic' if warmup < 10 or iterations < 30 else
                                 'unprofiled synchronized wrapper; warmup rows excluded from performance summary'))
                save()
        dispatcher._normal_dispatcher.close()
        dist.barrier()
    record.update(stage='complete', result='PASS')
    (out / f'libraries-rank{rank}.txt').write_text(Path('/proc/self/maps').read_text())
    save()
    dist.destroy_process_group()
except BaseException:
    record.update(stage='failed', error=traceback.format_exc())
    save()
    raise
