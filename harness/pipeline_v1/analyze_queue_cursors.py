"""Analyze sampled TX command consumption; this is not RDMA completion depth."""
import argparse,csv,gzip,json,re,statistics
from pathlib import Path


def pending_commands(size, write, read):
    assert size >= 12 and size % 2 == 0
    assert 8 <= write < size and write % 2 == 0
    assert read == 0 or 8 <= read < size
    assert read % 2 == 0
    if read == 0:
        read = 8
    return (write-read if write >= read else size-read+write-8)//2


def analyze(gate):
    finish=json.loads((gate/'FINISHED.json').read_text())
    assert finish['returncode']==0 and finish['qualification']['device_traces']=='PASS'
    sizes={}
    for node in range(2):
        text=(gate/'direct'/('node%d'%node)/'smoke.log').read_text()
        rows=re.findall(r'CXI_QUEUE gpu=(\d+) requested=\d+ tx_size32=(\d+)',text)
        for gpu in range(4):
            observed={int(size) for local,size in rows if int(local)==gpu}
            assert len(observed)==1, ('ambiguous or absent TX size',node,gpu,observed)
            sizes[node*4+gpu]=observed.pop()
    samples=[];summaries=[]
    for path in sorted((gate/'direct/ep/device-traces').glob('*-iteration*.json.gz')):
        with gzip.open(path,'rt') as file: capture=json.load(file)
        assert capture['correctness']=='PASS' and capture['stats']['overflow']==0
        rank=capture['rank'];size=sizes[rank];values=[]
        for event in capture['events']:
            if event['event']!=214:continue
            read=event['aux1']>>32;write=event['aux1']&0xffffffff
            pending=pending_commands(size,write,read);values.append(pending)
            samples.append(dict(rank=rank,operation=capture['operation'],iteration=capture['iteration'],
                context=event['aux0'],timestamp_ns=event['start_ns'],rp32=read,wp32=write,
                tx_size32=size,commands_before_enqueue=pending))
        assert values, ('missing cursor observations',path)
        capacity=(size-8)//2-1
        ordered=sorted(values)
        summaries.append(dict(rank=rank,operation=capture['operation'],iteration=capture['iteration'],
            samples=len(values),usable_padded_command_slots=capacity,
            median_commands=statistics.median(values),p95_commands=ordered[(95*(len(values)-1))//100],
            max_commands=max(values),fraction_at_least_80_percent=sum(v>=.8*capacity for v in values)/len(values)))
    assert summaries
    output=gate/'queue-cursor-analysis';output.mkdir(exist_ok=True)
    for name,rows in [('samples.csv',samples),('summary.csv',summaries)]:
        with (output/name).open('w') as file:
            writer=csv.DictWriter(file,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    (output/'README.md').write_text('The RP/WP sample is the successful admission read before writing the new command. '
        'It measures queued padded 64-byte commands not yet consumed by the NIC. Consumption does not mean '
        'remote delivery or completion. A low sampled depth does not prove a fast network or absence of '
        'an earlier capacity wait; consult event202 and completion events separately. Sizes come from '
        'the actual per-GPU queue inventory. Reserved status slots and the empty/full sentinel follow '
        'cxi_queue_credit.h. These are instrumented observations and may perturb scheduling.\n')
    return output


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('gate',type=Path)
    print(analyze(parser.parse_args().gate))
