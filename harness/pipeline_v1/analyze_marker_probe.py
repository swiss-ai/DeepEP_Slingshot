"""Separate an expected-negative marker reproduction from transport correctness."""
import argparse,json
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('gate',type=Path);a=p.parse_args();root=a.gate
finished=json.loads((root/'FINISHED.json').read_text());spec=finished['spec'];expected=spec['environment']['CXI_MUTATION_EXPECT'];records=[]
for rank in range(8):
 case=json.loads((root/'direct/smoke'/('rank%d.json'%rank)).read_text())
 for cycle in case['cases']:
  rows=[json.loads(x) for x in (root/'direct/smoke'/cycle['evidence']).read_text().splitlines()]
  records.extend(dict(rank=rank,**x) for x in rows if x.get('mutation_probe'))
result=dict(gate=spec['name'],expected=expected,qualification=finished['qualification'],
 scope=('Expected-negative reproduction of receiver-buffer corruption; NOT transport correctness qualification' if expected=='clobber' else 'Notification clear remains intact after flush; full EP qualification still required'),
 observed_values_hex=sorted({hex(x['observed']) for x in records}),ranks=len(records),
 verified_rounds=sum(x['rounds'] for x in records),errors=sum(x['errors'] for x in records),records=records)
assert len(records)==8 and {x['rank'] for x in records}==set(range(8))
(root/'marker-analysis.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps({k:v for k,v in result.items() if k!='records'},indent=2))
