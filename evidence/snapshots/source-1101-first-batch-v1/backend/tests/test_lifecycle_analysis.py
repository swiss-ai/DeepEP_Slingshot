import sys
from pathlib import Path
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from analyze_lifecycle import audit_rank


def fixture(persistent=True):
    lines = []
    for cycle in range(20):
        reused = cycle*129 if persistent else 0
        for gpu in range(4):
            for phase, idle in [('context-created', 0), ('context-closed', 129)]:
                lines.append(f'CXI pool phase={phase} gpu={gpu} created=129 reused={reused} allocated=129 idle={idle} ct_in_use=129 usage_rc=0')
            if not persistent or cycle == 19:
                lines.append(f'CXI pool phase=idle-lni-close gpu={gpu} created=129 reused={reused} allocated=129 idle=129 ct_in_use=129 usage_rc=0')
    return '\n'.join(lines)


class LifecycleTests(unittest.TestCase):
    def test_persistent_reuse(self):
        result = audit_rank(fixture(), 3, 20, 129, True)
        self.assertEqual(result['reuse_count'], 2451)

    def test_real_extra_bank_and_resource_growth(self):
        root = Path(__file__).resolve().parents[4]
        logpath = root / 'results/deepep_direct_10_26/tenhour/leases/3768857/results/01-ct-persistent-window/direct/node0/smoke.log'
        if not logpath.exists():
            self.skipTest('retained GPU evidence unavailable')
        log = logpath.read_text()
        result = audit_rank(log, 0, 20, 129, True)
        self.assertEqual(result['physical_channels_per_lni'], 133)
        self.assertEqual(result['reuse_count'], 2451)
        with self.assertRaisesRegex(ValueError, 'physical CT usage grows'):
            audit_rank(log.replace('reused=2451 allocated=133 idle=0 ct_in_use=133',
                                   'reused=2451 allocated=133 idle=0 ct_in_use=134'), 0, 20, 129, True)
        with self.assertRaisesRegex(ValueError, 'initial context bank not released'):
            audit_rank(log.replace('allocated=133 idle=133', 'allocated=133 idle=129'), 0, 20, 129, True)

    def test_idle_reopen(self):
        self.assertEqual(audit_rank(fixture(False), 0, 20, 129, False)['idle_lni_closes'], 20)

    def test_hidden_growth(self):
        with self.assertRaisesRegex(ValueError, 'physical CT usage grows'):
            audit_rank(fixture().replace('reused=2451 allocated=129 idle=0 ct_in_use=129',
                                        'reused=2451 allocated=129 idle=0 ct_in_use=258'), 1, 20, 129, True)

    def test_missing_close(self):
        with self.assertRaisesRegex(ValueError, 'final LNI'):
            audit_rank('\n'.join(l for l in fixture().splitlines() if 'idle-lni-close' not in l), 0, 20, 129, True)

    def test_reopen_cannot_masquerade_as_reuse(self):
        with self.assertRaisesRegex(ValueError, 'did not reuse'):
            audit_rank(fixture(False), 0, 20, 129, True)

    def test_missing_rank(self):
        with self.assertRaisesRegex(ValueError, 'lifecycle events'):
            audit_rank(fixture(), 7, 20, 129, True)


if __name__ == '__main__':
    unittest.main()
