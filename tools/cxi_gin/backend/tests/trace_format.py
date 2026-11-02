"""Reader dimensions are parsed from the actual device writer header."""
import re
from pathlib import Path
_HEADER=Path(__file__).with_name('device_trace.cuh').read_text()
_match=re.search(r'slots=(\d+), capacity=(\d+), header_words=8\+slots, words=(\d+)',_HEADER)
assert _match, 'unsupported trace ABI'
SLOTS,CAPACITY,WORDS=map(int,_match.groups());HEADER=8+SLOTS

def decode_record(row,events):
    s,e,event,block,thread,a,b,sm=map(int,row)
    assert e>=s>0 and event in events,(s,e,event)
    return dict(start_ns=s,end_ns=e,event=event,block=block,thread=thread,aux0=a,aux1=b,sm=sm)
