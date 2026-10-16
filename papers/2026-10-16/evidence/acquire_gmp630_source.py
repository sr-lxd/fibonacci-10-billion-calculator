from pathlib import Path
import hashlib,json,tarfile,requests
R=Path(__file__).resolve().parent/'experiments_20261016'/'staircase'
R.mkdir(parents=True,exist_ok=True)
url='https://ftp.gnu.org/gnu/gmp/gmp-6.3.0.tar.xz'
p=R/'gmp-6.3.0.tar.xz'
if not p.exists():
    r=requests.get(url,timeout=90);r.raise_for_status();p.write_bytes(r.content)
h=hashlib.sha256(p.read_bytes()).hexdigest()
assert h=='a3c2b80201b89e68616f4ad30bc66aee4927c3ce50e33929ca819d5c43538898',h
dest=R/'source';dest.mkdir(exist_ok=True)
with tarfile.open(p) as tf:
    for m in tf.getmembers():
        target=(dest/m.name).resolve()
        assert target.is_relative_to(dest.resolve())
    tf.extractall(dest,filter='data')
(R/'source_manifest.json').write_text(json.dumps({'url':url,'sha256':h,'version':'6.3.0','source':'GNU release archive; hash matches MSYS2 PKGBUILD'},indent=2),encoding='utf-8')
print(dest/'gmp-6.3.0')
