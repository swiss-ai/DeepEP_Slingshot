"""Install an audited serving-harness overlay without modifying shared inodes."""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

parent_name, name = sys.argv[1:]
assert all(Path(x).name == x for x in (parent_name, name))
campaign = Path(__file__).resolve().parent
parent, source = campaign / 'sources' / parent_name, campaign / 'sources' / name
assert (campaign / 'preflight' / parent_name / 'PASS').is_file()
assert not source.exists()
before = json.loads((parent / 'manifest.json').read_text())
changed = {'backend/tools/direct_node.sh', 'backend/tests/sglang_dispatcher_smoke.py', 'runner/validate_gate.py', 'sequence.json'}
shutil.copytree(str(parent), str(source), copy_function=os.link,
                ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
with tarfile.open(str(campaign / (name + '-overlay.tar.gz'))) as archive:
    assert {m.name for m in archive.getmembers()} == changed | {'manifest.json'}
    for m in archive:
        assert m.isfile()
        dest = source / m.name
        temp = dest.with_name(dest.name + '.new')
        with temp.open('xb') as f:
            f.write(archive.extractfile(m).read())
        os.chmod(str(temp), m.mode)
        temp.replace(dest)
after = json.loads((source / 'manifest.json').read_text())
assert set(after['files']) == set(before['files'])
assert {k for k in before['files'] if before['files'][k] != after['files'][k]} == changed
for root, manifest in [(parent, before), (source, after)]:
    for relative, digest in manifest['files'].items():
        assert hashlib.sha256((root / relative).read_bytes()).hexdigest() == digest, (root, relative)
subprocess.check_call(['bash', '-n', str(source / 'backend/tools/direct_node.sh')])
runtime = campaign / 'runtime' / name
assert not runtime.exists()
runtime.symlink_to(parent_name, target_is_directory=True)
for variant in json.loads((source / 'variants.json').read_text()):
    root = runtime / variant
    for relative, digest in json.loads((root / 'runtime-manifest.json').read_text())['files'].items():
        assert hashlib.sha256((root / relative).read_bytes()).hexdigest() == digest, relative
out = campaign / 'preflight' / name
out.mkdir()
(out / 'compile-equivalence.json').write_text(json.dumps(dict(
    parent=parent_name, changed=sorted(changed), unchanged_compiled_inputs=True,
    parent_manifest_sha256=hashlib.sha256((parent / 'manifest.json').read_bytes()).hexdigest(),
    manifest_sha256=hashlib.sha256((source / 'manifest.json').read_bytes()).hexdigest(),
    checker_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    scope='Inherited GPU/runtime compilation; serving harness syntax checked locally; GPU serving qualification pending'), indent=2) + '\n')
(out / 'PASS').write_text('PASS exact unchanged compiled inputs/runtime and shell syntax; GPU serving pending\n')
print('PASS serving harness staged, GPU pending', name)
