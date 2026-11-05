import json,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'backend/tools'))
from controller import atomic_json,prerequisite_pass,qualify_burst
class ControllerTests(unittest.TestCase):
    def test_failed_or_unqualified_dependency_blocks(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t);r=p/'results'/'a';r.mkdir(parents=True)
            self.assertFalse(prerequisite_pass(p,['a']))
            for record in [{'returncode':0},{'returncode':1,'qualification':{'status':'PASS'}},
                           {'returncode':0,'qualification':{'status':'FAIL'}}]:
                atomic_json(r/'FINISHED.json',record)
                self.assertFalse(prerequisite_pass(p,['a']))
            atomic_json(r/'FINISHED.json',{'returncode':0,'qualification':{'status':'PASS'}})
            self.assertTrue(prerequisite_pass(p,['a']))
            with self.assertRaises(ValueError):prerequisite_pass(p,['../escape'])
    def test_burst_requires_every_rank_and_exact_completion(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t)
            for node in range(2):
                p=root/'dynamic'/('node%d'%node);p.mkdir(parents=True)
                (p/'status.tsv').write_text(''.join('%d\t0\n'%g for g in range(4)))
                for g in range(4):
                    a={'rank':node*4+g,'cases':4,'errors':0,'diagnostic':0,'posted':16396,'completed':16396}
                    (p/('gpu%d.log'%g)).write_text(json.dumps(a)+'\n'+json.dumps({'rc':0,'is_nccl_gin':False})+'\n')
            self.assertEqual(qualify_burst(root)['status'],'PASS')
            f=root/'dynamic/node1/gpu3.log';s=f.read_text();f.write_text(s.replace('"completed": 16396','"completed": 16395'))
            with self.assertRaises(AssertionError):qualify_burst(root)
if __name__=='__main__':unittest.main()
