"""Identify both Git checkouts and deployed source archives without assuming .git."""
import hashlib
import json
from pathlib import Path
import subprocess


def source_metadata(source, origin_manifest=None, origin_key=None):
    source = Path(source)
    assert source.is_dir(), source
    git = subprocess.run(['git', '-C', str(source), 'rev-parse', '--show-toplevel'],
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
    # Do not accidentally attribute a copied directory to an enclosing repository.
    if git.returncode == 0 and Path(git.stdout.strip()).resolve() == source.resolve():
        commit = subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], universal_newlines=True).strip()
        origin = 'git_checkout'
    else:
        assert origin_manifest and origin_key, f'No source provenance for {source}'
        commit = json.loads(Path(origin_manifest).read_text())['sources'][origin_key]['sha']
        origin = 'recorded_archive_origin; deployed source identified separately by content hash'
    digest = hashlib.sha256()
    count = 0
    for p in sorted(source.rglob('*')):
        rel = p.relative_to(source)
        if any(x in {'.git', '__pycache__', 'build', 'dist'} for x in rel.parts):
            continue
        if not p.is_file() or p.suffix not in {'.py', '.c', '.cc', '.cpp', '.cu', '.cuh', '.h', '.hpp'}:
            continue
        digest.update(str(rel).encode() + b'\0')
        digest.update(hashlib.sha256(p.read_bytes()).digest())
        count += 1
    assert count > 0
    return dict(source_commit=commit, source_revision_origin=origin,
                deployed_source_sha256=digest.hexdigest(), source_files_hashed=count)
