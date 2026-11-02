#!/usr/bin/env python3
"""Read-only CLIC dependency audit. No GPU initialization or transport fallback.

Exit 0 means the requested file/tool checks passed, never runtime KI support.
Exit 2 means a required dependency/check is missing. Works on Python >=3.6.
"""
import argparse
import datetime
import glob
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess


def file_info(path):
    p = Path(path)
    try:
        with p.open('rb') as f:
            digest = hashlib.sha256()
            for block in iter(lambda: f.read(1024 * 1024), b''):
                digest.update(block)
        return dict(path=str(p), resolved=str(p.resolve()), readable=True,
                    sha256=digest.hexdigest())
    except OSError as e:
        return dict(path=str(p), readable=False, error=str(e))


def inspect_prefix(prefix):
    p = Path(prefix)
    headers = [file_info(p / 'include/rdma' / name) for name in
               ('fabric.h', 'fi_cxi_ext.h', 'fi_cxi_gpu_ext.h')]
    # Require a linkable development library in this prefix, not a system fallback.
    libraries = [file_info(p / d / 'libfabric.so') for d in ('lib', 'lib64')]
    return dict(prefix=str(p), headers=headers, libraries=libraries,
                dependency_files_present=all(x['readable'] for x in headers)
                and any(x['readable'] for x in libraries))


def run(cmd):
    try:
        p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           universal_newlines=True, timeout=30)
        return dict(command=cmd, returncode=p.returncode,
                    stdout=p.stdout[-12000:], stderr=p.stderr[-12000:])
    except (OSError, subprocess.TimeoutExpired) as e:
        return dict(command=cmd, error=str(e), returncode=None)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--libfabric', help='Explicit KI provider prefix; never replaced automatically')
    ap.add_argument('--output', required=True)
    ap.add_argument('--require-compute', action='store_true')
    ap.add_argument('--require-toolchain', action='store_true')
    ap.add_argument('--compile-check', action='store_true')
    args = ap.parse_args()
    requested = args.libfabric or os.getenv('CXI_KI_PREFIX')
    prefixes = ([requested] if requested else []) + [
        '/iopsstor/scratch/cscs/zyu/deepep-v2-20261022/lf-install']
    prefixes += sorted(glob.glob('/opt/cray/libfabric/*'))
    prefixes += ['/usr', '/usr/local', '/opt/libfabric']
    prefixes = list(dict.fromkeys(prefixes))
    checks = [inspect_prefix(p) for p in prefixes]
    candidates = [x for x in checks if x['dependency_files_present']]
    selected = next((x for x in checks if x['prefix'] == requested), None)
    reasons = []
    if requested and not selected['dependency_files_present']:
        reasons.append('Explicit provider prefix lacks readable required headers/linkable library')
    elif not candidates:
        reasons.append('No complete KI libfabric development installation in checked prefixes')
    tools = {k: shutil.which(os.getenv(k.upper(), k)) for k in ('cc', 'cmake', 'nvcc')}
    if args.require_toolchain and not all(tools.values()):
        reasons.append('Missing C/CUDA/CMake build tools')
    cxi_devices = sorted(glob.glob('/sys/class/cxi/cxi[0-9]*'))
    if args.require_compute and (not os.getenv('SLURM_JOB_ID') or not cxi_devices
                                 or platform.machine() not in ('aarch64', 'arm64')):
        reasons.append('Expected an allocated ARM64 CXI compute node')
    compile_result = None
    if args.compile_check:
        if selected and selected['dependency_files_present'] and tools['cc']:
            cmd = [tools['cc'], '-fsyntax-only', '-I' + str(Path(requested) / 'include')]
            cuda = os.getenv('CUDA_PATH', '/usr/local/cuda')
            cmd += ['-I' + str(Path(cuda) / 'include'), str(Path(__file__).with_name('ki_api_probe.c'))]
            compile_result = run(cmd)
            if compile_result['returncode'] != 0:
                reasons.append('KI header/API syntax check failed')
        else:
            reasons.append('Compile check needs an explicit complete --libfabric prefix and C compiler')
    report = dict(
        status='DEPENDENCY_CHECK_FAILED' if reasons else 'DEPENDENCY_CHECK_PASSED',
        runtime_ki_verified=False, cpu_free_progress_verified=False,
        warning='File/API checks do not establish matching provider ABI, GPU doorbell mapping, or CPU-free progress.',
        timestamp_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        hostname=platform.node(), architecture=platform.machine(),
        kernel=platform.release(), job_id=os.getenv('SLURM_JOB_ID'),
        requested_prefix=requested, reasons=reasons, prefixes=checks,
        tools=tools, cxi_devices=cxi_devices,
        source=run(['git', '-C', str(Path(__file__).with_name('CLIC_SwissAI')), 'rev-parse', 'HEAD']),
        compile_check=compile_result)
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(dict(status=report['status'], reasons=reasons,
                          candidates=[x['prefix'] for x in candidates], report=str(out))))
    return 2 if reasons else 0


if __name__ == '__main__':
    raise SystemExit(main())
