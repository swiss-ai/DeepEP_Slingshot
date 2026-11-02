import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from compare_sglang import match_rank


class PairingTests(unittest.TestCase):
    def fixture(self):
        record = dict(rank=0, hostname='test-node', job='test-job', cpu_affinity=[0, 1],
            source={'commit': 'pinned'}, test_sha256='test', native_extension_sha256='extension',
            nccl_sha256='nccl', model_geometry='v4flash', hidden=4096, experts=256, topk=6,
            routing='deterministic', warmup_iterations=10, timed_iterations=50,
            actual_sglang_scatter_gather=True, actual_sglang_expert_kernels=False,
            overlay_manifest={k: k for k in ['original_dispatcher_sha256', 'patched_dispatcher_sha256', 'adapter_sha256']},
            cases=[dict(dtype='fp8', tokens=4096, step=10, input_sha256='input', route_sha256='route',
                        weights_sha256='weights', received_tokens=18000, warmup=False, exact_dispatch_reference='PASS')])
        return record, copy.deepcopy(record)

    def test_matching(self):
        match_rank(*self.fixture())

    def test_input_route_weight_mismatch(self):
        for field in ['input_sha256', 'route_sha256', 'weights_sha256']:
            a, b = self.fixture(); b['cases'][0][field] = 'changed'
            with self.assertRaises(ValueError):
                match_rank(a, b)

    def test_source_or_placement_mismatch(self):
        for field in ['source', 'nccl_sha256', 'native_extension_sha256', 'hostname', 'job']:
            a, b = self.fixture(); b[field] = 'changed'
            with self.assertRaises(ValueError):
                match_rank(a, b)

    def test_missing_exact_reference(self):
        a, b = self.fixture(); b['cases'][0].pop('exact_dispatch_reference')
        with self.assertRaises(ValueError):
            match_rank(a, b)


if __name__ == '__main__':
    unittest.main()
