#!/usr/bin/env python3
"""Verify pinned source archives before extraction; no GPU/build implied."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

PINS = {
    'DeepEP': 'bd1e1669a9324a4a111e3786658f1a4a43151f1e',
    'nccl': '12df1a11afad322be5a204a2db890161cbf8131d',
    'fmt': 'a4c7e17133ee9cb6a2f45545f6e974dd3c393efa',
}


def verify(bundle, components):
    bundle = Path(bundle)
    manifest = json.loads((bundle / 'rebuild-inputs.json').read_text())
    checked = {}
    for name in components:
        entry = manifest[name]
        if entry['commit'] != PINS[name]:
            raise ValueError('Wrong pinned commit: ' + name)
        filename = entry['archive']
        if not filename or Path(filename).name != filename:
            raise ValueError('Archive must be a local filename')
        archive = bundle / filename
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        if digest != entry['sha256']:
            raise ValueError('Archive hash mismatch: ' + name)
        with archive.open('rb') as file:
            commit = subprocess.check_output(['git', 'get-tar-commit-id'], stdin=file).decode().strip()
        if commit != PINS[name]:
            raise ValueError('Archive commit differs from its manifest: ' + name)
        checked[name] = dict(commit=commit, sha256=digest)
    return checked


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('bundle', type=Path)
    parser.add_argument('--components', nargs='+', choices=sorted(PINS), default=sorted(PINS))
    args = parser.parse_args()
    print(json.dumps({'status': 'ARCHIVES_VERIFIED', 'components': verify(args.bundle, args.components)}, indent=2))


if __name__ == '__main__':
    main()
