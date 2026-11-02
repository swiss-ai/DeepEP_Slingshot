#!/usr/bin/env bash
set -euo pipefail
root=/iopsstor/scratch/cscs/zyu/deepep-direct-20261026/tenhour
exec 9>"$root/control-debug-submit.lock"
flock 9
[ ! -s "$root/control-debug-job.txt" ] || exit 0
[ -f "$root/control-build.PASS" ] || { printf 'Control build not ready\n' >&2;exit 1; }
normal=$(cat "$root/control-normal-job.txt")
state=$(squeue -j "$normal" -h -o '%T')
# Only replace our own still-pending normal job. A running/completed attempt
# is never interrupted or automatically repeated by this scheduling helper.
[ "$state" = PENDING ] || exit 0
scancel --state=PENDING "$normal"
sleep 1
state=$(squeue -j "$normal" -h -o '%T')
[ -z "$state" ] || exit 0
accounting=$(sacct -X -j "$normal" -n -P -o State | head -n 1)
case "$accounting" in CANCELLED*) ;; *) exit 0;; esac
job=$(sbatch --parsable --partition=debug --time=00:15:00 "$root/tools/control.sbatch")
printf '%s\n' "$job" > "$root/control-debug-job.txt"
printf 'Submitted batch job %s\n' "$job"
