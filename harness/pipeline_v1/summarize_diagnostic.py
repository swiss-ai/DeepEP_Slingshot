"""Read live host phase markers without assuming synchronized node clocks."""
import argparse
import json
from pathlib import Path


def records(path):
    if not path.exists():
        return [], False
    raw=path.read_text();lines=raw.splitlines();rows=[];partial=False
    for index,line in enumerate(lines):
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            if index!=len(lines)-1 or raw.endswith('\n'):
                raise
            partial=True
    return rows,partial


def main():
    parser=argparse.ArgumentParser();parser.add_argument('gate',type=Path)
    args=parser.parse_args();base=args.gate/'direct/ep'
    result=[]
    for rank in range(8):
        rows,partial=records(base/('diagnostic-watch-rank%d.jsonl'%rank))
        correctness,_=records(base/('correctness-rank%d.jsonl'%rank))
        timing,_=records(base/('timings-rank%d.jsonl'%rank))
        last=rows[-1] if rows else {}
        result.append(dict(rank=rank,records=len(rows),partial_last_record=partial,
            tokens=last.get('tokens'),routing=last.get('routing'),operation=last.get('operation'),
            phase=last.get('phase'),call_index=last.get('call_index'),
            diagnostic_codes=sorted({r['diagnostic_code'] for r in rows if r.get('diagnostic_code')}),
            correctness_records=len(correctness),timing_records=len(timing)))
    print(json.dumps(dict(gate=str(args.gate),scope='Host phase markers; no cross-node clock alignment or GPU completion inferred',ranks=result),indent=2))


if __name__=='__main__':main()
