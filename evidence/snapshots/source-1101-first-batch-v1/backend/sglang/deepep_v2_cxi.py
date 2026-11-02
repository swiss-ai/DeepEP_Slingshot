"""Opt-in experimental normal-mode adapter for the pinned SGLang container.

This file is installed only into an isolated source overlay. Direct CXI GIN
must pass the lower-level gates first. It does not implement LL, AUTO, overlap,
EPLB recording, or a general replacement for every SGLang DeepEP backend.
"""
import logging
import os

import torch
from deep_ep import ElasticBuffer

from sglang.srt.eplb.expert_distribution import get_global_expert_distribution_recorder
from sglang.srt.layers import deep_gemm_wrapper
from sglang.srt.layers.moe.token_dispatcher.deepep import (
    _DeepEPDispatcherImplNormal,
    _deepep_precompile_tp_barrier,
)
from sglang.srt.layers.moe.utils import DeepEPMode

logger = logging.getLogger(__name__)


class DeepEPV2CXINormal(_DeepEPDispatcherImplNormal):
    # Sequential layers share communication storage, as in SGLang's v1 path.
    _buffers = {}

    def __init__(self, async_finish=False, **kwargs):
        if async_finish or kwargs['deepep_mode'] != DeepEPMode.NORMAL:
            raise NotImplementedError('Experimental CXI v2 adapter requires normal mode without async overlap')
        proxy_control = os.getenv('SGLANG_CXI_DEEPEP_V2_ALLOW_PROXY_CONTROL') == '1'
        expected_type = '2' if proxy_control else '6'
        if os.environ.get('NCCL_GIN_TYPE') != expected_type:
            raise RuntimeError('Experimental CXI adapter backend does not match explicit direct/proxy selection')
        self.transport = 'proxy_ofi_cxi' if proxy_control else 'direct_cxi'
        super().__init__(async_finish=False, **kwargs)
        self._elastic = None
        self._buffer_key = None
        self._capacity = int(os.getenv('SGLANG_CXI_DEEPEP_V2_MAX_TOKENS', '4096'))
        self._sms = int(os.getenv('SGLANG_CXI_DEEPEP_V2_SMS', '64'))
        self._contexts = int(os.getenv('SGLANG_CXI_DEEPEP_V2_CONTEXTS', '129'))
        if self._capacity < 4096 or self._sms <= 0 or self._sms % 2 or self._contexts < 1:
            raise ValueError('Invalid v2 capacity/SM/context configuration')
        if self.use_nvfp4:
            raise NotImplementedError('Initial GH200 adapter supports BF16 or FP8 only')

    def _get_buffer(self):
        if self._elastic is None:
            if self.group.size() != 8:
                raise ValueError('This qualification adapter requires one eight-rank group')
            key = (id(self.group), self.hidden_size, self._capacity, self._contexts)
            cached = self._buffers.get(key)
            if cached is not None:
                cached['references'] += 1
                self._elastic = cached['buffer']
                self._buffer_key = key
                self._qps = self._elastic.get_theoretical_num_qps(self._sms)
                return self._elastic
            self._elastic = ElasticBuffer(
                self.group,
                num_max_tokens_per_rank=self._capacity,
                hidden=self.hidden_size,
                allow_hybrid_mode=True,
                allow_multiple_reduction=True,
                prefer_overlap_with_compute=False,
                num_allocated_qps=self._contexts,
                num_cpu_timeout_secs=120,
                num_gpu_timeout_secs=60,
                explicitly_destroy=True,
            )
            if self._elastic.get_physical_domain_size() != (2, 4):
                self._elastic.destroy()
                self._elastic = None
                raise RuntimeError('Expected two physical RDMA domains and four local NVLink GPUs')
            self._buffers[key] = {'buffer': self._elastic, 'references': 1, 'owner': None}
            self._buffer_key = key
            self._qps = self._elastic.get_theoretical_num_qps(self._sms)
            logger.warning('Experimental DeepEP v2 CXI transport=%s: group=%d capacity=%d SMs=%d contexts=%d used_qps=%d',
                           self.transport, self.group.size(), self._capacity, self._sms, self._contexts, self._qps)
        return self._elastic

    def _dispatch_core(self, x, topk_ids, topk_weights, previous_event):
        if previous_event is not None:
            raise NotImplementedError('Async event translation has not been qualified')
        if self.handle is not None:
            raise RuntimeError('Previous dispatch must be combined before a fresh dispatch')
        tensor = x[0] if isinstance(x, tuple) else x
        if tensor.shape[0] > self._capacity:
            raise ValueError('Input exceeds the explicitly allocated token capacity')
        recorder = get_global_expert_distribution_recorder()
        if type(recorder).__name__ != '_ExpertDistributionRecorderNoop':
            raise NotImplementedError('EPLB recorder metadata translation is not yet qualified')
        buffer = self._get_buffer()
        state = self._buffers[self._buffer_key]
        if state['owner'] is not None:
            raise RuntimeError('Overlapping dispatches on shared v2 storage are not qualified')
        # Keep ownership on any failed transfer; recovering a possibly live
        # communication protocol requires restarting the failed process group.
        state['owner'] = self
        _deepep_precompile_tp_barrier()
        received, ids, weights, handle, event = buffer.dispatch(
            x=x,
            topk_idx=topk_ids,
            topk_weights=topk_weights,
            num_experts=self.num_experts,
            num_max_tokens_per_rank=self._capacity,
            expert_alignment=128 if deep_gemm_wrapper.ENABLE_JIT_DEEPGEMM else 1,
            num_sms=self._sms,
            num_qps=self._qps,
            do_handle_copy=True,
            do_cpu_sync=True,
            do_expand=False,
            async_with_compute_stream=False,
            use_tma_aligned_col_major_sf=bool(deep_gemm_wrapper.DEEPGEMM_SCALE_UE8M0),
        )
        self.handle = handle
        return received, ids, weights, handle.num_recv_tokens_per_expert_list, event

    def _combine_core(self, x, previous_event):
        if previous_event is not None or self.handle is None:
            raise RuntimeError('Expected the live handle from synchronous fresh dispatch')
        if x.dtype != torch.bfloat16:
            raise TypeError('Initial combine qualification requires BF16 expert outputs')
        _deepep_precompile_tp_barrier()
        # SGLang's normal expert runner already applies routing weights. Passing
        # those weights again here would change model semantics.
        combined, _, event = self._get_buffer().combine(
            x, self.handle, num_sms=self._sms, num_qps=self._qps,
            async_with_compute_stream=False,
        )
        self._buffers[self._buffer_key]['owner'] = None
        return combined, event

    def close(self):
        if self.handle is not None:
            raise RuntimeError('Cannot destroy the adapter with an uncombined dispatch')
        if self._elastic is not None:
            state = self._buffers[self._buffer_key]
            if state['owner'] is not None:
                raise RuntimeError('Cannot destroy shared storage during a live dispatch')
            state['references'] -= 1
            if not state['references']:
                state['buffer'].destroy()
                del self._buffers[self._buffer_key]
            self._elastic = None
            self._buffer_key = None
