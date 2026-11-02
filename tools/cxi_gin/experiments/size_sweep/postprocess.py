import json,sys
from pathlib import Path
from sweep_analyze import main
root=Path(sys.argv[1]);attempts=list((root/'results/results').glob('*size-sweep-repeat*/FINISHED.json'))
if len(attempts)!=3 or any(json.loads(p.read_text()).get('qualification',{}).get('status')!='PASS' for p in attempts):
 (root/'SWEEP_INCOMPLETE.txt').write_text('Not all three complete sweeps passed. Preserve partial raw data; no final fit.\n')
else:main(root)
