#!/usr/bin/env bash
# Header experiment only. No rebuild or GPU qualification is implied.
set -euo pipefail
[ "$#" = 3 ] || { printf 'Usage: %s SNAPSHOT TESTED_PREFIX NEW_PREFIX\n' "$0" >&2; exit 2; }
snapshot=$(realpath "$1")
tested=$(realpath "$2")
prefix=$(realpath -m "$3")
[ ! -e "$prefix" ] || { printf 'Use a new private prefix\n' >&2; exit 2; }
python3 - "$snapshot" "$tested" <<'PY'
import hashlib,json,sys
from pathlib import Path
snapshot,tested=map(Path,sys.argv[1:])
m=json.loads((snapshot/'source-manifest.json').read_text())['experimental_device_overlay']
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
assert sha(tested/'lib/libnccl.so.2.32.3')==m['baseline_library_sha256']
assert sha(tested/'include/nccl_device/gin/cxi/cxi_primitives.cuh')==m['baseline_primitives_sha256']
for name,digest in m['files_sha256'].items():
    assert Path(name).name==name
    assert sha(snapshot/'nccl-device-overlay'/name)==digest
    assert sha(snapshot/'backend/device'/name)==digest
PY
mkdir -p "$prefix"
cp -a "$tested/include" "$prefix/include"
# Copy the real library; construct private relative symlinks explicitly.
mkdir "$prefix/lib"
cp "$tested/lib/libnccl.so.2.32.3" "$prefix/lib/libnccl.so.2.32.3"
ln -s libnccl.so.2.32.3 "$prefix/lib/libnccl.so.2"
ln -s libnccl.so.2 "$prefix/lib/libnccl.so"
cp "$snapshot/nccl-device-overlay/cxi_primitives.cuh" "$prefix/include/nccl_device/gin/cxi/"
cp "$snapshot/nccl-device-overlay/cxi_queue_credit.h" "$prefix/include/nccl_device/gin/cxi/"
python3 - "$snapshot" "$prefix" <<'PY'
import hashlib,json,sys
from pathlib import Path
snapshot,prefix=map(Path,sys.argv[1:])
m=json.loads((snapshot/'source-manifest.json').read_text())['experimental_device_overlay']
assert hashlib.sha256((prefix/'lib/libnccl.so.2.32.3').read_bytes()).hexdigest()==m['baseline_library_sha256']
for name,digest in m['files_sha256'].items():
    assert hashlib.sha256((prefix/'include/nccl_device/gin/cxi'/name).read_bytes()).hexdigest()==digest
(prefix/'EXPERIMENT_UNQUALIFIED.json').write_text(json.dumps(m,indent=2)+'\n')
PY
