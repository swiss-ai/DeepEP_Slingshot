import unittest
import tempfile,json,gzip
from pathlib import Path
from analyze import union,alignment,validate_capture,analyze

class TraceTests(unittest.TestCase):
    def test_overlapping_waits_not_added(self):
        self.assertEqual(union([(0,10),(2,8),(8,12),(20,21)]),13)
    def test_alignment_preserves_uncertainty(self):
        m={}
        for key in ('pre','post'):
            m['clock_'+key]={'offset_lower_ns':90,'offset_upper_ns':110}
            m['gpu_clock_'+key]={'best':{'gpu_ns':500,'host_lower_ns':1600,'host_upper_ns':1640}}
        self.assertEqual(alignment(m)['gpu_to_rank0_ns'],1020)
        self.assertEqual(alignment(m)['alignment_uncertainty_ns'],30)
    def test_clock_drift_widens_envelope(self):
        m={}
        for key,host in [('pre',1600),('post',1700)]:
            m['clock_'+key]={'offset_lower_ns':0,'offset_upper_ns':0}
            m['gpu_clock_'+key]={'best':{'gpu_ns':500,'host_lower_ns':host,'host_upper_ns':host+20}}
        self.assertEqual(alignment(m)['alignment_uncertainty_ns'],60)
    def test_overflow_rejected(self):
        with self.assertRaises(AssertionError):validate_capture({'correctness':'PASS','stats':{'overflow':1}})
    def test_missing_stages_rejected(self):
        with self.assertRaises(AssertionError):validate_capture({'correctness':'PASS','stats':{'overflow':0},'events':[]})
    def test_eight_rank_export_and_missing_rank_gate(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);base=root/'captures/v4flash';base.mkdir(parents=True)
            control=root/'original-control/direct/ep';control.mkdir(parents=True)
            for rank in range(8):
                m=dict(rank=rank,gin_type='6',hidden=4096,topk=6,remote_tokens=1,route_sha256='route',
                       captures=[{},{}],disabled_before={'cuda_event_us':[100]},disabled_after={'cuda_event_us':[100]})
                for key in ('pre','post'):
                    m['clock_'+key]={'offset_lower_ns':0,'offset_upper_ns':10}
                    m['gpu_clock_'+key]={'best':{'gpu_ns':500,'host_lower_ns':1000,'host_upper_ns':1010}}
                (base/f'manifest-rank{rank}.json').write_text(json.dumps(m));(base/f'DONE-rank{rank}').write_text('PASS')
                (control/f'timings-rank{rank}.jsonl').write_text(json.dumps(dict(model='v4flash',operation='dispatch_fresh',route_sha256='route',cuda_event_us=[100]))+'\n')
                for iteration in range(2):
                    events=[dict(event=code,start_ns=600+i*10,end_ns=605+i*10,block=0,thread=0,aux0=0,aux1=0,sm=0)
                            for i,code in enumerate([100,101,102,103,104,105,106,111,112,120,121,200,201,202,203,204,206])]
                    c=dict(rank=rank,iteration=iteration,cuda_event_us=110,correctness='PASS',stats={'overflow':0},events=events,host_events=[['dispatch_enter',1000],['dispatch_exit',1200]])
                    with gzip.open(base/f'dispatch-rank{rank}-iteration{iteration}.json.gz','wt') as f:json.dump(c,f)
            v=analyze(base,root/'analysis');self.assertEqual(v['ranks'],8);self.assertTrue(v['low_perturbation_diagnostic'])
            self.assertTrue((root/'analysis/overview.html').is_file())
            (base/'DONE-rank7').unlink()
            with self.assertRaises(FileNotFoundError):analyze(base,root/'missing')

if __name__=='__main__':unittest.main()
