"""Immutable decoder-only repair; preserve all GPU instrumentation and transport."""
import argparse
import ast
import hashlib
import json
import shutil
from pathlib import Path


def event_map(path):
    events = {}
    for statement in ast.parse(path.read_text()).body:
        if isinstance(statement, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'EVENTS' for t in statement.targets):
            events.update(ast.literal_eval(statement.value))
        if isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Call):
            call = statement.value
            if isinstance(call.func, ast.Attribute) and isinstance(call.func.value, ast.Name) and call.func.value.id == 'EVENTS' and call.func.attr == 'update':
                events.update(ast.literal_eval(call.args[0]))
    return events


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('base', type=Path); parser.add_argument('output', type=Path)
    args = parser.parse_args(); base, out = args.base.resolve(), args.output.resolve()
    shutil.copytree(base, out, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    runner = out / 'runner/trace_capture.py'
    source = runner.read_text()
    # Older native-fence packages may already contain event 211; normalizing
    # the complete map also makes the active import independently checkable.
    assert source.count('TRACE=None') == 1
    source = source.replace('TRACE=None', "EVENTS.update({209:'TX_publication',210:'delivery_marker_enqueue',211:'NIC_fence_enqueue'})\nTRACE=None")
    runner.write_text(source)
    shutil.copyfile(runner, out / 'backend/tests/trace_capture.py')
    assert {209, 210, 211} <= set(event_map(out / 'backend/tests/trace_capture.py'))
    sequence = json.loads((out / 'sequence.json').read_text())
    for step in sequence:
        step['snapshot'] = str(Path(step['snapshot']).parent / out.name)
    (out / 'sequence.json').write_text(json.dumps(sequence, indent=2) + '\n')
    changes = {str(p.relative_to(base)) for p in base.rglob('*') if p.is_file()
               and '__pycache__' not in p.parts and p.suffix != '.pyc'
               and p.read_bytes() != (out / p.relative_to(base)).read_bytes()}
    assert changes == {'runner/trace_capture.py', 'backend/tests/trace_capture.py', 'sequence.json'}, changes
    manifest = json.loads((base / 'manifest.json').read_text())
    manifest.update(scope='Decoder-only repair: active backend/tests and runner event maps synchronized; GPU/transport unchanged',
        files={str(p.relative_to(out)): hashlib.sha256(p.read_bytes()).hexdigest()
               for p in sorted(out.rglob('*')) if p.is_file() and p.name != 'manifest.json'})
    (out / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(out)


if __name__ == '__main__':
    main()
