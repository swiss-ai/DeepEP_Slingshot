import importlib.util,json,tempfile
from pathlib import Path
root=Path(__file__).resolve().parents[4]/'results/deepep_pipeline_20261030/source-marker-probe-v2'
spec=importlib.util.spec_from_file_location('qual',root/'runner/validate_gate.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
with tempfile.TemporaryDirectory() as tmp:
 p=Path(tmp);smoke=p/'direct/smoke';smoke.mkdir(parents=True)
 for node in range(2):
  q=p/'direct'/('node%d'%node);q.mkdir();(q/'PASS').touch()
 for expect in ('preserve','clobber'):
  env=dict(CXI_TRANSPORT='direct',CXI_TEST_KIND='smoke',CXI_SMOKE_CONTEXTS='2',CXI_SMOKE_ROUNDS='14',CXI_MUTATION_EXPECT=expect)
  gate=dict(qualification='gin',environment=env)
  for rank in range(8):
   name='case-rank%d.jsonl'%rank
   rows=[dict(context=c,rounds=14,errors=0) for c in range(2)]
   rows += [dict(mutation_probe=True,expect_clobber=expect=='clobber',rounds=100,errors=0,observed=0xff000000 if expect=='clobber' else 0),dict(complete=True,rc=0)]
   (smoke/name).write_text(''.join(json.dumps(x)+'\n' for x in rows))
   (smoke/('rank%d.json'%rank)).write_text(json.dumps(dict(rank=rank,stage='complete',gin_type='6',kind='smoke',cases=[dict(cycle=0,contexts=2,returncode=0,evidence=name)])))
  assert m.qualify(p,gate)['status']=='PASS'
  name=smoke/'case-rank7.jsonl';rows=[json.loads(x) for x in name.read_text().splitlines()];rows[-2]['observed']^=1;name.write_text(''.join(json.dumps(x)+'\n' for x in rows))
  try:m.qualify(p,gate)
  except ValueError:pass
  else:raise AssertionError('wrong observed byte accepted')
 print('PASS preserved/clobbered diagnostics distinguished; incorrect observation rejected')
