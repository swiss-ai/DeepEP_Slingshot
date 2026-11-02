#!/usr/bin/env python3
"""Stage a separate header experiment; do not replace the tested backend."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--base-bundle', type=Path, required=True)
parser.add_argument('--candidate', type=Path, required=True)
parser.add_argument('--destination', type=Path, required=True)
args = parser.parse_args()
if args.destination.exists():
    raise SystemExit('Use a new experiment snapshot')
base = json.loads((args.base_bundle / 'source-manifest.json').read_text())
candidate = json.loads((args.candidate / 'manifest.json').read_text())
for name, digest in base['backend_sha256'].items():
    if sha(args.base_bundle / name) != digest:
        raise ValueError('Baseline bundle changed: ' + name)
if base['backend_sha256']['backend/device/cxi_primitives.cuh'] != candidate['base_primitives_sha256']:
    raise ValueError('Candidate is for a different baseline primitive implementation')
for name, digest in candidate['files_sha256'].items():
    if Path(name).name != name or sha(args.candidate / name) != digest:
        raise ValueError('Candidate file changed: ' + name)
shutil.copytree(args.base_bundle, args.destination)
shutil.copyfile(args.base_bundle / 'source-manifest.json', args.destination / 'baseline-source-manifest.json')
overlay = args.destination / 'nccl-device-overlay'
overlay.mkdir()
for name in ['cxi_primitives.cuh', 'cxi_queue_credit.h']:
    shutil.copyfile(args.candidate / name, args.destination / 'backend/device' / name)
    shutil.copyfile(args.candidate / name, overlay / name)
shutil.copyfile(args.candidate / 'candidate.patch', args.destination / 'device-candidate.patch')
shutil.copyfile(Path(__file__).with_name('install_prefix.sh'), args.destination / 'install_prefix.sh')
base['qualification'] = 'UNQUALIFIED device-header experiment on unchanged baseline host library; not a candidate NCCL rebuild'
base['experimental_device_overlay'] = {
    'name': 'cq_credit_v1',
    'files_sha256': {p.name: sha(p) for p in overlay.iterdir()},
    'baseline_primitives_sha256': candidate['base_primitives_sha256'],
    'baseline_library_sha256': '43126080b901ff199c20dce664aec5d39eda36c8785aac629c45de4a3b95f295',
    'scope': 'raw and JIT/probe device headers only; host ABI unchanged; not deployed to baseline or qualified on GPU',
}
base['backend_sha256'] = {str(p.relative_to(args.destination)): sha(p)
                          for p in sorted((args.destination / 'backend').rglob('*')) if p.is_file()}
(args.destination / 'source-manifest.json').write_text(json.dumps(base, indent=2) + '\n')
readme = args.destination / 'README.md'
readme.write_text('''# UNQUALIFIED queue-credit device-header experiment

This snapshot overlays the raw probe and installed device headers. Its NCCL
patch still reconstructs the baseline host/library sources, not a complete
candidate rebuild. Use install_prefix.sh with a NEW prefix to overlay the
candidate headers on a verified copy of the tested host library. The ABI is
unchanged; all GPU kernels consuming these headers must be freshly compiled.
No candidate hardware gate has passed. Do not install this into the baseline
prefix or use its timings before prerequisite correctness gates pass.

''' + readme.read_text())
print(json.dumps({'status': 'STAGED_UNQUALIFIED', 'snapshot': str(args.destination),
                  'overlay': base['experimental_device_overlay']}, indent=2))
