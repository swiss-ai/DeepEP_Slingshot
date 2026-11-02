"""Recover an unused runtime installation using immutable identical compiled inputs."""
import hashlib,json,sys
from pathlib import Path
campaign=Path(sys.argv[1]);old=campaign/'sources/source-marker-probe-v1';new=campaign/'sources/source-marker-probe-v2'
assert (campaign/'preflight'/old.name/'PASS').is_file()
def manifest(root):
 d=json.loads((root/'manifest.json').read_text())['files']
 for name,h in d.items():assert hashlib.sha256((root/name).read_bytes()).hexdigest()==h,(root,name)
 return d
before=manifest(old);after=manifest(new)
assert set(before)==set(after)
changed={k for k in before if before[k]!=after[k]}
assert changed=={'runner/validate_gate.py','sequence.json'},changed
compile((new/'runner/validate_gate.py').read_text(),'validate_gate.py','exec')
variants=json.loads((new/'variants.json').read_text());runtime=campaign/'runtime'/new.name
# Installer must have been stopped before this script; this prefix has no GPU users.
retired=runtime.with_name(runtime.name+'-incomplete-20261031-0314')
assert runtime.is_dir() and not runtime.is_symlink() and not retired.exists()
runtime.rename(retired);runtime.symlink_to(old.name,target_is_directory=True)
for variant in variants:
 p=runtime/variant;d=json.loads((p/'runtime-manifest.json').read_text())
 assert d['defines']==variants[variant]
 for name,h in d['files'].items():assert hashlib.sha256((p/name).read_bytes()).hexdigest()==h,(variant,name)
out=campaign/'preflight'/new.name;out.mkdir(exist_ok=True)
(out/'compile-equivalence.json').write_text(json.dumps(dict(parent=str(old),changed=sorted(changed),runtime_alias=str(runtime.resolve()),retained_incomplete_runtime=str(retired),scope='Identical GPU/transport inputs and verified runtime hashes; host qualifier-only correction; no GPU outcome asserted'),indent=2)+'\n')
(out/'PASS').write_text('PASS identical compiled GPU sources/runtime and corrected host qualifier syntax\n')
print('PASS v2 GPU inputs/runtime identical to compiled v1; unused incomplete install preserved')
