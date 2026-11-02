"""Observe mandatory correctness calls without changing GPU/transport sources."""
import argparse,copy,hashlib,json,shutil
from pathlib import Path
from package import ROOT,REMOTE,replace
from package_credit_debug import add_observer

p=argparse.ArgumentParser();p.add_argument('output',type=Path);out=p.parse_args().output.resolve()
parent=ROOT/'results/deepep_pipeline_20261030/source-retire-refresh-v2'
shutil.copytree(parent,out,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
add_observer(out)
shutil.copyfile(Path(__file__).with_name('diagnostic_watch_local.py'),out/'backend/tests/diagnostic_watch.py')
b=out/'backend/tests/ep_benchmark.py'
replace(b,"routing=routing, operation=None)","routing=routing, seed=seed, operation=None)")
replace(b,'    b=Backend(args,n,h,e,k); case.update(actual_sms=b.sms,qps=b.qps)',
'''    diagnostic_watch.mark('buffer_create_enter')
    b=Backend(args,n,h,e,k); case.update(actual_sms=b.sms,qps=b.qps)
    diagnostic_watch.mark('buffer_create_return')''')
replace(b,'    result=b.dispatch(x,idx,w)',
'''    diagnostic_watch.mark('correctness_fresh_enter')
    result=b.dispatch(x,idx,w)
    diagnostic_watch.mark('correctness_fresh_return')''')
replace(b,'    shape=(rx[0] if isinstance(rx,tuple) else rx).shape',
'''    diagnostic_watch.mark('correctness_fresh_validated')
    shape=(rx[0] if isinstance(rx,tuple) else rx).shape''')
replace(b,'        cy,cw,_=b.combine(y,handle,rw)',
'''        diagnostic_watch.mark('correctness_combine_enter', floating=floating)
        cy,cw,_=b.combine(y,handle,rw)
        diagnostic_watch.mark('correctness_combine_return', floating=floating)''')
replace(b,'    cached=b.dispatch(x,idx,w,handle)',
'''    diagnostic_watch.mark('correctness_combines_validated')
    diagnostic_watch.mark('correctness_cached_enter')
    cached=b.dispatch(x,idx,w,handle)
    diagnostic_watch.mark('correctness_cached_return')''')
replace(b,"    case['progress_update_interval']=",
"    diagnostic_watch.mark('correctness_cached_validated')\n    case['progress_update_interval']=")
replace(b,'    torch.cuda.synchronize(); dist.barrier(); b.buf.destroy()',
'''    diagnostic_watch.mark('buffer_destroy_sync_enter')
    torch.cuda.synchronize(); dist.barrier()
    diagnostic_watch.mark('buffer_destroy_enter')
    b.buf.destroy()
    diagnostic_watch.mark('buffer_destroy_return')''')
seq=[]
original=next(s for s in json.loads((parent/'sequence.json').read_text()) if s['name'].endswith('-ep-correctness'))
for number,variant in [(2200,'marker-zero'),(2201,'marker-control')]:
 s=copy.deepcopy(original);s.update(name='%d-%s-first257-diagnostic'%(number,variant),snapshot=REMOTE+'/sources/'+out.name,timeout_seconds=900)
 s['environment'].update(CXI_VARIANT=variant,CXI_DIAGNOSTIC_WATCHDOG='1',CXI_REQUIRE_REUSE='0',CXI_EP_TOKENS='257',CXI_EP_DTYPES='fp8',CXI_EP_ROUTING='mixed',CXI_EP_SEEDS='1',CXI_EP_WARMUP='20',CXI_EP_ITERS='100',CXI_TEST_TIMEOUT='840')
 s['requires']=['1803-retire-refresh-tiny-stress']
 seq.append(s)
(out/'sequence.json').write_text(json.dumps(seq,indent=2)+'\n')
old=json.loads((parent/'manifest.json').read_text());new={str(p.relative_to(out)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(out.rglob('*')) if p.is_file() and p.name!='manifest.json'}
assert set(new)-set(old['files'])=={'backend/tests/diagnostic_watch.py'}
assert {k for k in old['files'] if old['files'][k]!=new[k]}=={'backend/tests/ep_benchmark.py','runner/validate_gate.py','sequence.json'}
old.update(files=new,source_parent=str(parent),scope='Host tmpfs first-call phase journal only; GPU/host transport/ABI/DeepEP/runtime unchanged; diagnostic timing excluded from performance')
(out/'manifest.json').write_text(json.dumps(old,indent=2)+'\n')
for f in [b,out/'backend/tests/diagnostic_watch.py',out/'runner/validate_gate.py']:compile(f.read_text(),str(f),'exec')
print('PASS diagnostic-only source delta; no GPU execution')
