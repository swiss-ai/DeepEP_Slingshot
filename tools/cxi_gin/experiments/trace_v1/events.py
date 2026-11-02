"""Stable trace schema. Durations are inclusive unless explicitly stated."""
EVENTS={
100:'dispatch.hybrid',101:'dispatch.initial_barrier',102:'dispatch.notify_counts',
103:'dispatch.scaleout_role',104:'dispatch.forward_role',105:'dispatch.arrival_tail_wait',
106:'dispatch.final_local_barrier',108:'dispatch.forward_token',109:'dispatch.nvlink_issue',
110:'dispatch.publish_tail',111:'dispatch.remote_token_put',112:'dispatch.pack_and_stage',
120:'dispatch.copy_epilogue',121:'dispatch.copy_dependency_wait',
200:'cxi.context_lock_wait',201:'cxi.emit_command',202:'cxi.command_consumption_wait',
203:'cxi.completion_flush',204:'cxi.payload_put',205:'cxi.signal_add',206:'cxi.gin_put',
}
SLOTS=8192
CAPACITY=512
WORDS=8
HEADER=8+SLOTS
BUFFER_WORDS=HEADER+SLOTS*CAPACITY*WORDS
