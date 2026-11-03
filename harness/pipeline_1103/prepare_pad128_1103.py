#!/usr/bin/env python3
"""Row stride padded to a 128-byte multiple (2026-11-03 evening): the fix for the alignment cliff of our
GPU-issued PUTs (11_01 alignment probe: a PUT whose address is 64 bytes off a 128-byte line runs at a
quarter of the link rate; 11_03 §5.5: a one-row combine batch is 4x slower). DeepEP's TokenLayout aligns
each component to 32 bytes, giving rows of 4320 (FP8 dispatch), 8288 (BF16 dispatch) and 8256 (combine)
bytes, so odd row boundaries are 32 or 64 bytes off a line. Rounding the per-token size up to 128 bytes
(4352 / 8320 / 8320, +0.4 to +0.8 % payload) puts every row boundary on a line; component offsets are
unchanged. Host (csrc) and device code share layout.cuh and the extension is rebuilt from the archive in
every job, so sizes stay consistent; the change is unconditional in the archive (no -D knob) for that reason.
"""
import sys, tarfile, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'pipeline_v1'))
from package import replace  # noqa: E402


def prepare(snapshot, archives=('DeepEP.tar.gz',)):
    out = Path(snapshot)
    for archive in archives:
      with tempfile.TemporaryDirectory() as d:
        ep = Path(d)
        with tarfile.open(out / archive) as a: a.extractall(ep)
        f = ep / 'deep_ep/include/deep_ep/common/layout.cuh'
        replace(f, '''                               math::align<int>(kWithMBarrier ? sizeof(ptx::mbarrier) : 0, ptx::kNumTMAAlignBytes);
        return static_cast<dtype_t>(num_bytes);
''', '''                               math::align<int>(kWithMBarrier ? sizeof(ptx::mbarrier) : 0, ptx::kNumTMAAlignBytes);
        // CXI pad128 (2026-11-03): every row boundary on a 128-byte line, so no PUT of a packed run of
        // rows starts 32 or 64 bytes off a line (the alignment cliff of the GPU-issued CXI path).
        return static_cast<dtype_t>(math::align<int>(num_bytes, 128));
''')
        with tarfile.open(out / archive, 'w:gz') as a: a.add(ep, arcname='.')
    return out


if __name__ == '__main__':
    prepare(sys.argv[1]); print('prepared', sys.argv[1])
