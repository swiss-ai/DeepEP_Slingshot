#!/usr/bin/env bash
# Run inside an allocated GH200 CUDA container. All outputs stay in BUILD_ROOT.
set -euo pipefail
[[ $# = 1 ]] || { echo 'usage: CXI_KI_PREFIX=/matching/provider bash build.sh /absolute/new-build-root' >&2; exit 2; }
here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
build_root=$1
[[ "$build_root" = /* && ! -e "$build_root" ]] || { echo 'Build root must be an absolute, unused path' >&2; exit 2; }
: "${CXI_KI_PREFIX:?Set the matching KI-enabled libfabric prefix}"
export CUDA_PATH="${CUDA_PATH:-/usr/local/cuda}"
export PATH="$CUDA_PATH/bin:$PATH"
export CC="${CC:-gcc}"
export CXX="${CXX:-g++}"
export CUDAHOSTCXX="${CUDAHOSTCXX:-$CXX}"
python_bin=${CLIC_BUILD_PYTHON:-python3}
mkdir -p "$build_root"
"$python_bin" "$here/preflight.py" --libfabric "$CXI_KI_PREFIX" \
    --require-compute --require-toolchain --compile-check --output "$build_root/preflight.json"
expected=e80f60c059e1e5f272fc630eb15d60b5b09d8391
actual=$(git -C "$here/CLIC_SwissAI" rev-parse HEAD)
[[ "$actual" = "$expected" ]] || { echo 'Unexpected CLIC revision; update the pin deliberately' >&2; exit 2; }
[[ -z "$(git -C "$here/CLIC_SwissAI" status --porcelain --untracked-files=no)" ]] || { echo 'CLIC has tracked edits; archive them explicitly before building' >&2; exit 2; }
mkdir "$build_root/source"
git -C "$here/CLIC_SwissAI" archive HEAD | tar -x -C "$build_root/source"
printf '%s\n' "$actual" > "$build_root/source-revision.txt"
"$python_bin" -m venv --system-site-packages "$build_root/venv"
export CLIC_PYTHON="$build_root/venv/bin/python"
export LIBFABRIC_PATH="$CXI_KI_PREFIX"
export OPENMPI_PATH="${CLIC_OPENMPI_PREFIX:-/usr}"
export CLIC_BUILD_JOBS="${CLIC_BUILD_JOBS:-8}"
export MAX_JOBS="$CLIC_BUILD_JOBS"
export LD_LIBRARY_PATH="$LIBFABRIC_PATH/lib:$LIBFABRIC_PATH/lib64:${LD_LIBRARY_PATH:-}"
"$CLIC_PYTHON" -m pip freeze > "$build_root/python-before.txt"
bash "$build_root/source/install.sh" 2>&1 | tee "$build_root/build.log"
"$CLIC_PYTHON" -c 'import clic; print(clic.__file__)' | tee "$build_root/import.txt"
ldd "$build_root/source/build/src/libclic.so" > "$build_root/linked-libraries.txt"
"$CLIC_PYTHON" -m pip freeze > "$build_root/python-after.txt"
{
    printf 'export CUDA_PATH=%q\n' "$CUDA_PATH"
    printf 'export LIBFABRIC_PATH=%q\n' "$LIBFABRIC_PATH"
    printf 'export OPENMPI_PATH=%q\n' "$OPENMPI_PATH"
    printf 'export CLIC_PYTHON=%q\n' "$CLIC_PYTHON"
    printf 'export CLIC_SOURCE=%q\n' "$build_root/source"
} > "$build_root/runtime.sh"
echo 'CLIC_BUILD_COMPLETE: runtime KI and CPU-free progress remain unverified'
