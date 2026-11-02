# UNQUALIFIED queue-credit device-header experiment

This snapshot overlays the raw probe and installed device headers. Its NCCL
patch still reconstructs the baseline host/library sources, not a complete
candidate rebuild. Use install_prefix.sh with a NEW prefix to overlay the
candidate headers on a verified copy of the tested host library. The ABI is
unchanged; all GPU kernels consuming these headers must be freshly compiled.
No candidate hardware gate has passed. Do not install this into the baseline
prefix or use its timings before prerequisite correctness gates pass.

# Experimental direct CXI GIN source bundle

Apply `DeepEP.patch` and `nccl.patch` to the exact commits in
`source-manifest.json` using `git apply --check` followed by `git apply`.
The exporter reconstructed both patches in fresh temporary checkouts and
compared every changed/new file with the worktrees.

`backend/` contains the host plugin, device code, bounded Slurm launcher,
qualification tests and SGLang adapter. Its README documents the experimental
support boundary. Source reconstruction is not a build or GPU correctness pass.
The cluster scripts currently contain site-specific paths; use new isolated
prefixes for a clean rebuild and never overwrite the recorded tested release.
Preserve the vendor license notices in the hardware-definition header.

DeepEP remains at bd1e1669. CXI uses private GIN type 6, not GDAKI type 3.
This bundle is local preparation; no upstream PR has been published.

If `rebuild-inputs.json` is included, all three pinned base archives are bundled.
Before building, run `python3 backend/tools/verify_rebuild_inputs.py .`.
See `backend/docs/reproduce.md` for the site-specific rebuild and qualification
procedure. A complete archive bundle is not a completed clean GPU rerun.
