"""Copy header contents without replaying source filesystem permissions/ACLs."""
import hashlib
from pathlib import Path
import shutil
import sys

def copy_headers(source, destination):
    source=Path(source).resolve();destination=Path(destination)
    if destination.exists():
        raise ValueError('Destination must be new: '+str(destination))
    destination.mkdir(parents=True)
    count=0
    for path in sorted(source.rglob('*')):
        target=destination/path.relative_to(source)
        if path.is_symlink():
            raise ValueError('Review header symlink before copying: '+str(path))
        if path.is_dir():
            target.mkdir(exist_ok=True)
        elif path.is_file():
            target.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(str(path),str(target))
            assert hashlib.sha256(path.read_bytes()).digest()==hashlib.sha256(target.read_bytes()).digest(),str(path)
            count+=1
    assert count>0,'empty header tree'
    return count

if __name__=='__main__':
    print('Verified header files:',copy_headers(sys.argv[1],sys.argv[2]))
