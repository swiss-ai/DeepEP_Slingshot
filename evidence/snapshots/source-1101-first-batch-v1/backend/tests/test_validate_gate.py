import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

module_spec = importlib.util.spec_from_file_location(
    'validate_gate', Path(__file__).resolve().parents[1] / 'tools/validate_gate.py')
module = importlib.util.module_from_spec(module_spec)
module_spec.loader.exec_module(module)


class GateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.spec = {'qualification': 'gin', 'environment': {
            'CXI_SMOKE_CONTEXTS': '1', 'CXI_SMOKE_RESET': '1',
            'CXI_SMOKE_NEGATIVE': '1', 'CXI_SMOKE_SELF': '1'}}
        for node in range(2):
            p = self.root / 'direct' / ('node%d' % node)
            p.mkdir(parents=True)
            (p / 'PASS').touch()
        self.smoke = self.root / 'direct/smoke'
        self.smoke.mkdir()
        for rank in range(8):
            record = {'rank': rank, 'stage': 'complete', 'gin_type': '6', 'kind': 'smoke',
                      'cases': [{'cycle': 0, 'contexts': 1, 'returncode': 0,
                                 'evidence': 'contexts1-rank%d.jsonl' % rank}]}
            self.write_rank(rank, record)
            self.write_rows(rank, [
                {'negative_version': True, 'rc': 5, 'expected': 5},
                {'context': 0, 'rounds': 14, 'errors': 0},
                {'reset_epoch': 1, 'context': 0, 'rounds': 14, 'errors': 0},
                {'delayed_peer': True, 'rank': rank, 'first': 8 if rank < 4 else 0,
                 'expected_first': 8 if rank < 4 else 0, 'recovered': 0, 'flush': 0},
                {'self_signal': True, 'context': 0, 'rc': 0},
                {'complete': True, 'rc': 0}])

    def write_rank(self, rank, record):
        (self.smoke / ('rank%d.json' % rank)).write_text(json.dumps(record))

    def rows(self, rank):
        return module.json_lines(self.smoke / ('contexts1-rank%d.jsonl' % rank))

    def write_rows(self, rank, rows):
        (self.smoke / ('contexts1-rank%d.jsonl' % rank)).write_text(
            ''.join(json.dumps(r) + '\n' for r in rows))

    def test_complete(self):
        self.assertEqual(module.qualify(self.root, self.spec)['status'], 'PASS')

    def test_persistent_lifecycle_requires_hold_and_release(self):
        self.spec['environment']['CXI_LIFECYCLE_HOLD_WINDOW'] = '1'
        with self.assertRaisesRegex(ValueError, 'persistent lifecycle'):
            module.qualify(self.root, self.spec)
        for rank in range(8):
            path = self.smoke / ('rank%d.json' % rank)
            record = json.loads(path.read_text())
            record.update(held_window=True, held_window_released=True)
            self.write_rank(rank, record)
        self.assertEqual(module.qualify(self.root, self.spec)['status'], 'PASS')
        record['held_window_released'] = False
        self.write_rank(7, record)
        with self.assertRaisesRegex(ValueError, 'persistent lifecycle'):
            module.qualify(self.root, self.spec)

    def test_missing_node(self):
        (self.root / 'direct/node1/PASS').unlink()
        with self.assertRaises(ValueError):
            module.qualify(self.root, self.spec)

    def test_missing_rank(self):
        (self.smoke / 'rank7.json').unlink()
        with self.assertRaises(FileNotFoundError):
            module.qualify(self.root, self.spec)

    def test_proxy_fallback(self):
        p = self.smoke / 'rank3.json'
        record = json.loads(p.read_text()); record['gin_type'] = '2'
        self.write_rank(3, record)
        with self.assertRaises(ValueError):
            module.qualify(self.root, self.spec)

    def test_failed_recovery(self):
        rows = self.rows(4); rows[3]['recovered'] = 8; self.write_rows(4, rows)
        with self.assertRaises(ValueError):
            module.qualify(self.root, self.spec)

    def test_payload_error(self):
        rows = self.rows(2); rows[1]['errors'] = 1; self.write_rows(2, rows)
        with self.assertRaises(ValueError):
            module.qualify(self.root, self.spec)

    def test_teardown_failure(self):
        rows = self.rows(7); rows[-1]['rc'] = 1; self.write_rows(7, rows)
        with self.assertRaises(ValueError):
            module.qualify(self.root, self.spec)

    def test_missing_self_signal(self):
        self.write_rows(0, [r for r in self.rows(0) if not r.get('self_signal')])
        with self.assertRaises(ValueError):
            module.qualify(self.root, self.spec)

    def test_missing_reset(self):
        self.write_rows(1, [r for r in self.rows(1) if 'reset_epoch' not in r])
        with self.assertRaises(ValueError):
            module.qualify(self.root, self.spec)

    def test_unsafe_evidence(self):
        record = json.loads((self.smoke / 'rank0.json').read_text())
        record['cases'][0]['evidence'] = '../../elsewhere'
        self.write_rank(0, record)
        with self.assertRaises(ValueError):
            module.qualify(self.root, self.spec)

    def ep_fixture(self):
        self.spec = {'qualification': 'ep', 'environment': {}}
        ep = self.root / 'direct/ep'; ep.mkdir()
        (ep / 'validation.json').write_text(json.dumps({'status': 'PASS', 'ep': 8}))
        for rank in range(8):
            (ep / ('DONE-rank%d' % rank)).touch()
            (ep / ('correctness-rank%d.jsonl' % rank)).write_text(json.dumps({
                'rank': rank, 'ep': 8, 'model': 'v4flash', 'tokens_per_gpu': 32,
                'dispatch_dtype': 'bf16', 'routing': 'mixed', 'seed': 1,
                'status': 'PASS', 'gin_type': '6'}) + '\n')
        return ep

    def test_ep_complete(self):
        self.ep_fixture()
        self.assertEqual(module.qualify(self.root, self.spec)['status'], 'PASS')

    def test_ep_matrix_incomplete(self):
        self.ep_fixture()
        self.spec['environment']['CXI_EP_TOKENS'] = '32 4096'
        with self.assertRaises(ValueError):
            module.qualify(self.root, self.spec)

    def test_ep_failure_file(self):
        ep = self.ep_fixture(); (ep / 'failures-rank0.jsonl').write_text('{}\n')
        with self.assertRaises(ValueError):
            module.qualify(self.root, self.spec)

    def test_ep_wrong_transport(self):
        ep = self.ep_fixture(); p = ep / 'correctness-rank7.jsonl'
        r = json.loads(p.read_text()); r['gin_type'] = '2'; p.write_text(json.dumps(r))
        with self.assertRaises(ValueError):
            module.qualify(self.root, self.spec)

    def sglang_fixture(self):
        self.spec = {'qualification': 'sglang', 'environment': {
            'CXI_SGLANG_MODEL': 'v4flash', 'CXI_SGLANG_GEMM': '1',
            'CXI_SGLANG_IMPORT_AFTER_INIT': '1'}}
        for rank in range(8):
            self.write_rank(rank, {'rank': rank, 'stage': 'complete', 'result': 'PASS',
                'gin_type': '6', 'model_geometry': 'v4flash', 'actual_sglang_scatter_gather': True,
                'actual_sglang_expert_kernels': True, 'import_after_group_init': True,
                'cases': [{'dtype': d, 'tokens': n, 'step': i, 'max_abs_error': 0.001}
                          for d in ['bf16', 'fp8'] for n in [32, 4096] for i in range(3)]})
            (self.smoke / ('libraries-rank%d.txt' % rank)).write_text('runtime paths')

    def test_sglang_complete(self):
        self.sglang_fixture()
        self.assertEqual(module.qualify(self.root, self.spec)['status'], 'PASS')

    def test_sglang_incomplete(self):
        self.sglang_fixture(); p = self.smoke / 'rank1.json'
        record = json.loads(p.read_text()); record['cases'].pop(); self.write_rank(1, record)
        with self.assertRaises(ValueError):
            module.qualify(self.root, self.spec)

    def test_sglang_wrong_scope(self):
        self.sglang_fixture(); p = self.smoke / 'rank3.json'
        record = json.loads(p.read_text()); record['actual_sglang_expert_kernels'] = False
        self.write_rank(3, record)
        with self.assertRaises(ValueError):
            module.qualify(self.root, self.spec)

    def test_sglang_nonfinite_error(self):
        self.sglang_fixture(); p = self.smoke / 'rank4.json'
        record = json.loads(p.read_text()); record['cases'][0]['max_abs_error'] = float('nan')
        self.write_rank(4, record)
        with self.assertRaises(ValueError):
            module.qualify(self.root, self.spec)

    def test_sglang_exact_reference_required(self):
        self.sglang_fixture()
        self.spec['environment']['CXI_SGLANG_EXACT_REFERENCE'] = '1'
        with self.assertRaises(ValueError):
            module.qualify(self.root, self.spec)
        for rank in range(8):
            record = json.loads((self.smoke / ('rank%d.json' % rank)).read_text())
            record['exact_dispatch_reference'] = True
            for case in record['cases']:
                case['exact_dispatch_reference'] = 'PASS'
            self.write_rank(rank, record)
        self.assertEqual(module.qualify(self.root, self.spec)['status'], 'PASS')
        record['cases'][0]['exact_dispatch_reference'] = 'FAIL'
        self.write_rank(7, record)
        with self.assertRaises(ValueError):
            module.qualify(self.root, self.spec)

    def test_sglang_proxy_is_explicit_and_separate(self):
        self.sglang_fixture()
        (self.root / 'direct').rename(self.root / 'proxy')
        self.smoke = self.root / 'proxy/smoke'
        self.spec['environment']['CXI_TRANSPORT'] = 'proxy'
        with self.assertRaises(ValueError):
            module.qualify(self.root, self.spec)
        for rank in range(8):
            record = json.loads((self.smoke / ('rank%d.json' % rank)).read_text())
            record.update(gin_type='2', proxy_control=True, transport='proxy_ofi_cxi')
            self.write_rank(rank, record)
        verdict = module.qualify(self.root, self.spec)
        self.assertEqual((verdict['transport'], verdict['gin_type']), ('proxy', '2'))
        record['proxy_control'] = False
        self.write_rank(7, record)
        with self.assertRaises(ValueError):
            module.qualify(self.root, self.spec)

    def dynamic_fixture(self):
        self.spec = {'qualification': 'dynamic'}
        for node in range(2):
            base = self.root / 'dynamic' / ('node%d' % node)
            base.mkdir(parents=True)
            (base / 'status.tsv').write_text(''.join('%d\t0\n' % gpu for gpu in range(4)))
            for gpu in range(4):
                rank = node * 4 + gpu
                rows = [dict(rank=rank, stage='dynamic_result', cases=18, errors=0,
                             diagnostic=0, posted=100, completed=100),
                        dict(rank=rank, stage='process_result', rc=0, is_nccl_gin=False)]
                (base / ('gpu%d.log' % gpu)).write_text('inventory text\n' + ''.join(json.dumps(r) + '\n' for r in rows))

    def test_raw_dynamic_complete(self):
        self.dynamic_fixture()
        verdict = module.qualify(self.root, self.spec)
        self.assertEqual(verdict['kind'], 'raw_dynamic')
        self.assertEqual(verdict['ranks'], 8)

    def test_raw_dynamic_missing_gpu_status(self):
        self.dynamic_fixture()
        (self.root / 'dynamic/node1/status.tsv').write_text('0\t0\n1\t0\n2\t0\n')
        with self.assertRaises(ValueError):
            module.qualify(self.root, self.spec)

    def test_raw_dynamic_incomplete_completion(self):
        self.dynamic_fixture()
        path = self.root / 'dynamic/node1/gpu3.log'
        path.write_text(path.read_text().replace('"completed": 100', '"completed": 99'))
        with self.assertRaises(ValueError):
            module.qualify(self.root, self.spec)

    def producer_fixture(self):
        self.spec = {'qualification': 'gin', 'environment': {'CXI_TEST_KIND': 'producer'}}
        for rank in range(8):
            cases = []
            for cycle, blocks in enumerate([1, 2, 8]):
                filename = 'blocks%d-rank%d.jsonl' % (blocks, rank)
                cases.append(dict(blocks=blocks, cycle=cycle, evidence=filename, returncode=0))
                rows = [dict(block=b, rounds=128, errors=0) for b in range(blocks)]
                rows.append(dict(complete=True, blocks=blocks, rounds_requested=128, rc=0))
                (self.smoke / filename).write_text(''.join(json.dumps(r) + '\n' for r in rows))
            self.write_rank(rank, dict(rank=rank, stage='complete', gin_type='6', kind='producer', cases=cases))

    def test_producer_complete(self):
        self.producer_fixture()
        self.assertEqual(module.qualify(self.root, self.spec)['cycles_per_rank'], 3)

    def test_producer_partial_rounds(self):
        self.producer_fixture()
        path = self.smoke / 'blocks8-rank7.jsonl'
        path.write_text(path.read_text().replace('"rounds": 128', '"rounds": 127', 1))
        with self.assertRaises(ValueError):
            module.qualify(self.root, self.spec)

    def test_producer_duplicate_cta(self):
        self.producer_fixture()
        path = self.smoke / 'blocks8-rank7.jsonl'
        path.write_text(path.read_text().replace('"block": 7', '"block": 6'))
        with self.assertRaises(ValueError):
            module.qualify(self.root, self.spec)


if __name__ == '__main__':
    unittest.main()
