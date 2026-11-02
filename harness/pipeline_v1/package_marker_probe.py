"""Test whether replaying a delivery-marker byte corrupts consumed metadata."""
import argparse,hashlib,json,shutil
from pathlib import Path
from package import ROOT,REMOTE,replace

p=argparse.ArgumentParser();p.add_argument('output',type=Path);p.add_argument('--gate-base',type=int,default=1120);args=p.parse_args();out=args.output.resolve()
base=ROOT/'results/deepep_pipeline_20261030/source-hw-fence-v3'
shutil.copytree(base,out,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
primitive=out/'backend/device/cxi_primitives.cuh'
replace(primitive,'namespace cxi_gin {','#ifndef CXI_ZERO_DELIVERY_MARKER\n#define CXI_ZERO_DELIVERY_MARKER 0\n#endif\nnamespace cxi_gin {')
replace(primitive,'  cmd->request_len=1;','  cmd->request_len=CXI_ZERO_DELIVERY_MARKER?0:1;')
variants={}
for name,batch,zero in [('marker-control',0,0),('marker-replay',1,0),('marker-zero',1,1)]:
 variants[name]=dict(CXI_HW_SIGNAL_FENCE=1,CXI_BATCH_DELIVERY=batch,CXI_ZERO_DELIVERY_MARKER=zero,CXI_CT_THRESHOLD_FLUSH=1,CXI_TX_BATCH_LIMIT=8)
(out/'variants.json').write_text(json.dumps(variants,indent=2)+'\n')
smoke=out/'backend/tests/gin_smoke.cu'
probe=Path(__file__).with_name('marker_mutation_probe.cuh').read_text()
replace(smoke,'static void ck(int rc,const char* op)',probe+'\nstatic void ck(int rc,const char* op)')
replace(smoke,'int* self_results=nullptr;','int* self_results=nullptr;MutationResult* mutation=nullptr;')
replace(smoke,'  }catch(const std::exception& e){fprintf(stderr,"GIN smoke:', '''    if(getenv("CXI_MUTATION_EXPECT") && result==0) {
      if(contexts<2)throw std::runtime_error("mutation probe needs separate data/handshake contexts");
      bool clobber=std::string(getenv("CXI_MUTATION_EXPECT"))=="clobber";
      if(!clobber && std::string(getenv("CXI_MUTATION_EXPECT"))!="preserve")throw std::runtime_error("invalid mutation expectation");
      CK(ncclAllReduce(dr,dr,1,ncclInt,ncclSum,comm,0));CK(cudaDeviceSynchronize());
      reset_smoke<<<contexts,1>>>(dev,dw);CK(cudaGetLastError());CK(cudaDeviceSynchronize());
      CK(ncclAllReduce(dr,dr,1,ncclInt,ncclSum,comm,0));CK(cudaDeviceSynchronize());
      CK(cudaMalloc(&mutation,sizeof(MutationResult)));CK(cudaMemset(mutation,0,sizeof(MutationResult)));
      mutation_probe<<<1,1>>>(dev,sw,dw,src,dst,100,clobber,mutation);CK(cudaGetLastError());CK(cudaDeviceSynchronize());
      MutationResult r{};CK(cudaMemcpy(&r,mutation,sizeof(r),cudaMemcpyDeviceToHost));
      if(r.errors || r.rounds!=100)result=1;
      fprintf(f,"{\\"mutation_probe\\":true,\\"expect_clobber\\":%s,\\"rounds\\":%u,\\"errors\\":%u,\\"stage\\":%u,\\"observed\\":%u,\\"expected\\":%u}\\n",clobber?"true":"false",r.rounds,r.errors,r.stage,r.observed,r.expected);
    }
  }catch(const std::exception& e){fprintf(stderr,"GIN smoke:''')
replace(smoke,'  if(src && ncclMemFree(src)!=ncclSuccess)result=1;','  if(mutation && cudaFree(mutation)!=cudaSuccess)result=1;\n  if(src && ncclMemFree(src)!=ncclSuccess)result=1;')
validator=out/'runner/validate_gate.py'
replace(validator,'                contexts = dimensions[cycle]', '''                if env.get('CXI_MUTATION_EXPECT'):
                    probes=[r for r in rows if r.get('mutation_probe')]
                    expected=env['CXI_MUTATION_EXPECT']=='clobber'
                    require(len(probes)==1 and probes[0].get('expect_clobber')==expected and
                            probes[0].get('rounds')==100 and probes[0].get('errors')==0 and
                            probes[0].get('observed')==(0xff000000 if expected else 0),
                            'receiver-mutation diagnostic failed')
                contexts = dimensions[cycle]''')
replace(validator, "normal = [r for r in rows if 'rounds' in r and 'reset_epoch' not in r]", "normal = [r for r in rows if 'context' in r and 'rounds' in r and 'reset_epoch' not in r]")
seq=[]
old=json.loads((base/'sequence.json').read_text())
for i,name in enumerate(variants):
 x=json.loads(json.dumps(next(x for x in old if x['name']=='404-fence-dc-gin')));x.update(name='%d-%s-notification-probe'%(args.gate_base+i,name),snapshot=REMOTE+'/sources/'+out.name,timeout_seconds=600)
 x['requires']=['407-fence-dc-ep-correctness']
 x['environment'].update(CXI_VARIANT=name,CXI_SMOKE_CONTEXTS='2',CXI_SMOKE_ROUNDS='14',CXI_TEST_TIMEOUT='540',CXI_MUTATION_EXPECT='clobber' if name=='marker-replay' else 'preserve')
 for key in ['CXI_SMOKE_RESET','CXI_SMOKE_SELF','CXI_SMOKE_NEGATIVE']:x['environment'].pop(key,None)
 if i:x['requires'].append(seq[-1]['name'])
 assert x['qualification']=='gin' and x['environment']['CXI_TEST_KIND']=='smoke'
 seq.append(x)
(out/'sequence.json').write_text(json.dumps(seq,indent=2)+'\n')
preflight=out/'runner/preflight.sh'
t=preflight.read_text().replace('for variant in fence-control fence-dc fence-batched; do','for variant in marker-control marker-replay marker-zero; do')
# Compile raw wrap under both marker definitions, too.
t=t.replace('for hw_fence in 0 1; do','for hw_fence in 0 1; do\nfor zero in 0 1; do').replace('-DCXI_HW_SIGNAL_FENCE="$hw_fence"','-DCXI_ZERO_DELIVERY_MARKER="$zero" -DCXI_HW_SIGNAL_FENCE="$hw_fence"').replace('burst-$limit-fence$hw_fence.o','burst-$limit-fence$hw_fence-zero$zero.o').replace('date -Is > "$out/PASS"','done\ndate -Is > "$out/PASS"')
preflight.write_text(t)
m=json.loads((base/'manifest.json').read_text());m.update(scope='Diagnostic receiver-mutation reproduction and zero-byte DC marker experiment; no performance claim',source_parent=str(base))
m['files']={str(p.relative_to(out)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(out.rglob('*')) if p.is_file() and p.name!='manifest.json'}
(out/'manifest.json').write_text(json.dumps(m,indent=2)+'\n');print(out)
