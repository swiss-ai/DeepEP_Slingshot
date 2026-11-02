"""Exercise the pinned import guard without importing CUDA/PyTorch on the host.

Extract the actual function from the selected checkout; use real temporary
library files and synthetic /proc/self/maps entries to exercise its decisions.
"""
import argparse
import ast
import builtins
import filecmp
import glob
import io
import os
from pathlib import Path
import re
import tempfile
from unittest.mock import patch


def check(source):
    tree = ast.parse(source.read_text())
    function = next(n for n in tree.body if isinstance(n, ast.FunctionDef)
                    and n.name == 'check_nccl_so')
    scope = dict(os=os, re=re, glob=glob, filecmp=filecmp)
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(source), 'exec'), scope)
    results = []
    with tempfile.TemporaryDirectory(prefix='cxi-nccl-guard-') as tmp:
        root = Path(tmp)
        (root / 'lib').mkdir()
        linked = root / 'lib/libnccl.so.2'
        linked.write_bytes(b'expected-runtime')
        other = root / 'other/libnccl.so.2'
        other.parent.mkdir()
        other.write_bytes(b'different-runtime')
        scope['find_nccl_root'] = lambda: str(root)
        real_open = builtins.open

        def run(name, paths, expected_error=None):
            maps = ''.join('1000-2000 r-xp 00000000 00:01 1 ' + str(p) + '\n' for p in paths)

            def opened(path, *args, **kwargs):
                return io.StringIO(maps) if path == '/proc/self/maps' else real_open(path, *args, **kwargs)

            with patch.dict(os.environ, {'EP_SUPPRESS_NCCL_CHECK': '0'}), patch('builtins.open', opened):
                try:
                    scope['check_nccl_so']()
                except AssertionError as error:
                    if expected_error is None or expected_error not in str(error):
                        raise
                else:
                    assert expected_error is None, name + ': expected runtime rejection'
            results.append(name)

        run('one runtime with repeated mappings', [linked, linked])
        run('runtime plus OFI and GIN plugins', [linked, root / 'libnccl-net.so', root / 'libnccl-gin-cxi.so'])
        run('two runtimes rejected', [linked, other], 'Duplicate NCCL runtime')
        run('different linked runtime rejected', [other], 'Invalid NCCL versions')
        run('plugins alone are not a runtime', [root / 'libnccl-gin-cxi.so'], 'No NCCL runtime')
    print('PASS: ' + '; '.join(results))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', type=Path, required=True)
    check(parser.parse_args().source)
