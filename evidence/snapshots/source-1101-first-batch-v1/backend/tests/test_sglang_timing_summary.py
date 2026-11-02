import importlib.util
import json
from pathlib import Path
import sys
import unittest

import test_validate_gate as fixtures

tools = Path(__file__).resolve().parents[1] / 'tools'
sys.path.insert(0, str(tools))
spec = importlib.util.spec_from_file_location('summarize_sglang', tools / 'summarize_sglang.py')
module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)


class TimingTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.GateTests('test_complete')
        self.fixture.setUp(); self.addCleanup(self.fixture.doCleanups)
        self.fixture.sglang_fixture()
        self.root = self.fixture.root

    def finished(self):
        (self.root / 'FINISHED.json').write_text(json.dumps({'returncode': 0, 'spec': self.fixture.spec}))

    def performance(self):
        self.fixture.spec['environment'].update(CXI_SGLANG_DTYPES='fp8', CXI_SGLANG_TOKENS='4096',
                                               CXI_SGLANG_WARMUP='10', CXI_SGLANG_ROUNDS='30')
        for rank in range(8):
            path = self.fixture.smoke / ('rank%d.json' % rank)
            record = json.loads(path.read_text())
            record.update(warmup_iterations=10, timed_iterations=30, routing='synthetic fixture', cases=[])
            for step in range(40):
                # Deliberately enormous cold timings must not affect statistics.
                value = 1e9 if step < 10 else 100 + step - 10 + rank
                record['cases'].append({'dtype': 'fp8', 'tokens': 4096, 'step': step, 'warmup': step < 10,
                    'max_abs_error': 0.001, 'dispatch_cuda_us': value, 'combine_cuda_us': 2 * value,
                    'dispatch_wrapper_ms': value / 1000, 'combine_wrapper_ms': 2 * value / 1000})
            self.fixture.write_rank(rank, record)
        self.finished()

    def test_smoke_is_not_performance(self):
        self.finished(); status, rows = module.summarize(self.root)
        self.assertEqual(status['status'], 'CORRECTNESS_ONLY'); self.assertEqual(rows, [])

    def test_warmup_excluded_and_rank_maxima_used(self):
        self.performance(); status, rows = module.summarize(self.root)
        self.assertEqual(status['status'], 'PASS')
        dispatch = next(r for r in rows if r['operation'] == 'dispatch')
        self.assertEqual(dispatch['median_rank_max_cuda_us'], 121.5)
        self.assertEqual(dispatch['p95_rank_max_cuda_us'], 135)
        self.assertEqual(dispatch['max_rank_max_cuda_us'], 136)

    def test_nonfinite_timing_rejected(self):
        self.performance(); p = self.fixture.smoke / 'rank0.json'
        record = json.loads(p.read_text()); record['cases'][10]['dispatch_cuda_us'] = float('nan')
        self.fixture.write_rank(0, record)
        with self.assertRaises(ValueError):
            module.summarize(self.root)

    def test_wrong_warmup_label_rejected(self):
        self.performance(); p = self.fixture.smoke / 'rank7.json'
        record = json.loads(p.read_text()); record['cases'][10]['warmup'] = True
        self.fixture.write_rank(7, record)
        with self.assertRaises(ValueError):
            module.summarize(self.root)

    def test_proxy_timing_keeps_transport_label(self):
        self.performance()
        (self.root / 'direct').rename(self.root / 'proxy')
        self.fixture.smoke = self.root / 'proxy/smoke'
        self.fixture.spec['environment']['CXI_TRANSPORT'] = 'proxy'
        for rank in range(8):
            p = self.fixture.smoke / ('rank%d.json' % rank)
            record = json.loads(p.read_text())
            record.update(gin_type='2', proxy_control=True, transport='proxy_ofi_cxi')
            self.fixture.write_rank(rank, record)
        self.finished()
        status, rows = module.summarize(self.root)
        self.assertEqual(status['status'], 'PASS')
        self.assertTrue(all(r['transport'] == 'proxy' and r['gin_type'] == '2' for r in rows))


if __name__ == '__main__':
    unittest.main()
