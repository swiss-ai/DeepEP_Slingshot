"""NIC-domain counter windows, separate from CUDA timing and GPU traces."""
import json
import math
import time
from pathlib import Path


def snapshot(sysfs=Path('/sys/class/cxi')):
    catalog=json.loads(Path(__file__).with_name('nic-counter-catalog.json').read_text())
    start=time.monotonic_ns();values={}
    nics=sorted(sysfs.glob('cxi[0-9]*'))
    assert {p.name for p in nics}=={'cxi0','cxi1','cxi2','cxi3'}
    for nic in nics:
        for counter in catalog['counters']:
            value,stamp=(nic/'device/telemetry'/counter).read_text().strip().split('@')
            values[nic.name+'/'+counter]=dict(value=int(value),timestamp=float(stamp))
    return dict(values=values,read_start_monotonic_ns=start,read_end_monotonic_ns=time.monotonic_ns(),
                catalog_source_sha256=catalog['source_sha256'])


def deltas(before,after,iterations):
    assert iterations>0 and before['catalog_source_sha256']==after['catalog_source_sha256']
    assert before['values'].keys()==after['values'].keys()
    result={}
    for name,b in before['values'].items():
        a=after['values'][name];delta=a['value']-b['value'];seconds=a['timestamp']-b['timestamp']
        assert delta>=0 and seconds>0 and math.isfinite(seconds),(name,delta,seconds)
        result[name]=dict(raw_delta=delta,counter_seconds=seconds,raw_per_second=delta/seconds,
                          raw_per_iteration=delta/iterations)
    return result


def record(path,case,before,after,iterations,wall_seconds):
    row=dict(case,before=before,after=after,deltas=deltas(before,after,iterations),
        iterations=iterations,wall_seconds=wall_seconds,
        scope='Separate isolated operation window including synchronization/control traffic; NIC counts/cycles are not GPU durations and overlapping categories must not be added')
    with Path(path).open('a') as file:file.write(json.dumps(row)+'\n')


def validate(directory,env):
    catalog=json.loads(Path(__file__).with_name('nic-counter-catalog.json').read_text())
    keys={nic+'/'+counter for nic in ['cxi0','cxi1','cxi2','cxi3'] for counter in catalog['counters']}
    expected={(m,d,r,operation) for m in env['CXI_EP_MODELS'].split()
              for d in env['CXI_EP_DTYPES'].split() for r in env['CXI_EP_ROUTING'].split()
              for operation in ['dispatch_fresh','dispatch_cached','combine','cycle']}
    for node in range(2):
        rows=[json.loads(line) for line in (Path(directory)/('nic-extra-node%d.jsonl'%node)).read_text().splitlines()]
        assert len(rows)==len(expected)
        assert {(r['model'],r['dispatch_dtype'],r['routing'],r['operation']) for r in rows}==expected
        for row in rows:
            assert row['rank']==node*4 and row['ep']==8 and row['gin_type']=='6'
            assert row['tokens_per_gpu']==4096 and row['seed']==int(env['CXI_EP_SEEDS'].split()[0])
            assert row['iterations']==int(env['CXI_EP_NIC_ITERS']) and row['wall_seconds']>0
            assert set(row['before']['values'])==keys and set(row['after']['values'])==keys
            assert row['before']['catalog_source_sha256']==catalog['source_sha256']
            assert row['deltas']==deltas(row['before'],row['after'],row['iterations'])
    return len(expected)*2
