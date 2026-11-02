import hashlib,json,sys
from pathlib import Path
def verify(root, name):
    root=Path(root)
    m=json.loads((root/name).read_text())
    for rel,digest in m['files'].items():
        p=(root/rel).resolve()
        assert p.is_relative_to(root.resolve()), rel
        assert hashlib.sha256(p.read_bytes()).hexdigest()==digest, str(p)
    print('manifest PASS',root,len(m['files']))
if __name__=='__main__':
    verify(sys.argv[1],'manifest.json')
    verify(sys.argv[2],'runtime-manifest.json')
