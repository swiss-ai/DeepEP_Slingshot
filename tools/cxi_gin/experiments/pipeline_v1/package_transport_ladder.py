"""Rebase matched dispatch/combine transport probes onto the qualified backend.

Only the probe/frontend/validator changes. GPU transport and DeepEP are identical
to source-zero-packed-v7. The raw probe has no NVLink relay or expert reduction.
"""
import argparse,hashlib,json,shutil,tarfile
from pathlib import Path
from package import ROOT,HERE,REMOTE,replace

p=argparse.ArgumentParser();p.add_argument('output',type=Path);a=p.parse_args()
base=ROOT/'results/deepep_pipeline_20261030/source-zero-packed-v7'
out=a.output.resolve();assert not out.exists()
shutil.copytree(base,out,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
probe=out/'backend/tests/gin_stage_ladder.cu'
shutil.copyfile(HERE/'gin_stage_ladder.cu',probe)
replace(probe,'constexpr size_t row_bytes=4320;','// Row width is selected by the host and specialized below.')
replace(probe,'__global__ void transfer(', 'template <size_t row_bytes>\n__global__ void transfer(')
replace(probe,'    const bool coalesce=option("CXI_LADDER_COALESCE",0);',
    '    const size_t row_bytes=option("CXI_LADDER_ROW_BYTES",4320);\n'
    '    if(row_bytes!=4320 && row_bytes!=8256)throw std::runtime_error("unsupported row width");\n'
    '    const bool coalesce=option("CXI_LADDER_COALESCE",0);')
replace(probe,'      transfer<<<64,128>>>(dev,sw,dw,contexts,rows,interval,coalesce,iteration,device);',
    '      if(row_bytes==4320)transfer<4320><<<64,128>>>(dev,sw,dw,contexts,rows,interval,coalesce,iteration,device);\n'
    '      else transfer<8256><<<64,128>>>(dev,sw,dw,contexts,rows,interval,coalesce,iteration,device);')
node=out/'backend/tools/direct_node.sh'
replace(node,'  producer) test_source=gin_producer_stress.cu;;',
    '  producer) test_source=gin_producer_stress.cu;;\n  ladder) test_source=gin_stage_ladder.cu;;')
replace(node,'test_args=("$src/tests/gin_smoke.py")', '''if [ "${CXI_TEST_KIND:-smoke}" = ladder ] && [ "${CXI_LOCAL_RESULTS:-0}" = 1 ]; then
  raw_shared_results="$CASE_OUT"
  export CASE_OUT=$(mktemp -d "/dev/shm/deepep-ladder-${SLURM_JOB_ID}-n${SLURM_PROCID}-XXXXXX")
  printf '%s\\n' "$CASE_OUT" > "$base/local-raw-results-path.txt"
fi
test_args=("$src/tests/gin_smoke.py")''')
replace(node,'if [ "$test_rc" != 0 ]; then exit "$test_rc"; fi', '''if [ -n "${raw_shared_results:-}" ]; then
  mkdir -p "$raw_shared_results"
  cp -r --no-preserve=all "$CASE_OUT/." "$raw_shared_results/"
  rm -rf -- "$CASE_OUT"
fi
if [ "$test_rc" != 0 ]; then exit "$test_rc"; fi''')
replace(out/'backend/tests/gin_smoke.py', "    elif kind == 'producer':", """    elif kind == 'ladder':
        function = lib.gin_stage_ladder
        dimensions = os.getenv('CXI_LADDER_CONTEXTS', '129,257')
        rounds = int(os.getenv('CXI_LADDER_ROUNDS', '30'))
        dimension_name = 'contexts'
    elif kind == 'producer':""")
old=(base.parent/'source-ladder-v2/runner/validate_gate.py').read_text()
start=old.index("    if mode == 'ladder':");end=old.index("    if mode == 'gin':",start)
branch=old[start:end]
assert branch.count("r['row_bytes'] == 4320")==1
branch=branch.replace("r['row_bytes'] == 4320", "r['row_bytes'] == int(env['CXI_LADDER_ROW_BYTES'])")
replace(out/'runner/validate_gate.py', "    if mode == 'gin':", branch+"    if mode == 'gin':")
seq=[]
for tokens in [4096,16384]:
 for width in [4320,8256]:
  for mode,coalesce in [('rows-final',0),('coalesced',1)]:
   env=dict(CXI_VARIANT='marker-zero',CXI_TRANSPORT='direct',CXI_TEST_KIND='ladder',
       CXI_TEST_TIMEOUT='840',CXI_QUEUE_INVENTORY='1',CXI_LADDER_ROWS=str(tokens),
       CXI_LADDER_ROW_BYTES=str(width),CXI_LADDER_SIGNAL_INTERVAL='0',
       CXI_LADDER_COALESCE=str(coalesce),CXI_LADDER_CONTEXTS='129,257',CXI_LADDER_ROUNDS='30',
       CXI_LOCAL_JIT='1',CXI_LOCAL_RESULTS='1',CXI_LOCAL_LOGS='1',CXI_DEVICE_TRACE='0',CXI_EP_DEBUG='0')
   seq.append(dict(name='%d-zero-ladder-%dB-%d-%s'%(5200+len(seq),width,tokens,mode),
       snapshot=REMOTE+'/sources/'+out.name,node_script='runner/node.sh',qualification='ladder',
       timeout_seconds=900,environment=env,requires=[]))
(out/'sequence.json').write_text(json.dumps(seq,indent=2)+'\n')
manifest=json.loads((base/'manifest.json').read_text())
after={str(f.relative_to(out)):hashlib.sha256(f.read_bytes()).hexdigest()
       for f in out.rglob('*') if f.is_file() and f.name!='manifest.json'}
changed={k for k in manifest['files'] if after[k]!=manifest['files'][k]}
assert changed=={'backend/tools/direct_node.sh','backend/tests/gin_smoke.py','runner/validate_gate.py','sequence.json'}
assert set(after)-set(manifest['files'])=={'backend/tests/gin_stage_ladder.cu'}
manifest.update(files=after,source_parent=str(base),
    scope='Matched4320/8256-byte public-GIN transport probes; exact unchanged zero-marker transport/DeepEP; local journals; GPU unqualified')
(out/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
with tarfile.open(out.parent/(out.name+'-overlay.tar.gz'),'w:gz') as archive:
 for name in sorted(changed|{'manifest.json','backend/tests/gin_stage_ladder.cu'}):archive.add(out/name,arcname=name)
print(out)
