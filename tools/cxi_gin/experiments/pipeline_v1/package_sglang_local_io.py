"""Prepare serving checks with node-local journals; compiled inputs unchanged."""
import argparse
import hashlib
import json
import shutil
import subprocess
import tarfile
from pathlib import Path
from package import ROOT
from prepare_sglang_local_io import prepare

p = argparse.ArgumentParser()
p.add_argument('parent')
p.add_argument('name')
a = p.parse_args()
assert all(Path(x).name == x for x in (a.parent, a.name))
campaign = ROOT / 'results/deepep_pipeline_20261030'
parent, out = campaign / a.parent, campaign / a.name
assert not out.exists()
before = json.loads((parent / 'manifest.json').read_text())
for name, digest in before['files'].items():
    assert hashlib.sha256((parent / name).read_bytes()).hexdigest() == digest, name
shutil.copytree(parent, out, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
prepare(out)
# Requests are prepared separately after selecting qualified ordinary repeats.
(out / 'sequence.json').write_text('[]\n')
changed = {'backend/tools/direct_node.sh', 'backend/tests/sglang_dispatcher_smoke.py', 'runner/validate_gate.py', 'sequence.json'}
files = {str(f.relative_to(out)): hashlib.sha256(f.read_bytes()).hexdigest()
         for f in out.rglob('*') if f.is_file() and f.name != 'manifest.json'}
assert set(files) == set(before['files'])
assert {k for k in files if files[k] != before['files'][k]} == changed
subprocess.check_call(['bash', '-n', str(out / 'backend/tools/direct_node.sh')])
compile((out / 'backend/tests/sglang_dispatcher_smoke.py').read_text(), 'sglang_dispatcher_smoke.py', 'exec')
compile((out / 'runner/validate_gate.py').read_text(), 'validate_gate.py', 'exec')
before.update(files=files, source_parent=str(parent),
              scope='SGLang smoke journal/cache paths, post-run persistence and actual configuration evidence; all GPU/transport/compiled inputs unchanged; GPU serving checks pending')
(out / 'manifest.json').write_text(json.dumps(before, indent=2) + '\n')
with tarfile.open(campaign / (a.name + '-overlay.tar.gz'), 'w:gz') as archive:
    for name in sorted(changed | {'manifest.json'}):
        archive.add(out / name, arcname=name)
print('PASS local syntax and exact harness-only delta:', out)
