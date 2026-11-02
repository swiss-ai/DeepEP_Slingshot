"""Verify decoder-only repair against compiled parent without changing GPU code."""
import ast
import hashlib
import importlib.util
import json
import sys
from pathlib import Path


def check(root, name):
    data = json.loads((root / name).read_text())
    for path, digest in data['files'].items():
        assert hashlib.sha256((root / path).read_bytes()).hexdigest() == digest, path
    return data


def main():
    source, parent = map(Path, sys.argv[1:])
    campaign = source.parent.parent
    assert (campaign / 'preflight' / parent.name / 'PASS').is_file()
    old, new = check(parent, 'manifest.json'), check(source, 'manifest.json')
    assert old['files'].keys() == new['files'].keys()
    changed = {k for k in old['files'] if old['files'][k] != new['files'][k]}
    assert changed == {'runner/trace_capture.py', 'backend/tests/trace_capture.py', 'sequence.json'}
    for variant in json.loads((source / 'variants.json').read_text()):
        a = check(campaign / 'runtime' / parent.name / variant, 'runtime-manifest.json')
        b = check(campaign / 'runtime' / source.name / variant, 'runtime-manifest.json')
        assert a['files'] == b['files']
    active = source / 'backend/tests/trace_capture.py'
    assert active.read_bytes() == (source / 'runner/trace_capture.py').read_bytes()
    events = {}
    for statement in ast.parse(active.read_text()).body:
        if isinstance(statement, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'EVENTS' for t in statement.targets):
            events.update(ast.literal_eval(statement.value))
        if isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Call):
            call = statement.value
            if isinstance(call.func, ast.Attribute) and isinstance(call.func.value, ast.Name) and call.func.value.id == 'EVENTS' and call.func.attr == 'update':
                events.update(ast.literal_eval(call.args[0]))
    assert {209, 210, 211} <= set(events)
    spec = importlib.util.spec_from_file_location('decoder_preflight', str(source / 'backend/tests/trace_format.py'))
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    for event in [200, 207, 209, 210, 211]:
        row = module.decode_record([100, 120, event, 1, 32, 0, 0, 2], events)
        assert row['event'] == event and row['end_ns'] == 120
    for record in [[120, 100, 209, 1, 32, 0, 0, 2], [100, 120, 999, 1, 32, 0, 0, 2]]:
        try:
            module.decode_record(record, events)
        except AssertionError:
            pass
        else:
            raise AssertionError('Malformed/unknown event was accepted')
    output = campaign / 'preflight' / source.name
    output.mkdir(parents=True, exist_ok=True)
    evidence = dict(parent=str(parent), changed_sources=sorted(changed),
                    gpu_and_transport_sources='byte-identical', private_runtimes='byte-identical',
                    active_decoder_events=sorted(events), valid_and_invalid_decode_checks='PASS')
    (output / 'decoder-equivalence.json').write_text(json.dumps(evidence, indent=2) + '\n')
    (output / 'PASS').write_text('Decoder repair tested; all GPU compilation inputs and runtimes match compiled parent. GPU recapture pending.\n')
    print(json.dumps(evidence), flush=True)


if __name__ == '__main__':
    main()
