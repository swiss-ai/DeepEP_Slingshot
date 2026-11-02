import ctypes
import datetime
import json
import os
from pathlib import Path
import traceback

import torch
import torch.distributed as dist
from common import bind_cpu

out = Path(os.environ['CASE_OUT'])
out.mkdir(parents=True, exist_ok=True)
rank = int(os.environ['RANK'])
local = int(os.environ['LOCAL_RANK'])
record = {'rank': rank, 'cpu_affinity': bind_cpu(local), 'stage': 'starting',
          'gin_type': os.getenv('NCCL_GIN_TYPE'), 'plugin': os.getenv('NCCL_GIN_PLUGIN'), 'cases': []}
def save():
    (out / f'rank{rank}.json').write_text(json.dumps(record, indent=2) + '\n')
try:
    torch.cuda.set_device(local)
    import deep_ep
    record.update(stage='process_group_init', deep_ep=deep_ep.__file__)
    save()
    dist.init_process_group('nccl', device_id=torch.device('cuda', local),
                            timeout=datetime.timedelta(seconds=90))
    from deep_ep.utils.comm import get_nccl_comm_handle
    comm = get_nccl_comm_handle(dist.group.WORLD).get()
    lib = ctypes.CDLL(os.environ['SMOKE_SO'])
    kind = os.getenv('CXI_TEST_KIND', 'smoke')
    if kind == 'smoke':
        function = lib.gin_smoke
        dimensions = os.getenv('CXI_SMOKE_CONTEXTS', '1,4')
        rounds = int(os.getenv('CXI_SMOKE_ROUNDS', '14'))
        dimension_name = 'contexts'
    elif kind == 'producer':
        function = lib.gin_producer_stress
        dimensions = os.getenv('CXI_PRODUCER_BLOCKS', '1,2,8')
        rounds = int(os.getenv('CXI_PRODUCER_ROUNDS', '128'))
        dimension_name = 'blocks'
    elif kind == 'bad_offset':
        function = lib.gin_bad_offset
        dimensions, rounds, dimension_name = '1', 1, 'negative'
    elif kind == 'bounds':
        function = lib.gin_bounds
        dimensions, rounds, dimension_name = '1', 1, 'bounds'
    else:
        raise ValueError('Unknown GIN test kind: ' + kind)
    function.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int, ctypes.c_int]
    function.restype = ctypes.c_int
    record.update(kind=kind, rounds_requested=rounds)
    held = ctypes.c_void_p()
    if os.getenv('CXI_LIFECYCLE_HOLD_WINDOW') == '1':
        assert kind == 'smoke'
        lib.gin_hold_window.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
        lib.gin_hold_window.restype = ctypes.c_int
        lib.gin_release_window.argtypes = [ctypes.c_void_p]
        lib.gin_release_window.restype = ctypes.c_int
        assert lib.gin_hold_window(ctypes.c_void_p(comm), ctypes.byref(held)) == 0 and held.value
        record['held_window'] = True
    seen = set()
    for cycle, dimension in enumerate(map(int, dimensions.split(','))):
        record.update(stage='gin_kernel', **{dimension_name: dimension})
        save()
        prefix = f'cycle{cycle}-' if dimension in seen else ''
        seen.add(dimension)
        path = out / f'{prefix}{dimension_name}{dimension}-rank{rank}.jsonl'
        rc = function(ctypes.c_void_p(comm), str(path).encode(), dimension, rounds)
        record['cases'].append({dimension_name: dimension, 'cycle': cycle,
                                'evidence': path.name, 'returncode': rc})
        save()
        if rc:
            raise RuntimeError(f'GIN {kind} {dimension_name}={dimension}: rc={rc}')
        dist.barrier()
    if held.value:
        assert lib.gin_release_window(held) == 0
        record['held_window_released'] = True
    (out / f'libraries-rank{rank}.txt').write_text(Path('/proc/self/maps').read_text())
    record['stage'] = 'complete'
    save()
    dist.destroy_process_group()
except BaseException:
    record['error'] = traceback.format_exc()
    save()
    raise
