"""Validate a host-observer-only snapshot against its qualified compilation inputs."""
import hashlib
import json
import sys
from pathlib import Path


def check(root, name):
    data=json.loads((root/name).read_text())
    for relative,digest in data['files'].items():
        assert hashlib.sha256((root/relative).read_bytes()).hexdigest()==digest,(root,relative)
    return data


def main():
    source,parent=map(Path,sys.argv[1:]);campaign=source.parent.parent
    assert (campaign/'preflight'/parent.name/'PASS').is_file()
    old=check(parent,'manifest.json')['files'];new=check(source,'manifest.json')['files']
    assert set(new)-set(old)=={'backend/tests/diagnostic_watch.py'}
    assert not set(old)-set(new)
    changed={k for k in old if old[k]!=new[k]}
    assert changed=={'backend/tests/ep_benchmark.py','runner/validate_gate.py','sequence.json'},changed
    variants=json.loads((source/'variants.json').read_text())
    for variant in variants:
        before=check(campaign/'runtime'/parent.name/variant,'runtime-manifest.json')
        after=check(campaign/'runtime'/source.name/variant,'runtime-manifest.json')
        assert before==after,variant
    for name in ['backend/tests/ep_benchmark.py','backend/tests/diagnostic_watch.py','runner/validate_gate.py']:
        compile((source/name).read_text(),name,'exec')
    output=campaign/'preflight'/source.name;output.mkdir(parents=True,exist_ok=True)
    (output/'compile-equivalence.json').write_text(json.dumps(dict(parent=str(parent),
        changed_sources=sorted(changed),unchanged_runtime_variants=list(variants),
        scope='Read-only diagnostic harness only; all GPU/transport compilation inputs byte-identical; GPU replay pending'),indent=2)+'\n')
    (output/'PASS').write_text('Diagnostic harness syntax and GPU/runtime input equivalence PASS\n')
    print('PASS diagnostic-only source/runtime equivalence')


if __name__=='__main__':main()
