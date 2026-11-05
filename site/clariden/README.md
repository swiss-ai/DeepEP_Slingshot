# Clariden site files

External dependencies of the harness that are not part of the source: copies of the files the
qualification jobs used, so the environment can be reproduced from this repository alone.

| File | Used by | Content |
|---|---|---|
| `deepep-v2-cxi.toml` | `srun --environment=...` in every launcher | Container environment definition: image `lmsysorg/sglang:v0.5.13-cu130` (CUDA 13.0, Python 3.12, torch, SGLang, DeepGEMM), mounts of the host's `/usr` as `/host_usr` (libcxi 1.5.0 of SHS 13.1.0 and its headers), `/opt/cray`, the four `/dev/cxi*` devices and `/dev/gdrdrv`. Change `workdir` to your own scratch directory. |
| `runtime.sh` | sourced by `runtime_cxi.sh` | Python virtual environment with the pinned torch and the NCCL Python package, NVSHMEM root, JIT cache location. Written for the author's scratch tree; every path is a site constant to adapt. |
| `runtime_cxi.sh` | sourced first by `backend/tools/direct_node.sh` and `harness/runner/node.sh` | Adds the libfabric/CXI runtime variables of the proxy (type 2) control path. The direct backend overrides `NCCL_GIN_TYPE`, and the launchers set the plugin path and bootstrap interface themselves. |

Other site facts the scripts rely on:

- Slurm account `infra01`, partition `normal` (4 h) or `debug` (25 min; one running and two
  submitted jobs per user); two nodes, four GPUs and 288 CPUs per node, one launcher task per node.
  The allocation supplies `SLINGSHOT_DEVICES`, `SLINGSHOT_SVC_IDS` and `SLINGSHOT_VNIS`; never reuse
  another job's service identifiers.
- Node software at qualification: GH200 120 GB, driver 595.91.07, kernel `6.4.0-150600.23.125-64kb`,
  cray-libcxi 1.0.2 (`libcxi.so.1.5.0`), cray-cxi-driver 1.0.0 (SHS 13.1.0, 2026-01-27).
- Login-node and preflight compiles use a CUDA 13.0 toolkit extracted onto scratch
  (`.../cuda-sdk/usr/local/cuda-13.0` in the scripts) with `g++-14`; inside the container
  `/usr/local/cuda` is used. The first reconstructed NCCL build used GCC 7.5.0 and CUDA 13.0.88.
- `/dev/shm` is mounted `noexec` inside the container (Triton caches go to the container's `/tmp`);
  the login node's `/tmp` can be full.
