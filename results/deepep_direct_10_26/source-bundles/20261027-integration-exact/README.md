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
