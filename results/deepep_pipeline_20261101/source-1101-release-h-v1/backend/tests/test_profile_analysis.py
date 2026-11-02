import json
from pathlib import Path
import sys
import unittest

import test_validate_gate as fixtures

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import analyze_profiles as analysis


def events(operation):
    return [dict(ph='X', name='ep4k/' + operation + '/iteration0', ts=0, dur=10),
            dict(ph='X', name='kernel1', cat='kernel', ts=2, dur=8),
            dict(ph='X', name='kernel2', cat='kernel', ts=4, dur=3),
            dict(ph='X', name='kernel3', cat='kernel', ts=14, dur=2),
            dict(ph='X', name='cudaDeviceSynchronize', cat='cuda_runtime', ts=1, dur=16)]


class ProfileTests(unittest.TestCase):
    def test_overlap_and_gap_are_not_double_counted(self):
        result, _ = analysis.analyze_events(events('cycle'), 'cycle', 1)
        self.assertEqual(result['kernel_span_us'], 14)
        self.assertEqual(result['kernel_union_us'], 10)
        self.assertEqual(result['kernel_gap_us'], 4)
        self.assertEqual(result['kernel_overlap_us'], 3)
        self.assertEqual(result['sync_api_union_us'], 16)

    def test_cpu_only_trace_rejected(self):
        with self.assertRaisesRegex(ValueError, 'No GPU'):
            analysis.analyze_events([events('cycle')[0]], 'cycle', 1)

    def test_iteration_missing_rejected(self):
        with self.assertRaisesRegex(ValueError, 'iteration'):
            analysis.analyze_events(events('cycle'), 'cycle', 2)

    def test_invalid_intervals_rejected(self):
        for intervals in [[(2, 1)], [(0, float('nan'))], [(0, float('inf'))]]:
            with self.assertRaises(ValueError):
                analysis.interval_stats(intervals)

    def prepare(self):
        fixture = fixtures.GateTests('test_complete')
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        ep = fixture.ep_fixture()
        fixture.spec['environment'].update(CXI_EP_TOKENS='4096', CXI_EP_DTYPES='fp8',
                                           CXI_EP_PROFILE_STEPS='1')
        (fixture.root / 'FINISHED.json').write_text(json.dumps({'returncode': 0, 'spec': fixture.spec}))
        profiles = ep / 'profiles'
        profiles.mkdir()
        for rank in range(8):
            path = ep / ('correctness-rank%d.jsonl' % rank)
            case = json.loads(path.read_text())
            case.update(tokens_per_gpu=4096, dispatch_dtype='fp8', actual_sms=64, qps=129,
                        route_sha256='test-route', input_sha256='test-input')
            path.write_text(json.dumps(case) + '\n')
            for op in ('dispatch_fresh', 'dispatch_cached', 'combine', 'cycle'):
                stem = 'v4flash-mixed-%s-rank%d' % (op, rank)
                summary = dict(case=case, operation=op, rank=rank, profiled_iterations=1)
                (profiles / (stem + '-summary.json')).write_text(json.dumps(summary))
                (profiles / (stem + '.json')).write_text(json.dumps({'traceEvents': events(op)}))
        return fixture.root, profiles

    def test_all_rank_diagnostic_only(self):
        root, _ = self.prepare()
        status, rows, kernels = analysis.analyze(root)
        self.assertEqual(status['status'], 'DIAGNOSTIC_ONLY')
        self.assertEqual(len(rows), 32)
        self.assertEqual(len(kernels), 96)

    def test_missing_rank_trace_rejected(self):
        root, profiles = self.prepare()
        (profiles / 'v4flash-mixed-cycle-rank7-summary.json').unlink()
        with self.assertRaisesRegex(ValueError, 'Missing traces'):
            analysis.analyze(root)

    def test_mismatched_input_identity_rejected(self):
        root, profiles = self.prepare()
        path = profiles / 'v4flash-mixed-cycle-rank7-summary.json'
        record = json.loads(path.read_text())
        record['case']['input_sha256'] = 'different-input'
        path.write_text(json.dumps(record))
        with self.assertRaisesRegex(ValueError, 'correctness case'):
            analysis.analyze(root)


if __name__ == '__main__':
    unittest.main()
