"""Ensure an ordinary CXI install cannot pass the KI dependency gate."""
import tempfile
from pathlib import Path
import unittest
from preflight import inspect_prefix


class DependencyGate(unittest.TestCase):
    def test_requires_extension_and_linkable_library_in_same_prefix(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            inc = p / 'include/rdma'
            inc.mkdir(parents=True)
            lib = p / 'lib'
            lib.mkdir()
            for name in ('fabric.h', 'fi_cxi_ext.h'):
                (inc / name).write_text('ordinary provider')
            (lib / 'libfabric.so').write_bytes(b'fixture')
            self.assertFalse(inspect_prefix(tmp)['dependency_files_present'])
            (inc / 'fi_cxi_gpu_ext.h').write_text('KI fixture')
            self.assertTrue(inspect_prefix(tmp)['dependency_files_present'])
            (lib / 'libfabric.so').unlink()
            self.assertFalse(inspect_prefix(tmp)['dependency_files_present'])

    def test_broken_library_symlink_is_not_available(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            (p / 'include/rdma').mkdir(parents=True)
            (p / 'lib').mkdir()
            for name in ('fabric.h', 'fi_cxi_ext.h', 'fi_cxi_gpu_ext.h'):
                (p / 'include/rdma' / name).write_text('fixture')
            (p / 'lib/libfabric.so').symlink_to('missing.so')
            self.assertFalse(inspect_prefix(tmp)['dependency_files_present'])


if __name__ == '__main__':
    unittest.main()
