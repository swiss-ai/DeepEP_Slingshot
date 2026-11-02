import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('allocation_time', Path(__file__).resolve().parents[1] / 'tools/allocation_time.py')
module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)


class AllocationTests(unittest.TestCase):
    def payload(self, state='RUNNING', end=2200, job=42):
        return {'jobs': [{'job_id': job, 'job_state': [state],
                          'end_time': {'set': True, 'infinite': False, 'number': end}}]}

    def test_backfill_export_is_stale(self):
        r = module.allocation_remaining({'SLURM_JOB_ID': '42', 'SLURM_JOB_END_TIME': '1300'},
                                        now=1000, query=lambda _: self.payload())
        self.assertEqual(r['remaining_seconds'], 1200)
        self.assertEqual(r['source'], 'scontrol current job record')

    def test_shorter_real_allocation_wins(self):
        r = module.allocation_remaining({'SLURM_JOB_ID': '42', 'SLURM_JOB_END_TIME': '2200'},
                                        now=1000, query=lambda _: self.payload(end=1100))
        self.assertEqual(r['remaining_seconds'], 100)

    def test_terminal_job_admits_nothing(self):
        r = module.allocation_remaining({'SLURM_JOB_ID': '42', 'SLURM_JOB_END_TIME': '2200'},
                                        now=1000, query=lambda _: self.payload(state='COMPLETED'))
        self.assertEqual(r['remaining_seconds'], 0)

    def test_query_failure_uses_export(self):
        def failed(_):
            raise OSError('scheduler temporarily unavailable')
        r = module.allocation_remaining({'SLURM_JOB_ID': '42', 'SLURM_JOB_END_TIME': '1300'},
                                        now=1000, query=failed)
        self.assertEqual(r['remaining_seconds'], 300)
        self.assertEqual(r['source'], 'exported end time fallback')

    def test_unknown_deadline_admits_nothing(self):
        r = module.allocation_remaining({'SLURM_JOB_ID': '42'}, now=1000,
                                        query=lambda _: {'jobs': []})
        self.assertEqual(r['remaining_seconds'], 0)


if __name__ == '__main__':
    unittest.main()
