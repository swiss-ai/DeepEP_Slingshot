#!/usr/bin/env bash
# Apply this repository's patches to pristine NCCL and DeepEP checkouts and copy the backend's
# device headers into the NCCL source tree.
#
#   scripts/apply_patches.sh [--profile full|release|qualified] [--trace] [--variant NAME] [--check]
#                            NCCL_SRC DEEPEP_SRC
#
#   NCCL_SRC    NCCL checkout at 12df1a11 (v2.32.3-1)
#   DEEPEP_SRC  DeepEP checkout at bd1e1669 with third-party/fmt checked out (a4c7e171)
#   --profile   full      every change, all extra knobs default off (default; the tree of the
#                         2026-11-03 snapshots source-1103-combine-v1 .. ep8skew-v3)
#               release   qualified + lean signal path only (source-1102-lean-v1, release matrix 3835100)
#               qualified the 2026-11-01 release (source-1101-first-batch-v1, 98-gate matrix 3830101)
#   --trace     also apply the device/host trace hooks (attribution builds only, not for timing)
#   --variant   prepend the transport variant's defines (backend/variants.json, e.g. lean-b) to the
#               cxi_primitives.cuh copied into NCCL_SRC, so every consumer of the installed headers
#               compiles that variant; without it the header defaults apply (see docs/usage.md)
#   --check     only verify that everything applies; change nothing
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd); repo=$(dirname "$here")
profile=full; trace=0; variant=""; check=0
while [ $# -gt 0 ]; do
  case "$1" in
    --profile) profile=$2; shift 2;;
    --trace) trace=1; shift;;
    --variant) variant=$2; shift 2;;
    --check) check=1; shift;;
    -h|--help) sed -n '2,20p' "$0"; exit 0;;
    --*) printf 'unknown option %s\n' "$1" >&2; exit 2;;
    *) break;;
  esac
done
[ $# -eq 2 ] || { printf 'usage: %s [options] NCCL_SRC DEEPEP_SRC\n' "$0" >&2; exit 2; }
nccl=$(realpath "$1"); deepep=$(realpath "$2")
[ -f "$nccl/src/include/nccl_device/gin/gin_device_api.h" ] || { printf 'not an NCCL source tree: %s\n' "$nccl" >&2; exit 2; }
[ -f "$deepep/deep_ep/include/deep_ep/impls/hybrid_dispatch.cuh" ] || { printf 'not a DeepEP v2 source tree: %s\n' "$deepep" >&2; exit 2; }
expect() { # expect DIR COMMIT: warn when the checkout is not at the pinned commit
  local head; head=$(git -C "$1" rev-parse HEAD 2>/dev/null || echo unknown)
  case "$head" in "$2"*) ;; *) printf 'warning: %s is at %s, patches are made against %s\n' "$1" "${head:0:12}" "$2" >&2;; esac
}
expect "$nccl" 12df1a11afad322be5a204a2db890161cbf8131d
expect "$deepep" bd1e1669a9324a4a111e3786658f1a4a43151f1e
case "$profile" in
  full) deepep_patches=("$repo/patches/deepep-bd1e1669-cxi-full.patch"); trace_patch=$repo/patches/deepep-trace-hooks-full.patch;;
  release) deepep_patches=("$repo/patches/deepep-bd1e1669-cxi-qualified.patch" "$repo/patches/1102/lean-signal-deepep-1102.patch"); trace_patch="";;
  qualified) deepep_patches=("$repo/patches/deepep-bd1e1669-cxi-qualified.patch"); trace_patch=$repo/patches/deepep-trace-hooks.patch;;
  *) printf 'unknown profile %s\n' "$profile" >&2; exit 2;;
esac
if [ $trace = 1 ] && [ -z "$trace_patch" ]; then printf 'no trace patch for profile %s (use full or qualified)\n' "$profile" >&2; exit 2; fi
[ $trace = 1 ] && deepep_patches+=("$trace_patch")
nccl_patch=$repo/patches/nccl-12df1a11-cxi-integration.patch
# --check first for every patch, so a half-applied tree is never left behind
git -C "$nccl" apply --check "$nccl_patch"
tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
cp -a "$deepep/." "$tmp/deepep"; rm -rf "$tmp/deepep/.git"
for p in "${deepep_patches[@]}"; do git -C "$tmp/deepep" apply "$p"; done
printf 'check PASS: %s and %d DeepEP patch(es) apply (profile %s%s)\n' "$(basename "$nccl_patch")" "${#deepep_patches[@]}" "$profile" "$([ $trace = 1 ] && echo ', trace')"
if [ -n "$variant" ]; then python3 -c "import json,sys; json.load(open(sys.argv[1]))[sys.argv[2]]" "$repo/backend/variants.json" "$variant"; fi
[ $check = 1 ] && exit 0
git -C "$nccl" apply "$nccl_patch"
for p in "${deepep_patches[@]}"; do git -C "$deepep" apply "$p"; printf 'applied %s\n' "$(basename "$p")"; done
dest=$nccl/src/include/nccl_device/gin/cxi; mkdir -p "$dest"
for f in include/cassini_user_defs.h include/cxi_gin_abi.h device/cxi_primitives.cuh device/cxi_queue_credit.h device/cxi_fence_command.h device/gin_cxi.cuh; do
  cp "$repo/backend/$f" "$dest/"
done
if [ -n "$variant" ]; then
  python3 - "$repo/backend/variants.json" "$variant" "$dest/cxi_primitives.cuh" <<'PY'
import json,sys
defs=json.load(open(sys.argv[1]))[sys.argv[2]]; p=sys.argv[3]
text=open(p).read()
open(p,'w').write(''.join('#define %s %d\n'%(k,v) for k,v in sorted(defs.items()))+text)
print('variant %s baked into %s: %s'%(sys.argv[2],p,' '.join('%s=%d'%kv for kv in sorted(defs.items()))))
PY
fi
(cd "$dest" && sha256sum cassini_user_defs.h cxi_gin_abi.h cxi_primitives.cuh gin_cxi.cuh cxi_queue_credit.h cxi_fence_command.h) > "$nccl/src/include/nccl_device/gin/cxi/SHA256SUMS"
printf 'installed backend headers into %s\n' "$dest"
printf 'next: build NCCL (make -C %s/src src.build ...), the plugin (scripts/build_plugin.sh) and DeepEP; see docs/usage.md\n' "$nccl"
