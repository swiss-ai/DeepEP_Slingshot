#!/usr/bin/env python3
"""Validate scheduled EP arguments using the real parser, without importing CUDA.

Only the local trusted harness's argument-parser block is executed. This catches
unsupported matrix entries before a GPU allocation is consumed.
"""
import argparse
import ast
import json
from pathlib import Path
import sys


def validate(sequence):
    tests = Path(__file__).resolve().parents[1] / 'tests'
    sys.path.insert(0, str(tests))
    from routing import ROUTING_CHOICES, routes
    tree = ast.parse((tests / 'ep_benchmark.py').read_text())
    models = next(ast.literal_eval(node.value) for node in tree.body
                  if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'MODELS' for t in node.targets))
    block = next(node for node in tree.body if isinstance(node, ast.If)
                 and ast.unparse(node.test) == "__name__ == '__main__'")
    statements = []
    for node in block.body:
        if isinstance(node, ast.With):
            break
        statements.append(node)
    namespace = {'argparse': argparse, 'MODELS': models, 'ROUTING_CHOICES': ROUTING_CHOICES}
    exec(compile(ast.Module(body=statements, type_ignores=[]), '<local EP parser>', 'exec'), namespace)
    parser = namespace['p']
    fields = {'MODELS': 'models', 'TOKENS': 'tokens', 'DTYPES': 'dtypes', 'ROUTING': 'routing',
              'SEEDS': 'seeds', 'WARMUP': 'warmup', 'ITERS': 'iters', 'NIC_ITERS': 'nic-iters',
              'PROFILE_STEPS': 'profile-steps'}
    names = set()
    for step in sequence:
        name, spec = step['name'], step['spec']
        if name in names or not set(spec.get('requires', [])).issubset(names):
            raise ValueError('Duplicate step or forward/missing dependency: ' + name)
        names.add(name)
        env = spec.get('environment', {})
        if env.get('CXI_TEST_KIND') != 'ep':
            continue
        args = ['--backend', 'deepep', '--output', '/unused/validation-only']
        for key, option in fields.items():
            if 'CXI_EP_' + key in env:
                args += ['--' + option] + env['CXI_EP_' + key].split()
        parsed = parser.parse_args(args)
        for route in parsed.routing:
            if route.startswith('skew'):
                h, experts, topk = models[parsed.models[0]]
                routes(128, 8, experts, topk, float(route[4:]), 1)
        if parsed.iters < 1 or parsed.warmup < 0:
            raise ValueError('Invalid iteration count: ' + name)
    return {'status': 'PASS', 'requests': len(sequence), 'scope': 'dependencies and actual EP parser/routing bounds; not GPU correctness'}


if __name__ == '__main__':
    print(json.dumps(validate(json.loads(Path(sys.argv[1]).read_text())), indent=2))
