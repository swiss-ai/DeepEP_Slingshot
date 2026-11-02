"""Adapt private trace generation to packed PUTs; never edit ordinary sources.

113 measures submission of one packed batch, not wire transfer.
114 associates notification submission with old/new remote tails.
115 records a receiver-observed available range; several submissions may have
arrived before this observation. Cross-rank time needs calibration bounds.
"""

def patched_generator(text):
    anchor="    source=source[:source.index(\"    p=headers/'cxi_primitives.cuh'\")]\n"
    assert text.count(anchor)==1
    text=text.replace(anchor,anchor+'''    # Both the search and replacement strings in the reused trace generator
    # must preserve the compile-time guard around the original per-row PUT.
    source=source.replace(
        'if (stored_dst_slot_idx >= 0 and stored_dst_scaleout_rank_idx != scaleout_rank_idx)',
        'if (!CXI_EP_PACK_ROWS and stored_dst_slot_idx >= 0 and stored_dst_scaleout_rank_idx != scaleout_rank_idx)')
''')
    anchor="    scope['prepare'](ep,None)\n"
    assert text.count(anchor)==1
    addition=r'''    packed=ep/'deep_ep/include/deep_ep/impls/hybrid_dispatch.cuh'
    edit(packed,'                    if (lane_idx != scaleout_rank_idx && pending > 0) {',
         '                    if (lane_idx != scaleout_rank_idx && pending > 0) {\n'
         '                        ep_trace::Scope trace_packed_put(113,\n'
         '                            (uint64_t(channel_idx) << 32) | uint32_t(lane_idx),\n'
         '                            (uint64_t(stored_old_scaleout_tail) << 32) | uint32_t(pending));')
    edit(packed,'                gin.red_add_rel<ncclTeamTagRail>(ptr, signaled_tail - old_signaled_tail, lane_idx);',
         '                gin.red_add_rel<ncclTeamTagRail>(ptr, signaled_tail - old_signaled_tail, lane_idx);\n'
         '                ep_trace::finish(114,trace_signal.start,\n'
         '                    uint64_t(channel_idx) | (uint64_t(lane_idx) << 16) | (uint64_t(finish_flag) << 32),\n'
         '                    (uint64_t(stored_old_scaleout_tail) << 32) | uint32_t(stored_scaleout_tail));')
    edit(packed,'            ep_trace::finish(105,trace_arrival,channel_idx,recv_scaleout_rank_idx);',
         '            ep_trace::finish(105,trace_arrival,channel_idx,recv_scaleout_rank_idx);\n'
         '            const auto trace_consumed_tail = ptx::exchange(stored_scaleout_old_tail_idx, recv_scaleout_rank_idx);\n'
         '            const auto trace_available_tail = ptx::exchange(stored_scaleout_tail_idx, recv_scaleout_rank_idx);\n'
         '            ep_trace::finish(115,ep_trace::begin(lane_idx==0),\n'
         '                (uint64_t(channel_idx) << 32) | uint32_t(recv_scaleout_rank_idx),\n'
         '                (uint64_t(trace_consumed_tail) << 32) | uint32_t(trace_available_tail));')
'''
    text=text.replace(anchor,anchor+addition)
    # These scopes are also needed for the native-fence, zero-marker transport.
    text += r'''
    p=d/'cxi_primitives.cuh'
    edit(p,'  if(!c.tx_unpublished)return;',
         '  if(!c.tx_unpublished)return;\n  ep_trace::Scope trace_publish(209,(uint64_t)&c,c.tx_unpublished);')
    edit(p,'  if(!w)return true;',
         '  if(!w)return true;\n  ep_trace::Scope trace_delivery(210,(uint64_t)&c,c.pending_peer);')
    edit(p,'  uint64_t words[8];cxi_build_fence_command(words);',
         '  ep_trace::Scope trace_hw_fence(211,(uint64_t)&c,c.posted);\n  uint64_t words[8];cxi_build_fence_command(words);')
    edit(p,'  uint64_t words[8]{};auto* st=(c_cstate_cmd*)words;',
         '  ep_trace::Scope trace_cstate(212,(uint64_t)&c,peer);\n  uint64_t words[8]{};auto* st=(c_cstate_cmd*)words;')
    edit(p,'  uint64_t words[8]{};auto* hdr=(c_idc_hdr*)words;auto* amo=(c_small_amo_payload*)(words+2);',
         '  ep_trace::Scope trace_atomic(213,(uint64_t)&c,amount);\n  uint64_t words[8]{};auto* hdr=(c_idc_hdr*)words;auto* amo=(c_small_amo_payload*)(words+2);')
    edit(p,'  const auto trace_capacity=ep_trace::begin();',
         '  uint32_t trace_rp32=0;\n  const auto trace_capacity=ep_trace::begin();')
    edit(p,'    uint32_t rp32=(status&65535)*2;',
         '    uint32_t rp32=(status&65535)*2;\n    trace_rp32=rp32;')
    edit(p,'  ep_trace::finish(202,trace_capacity,(uint64_t)&c,c.tx_wp32);',
         '  ep_trace::finish(202,trace_capacity,(uint64_t)&c,c.tx_wp32);\n'
         '  ep_trace::finish(214,ep_trace::begin(),(uint64_t)&c,(uint64_t(trace_rp32)<<32)|uint32_t(c.tx_wp32));')
'''
    compile(text,'packed_trace_generator','exec')
    return text

EVENTS={113:'packed_payload_submission',114:'tail_notification_submission',
        115:'receiver_tail_observation',209:'TX_publication',
        210:'delivery_marker_enqueue',211:'NIC_fence_enqueue',
        212:'CSTATE_submission',213:'atomic_notification_submission',
        214:'TX_admission_cursor_observation'}
