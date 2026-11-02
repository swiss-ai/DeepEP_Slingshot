"""Reconstruct the pinned private checkout, instrument a copy, and seal inputs."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
from prepare import prepare

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
def main():
    p=argparse.ArgumentParser();p.add_argument('output',type=Path);a=p.parse_args();out=a.output.resolve()
    assert not out.exists();out.mkdir(parents=True)
    repo=ROOT/'DeepEP-cxi-dev';commit=subprocess.check_output(['git','-C',str(repo),'rev-parse','HEAD'],text=True).strip();assert commit.startswith('bd1e1669')
    subprocess.run(['git','-C',str(repo),'diff','--check'],check=True)
    shutil.copytree(ROOT/'backend',out/'backend',ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    shutil.copytree(HERE,out/'trace',ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    (out/'trace/nvcc_wrapper.py').chmod(0o755)
    with tempfile.TemporaryDirectory() as t:
        source=Path(t)/'source';source.mkdir();archive=Path(t)/'base.tar'
        subprocess.run(['git','-C',str(repo),'archive','--output='+str(archive),'HEAD'],check=True)
        with tarfile.open(archive) as f:f.extractall(source)
        patch=subprocess.check_output(['git','-C',str(repo),'diff','--binary','HEAD'])
        (out/'base-private.patch').write_bytes(patch)
        subprocess.run(['git','apply',str(out/'base-private.patch')],cwd=source,check=True)
        new=subprocess.check_output(['git','-C',str(repo),'ls-files','--others','--exclude-standard','-z']).decode().split('\0')
        for name in filter(None,new):
            src=repo/name;dst=source/name;assert src.is_file() and not src.is_symlink();dst.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(src,dst)
        fmt=ROOT.parents[1]/'results/deepep_direct_10_26/source-bundles/20261027-complete-rebuild-inputs/fmt-base.tar'
        assert hashlib.sha256(fmt.read_bytes()).hexdigest()=='eddee710df7126bb543e97c84d726030ed097202c78bccf3310c796d2646a89f'
        (source/'third-party/fmt').mkdir(parents=True,exist_ok=True)
        with tarfile.open(fmt) as f:f.extractall(source/'third-party/fmt')
        headers=out/'trace-headers';headers.mkdir()
        for n in ['cxi_primitives.cuh','gin_cxi.cuh']:shutil.copyfile(ROOT/'backend/device'/n,headers/n)
        prepare(source,headers)
        with tarfile.open(out/'DeepEP-instrumented.tar.gz','w:gz') as f:f.add(source,arcname='.')
    manifest={'baseline':commit,'mode':'private tracing copy; baseline transport ordering unchanged',
              'files':{str(p.relative_to(out)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(out.rglob('*')) if p.is_file()}}
    (out/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print(out)
if __name__=='__main__':main()
