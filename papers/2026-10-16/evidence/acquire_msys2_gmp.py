"""Acquire a hash-checked MSYS2 GMP package without installing it globally."""
from pathlib import Path, PurePosixPath
import hashlib
import io
import json
import tarfile
import requests
import zstandard

ROOT = Path(__file__).resolve().parent / "experiments_20261016" / "followup" / "msys2"
URL = "https://mirror.msys2.org/mingw/mingw64/mingw-w64-x86_64-gmp-6.3.0-2-any.pkg.tar.zst"
EXPECTED = "8924433974c4add46cb46ea4f6ef283b5c5139d3f552375115b5580f855015cc"
ROOT.mkdir(parents=True, exist_ok=True)
archive = ROOT / URL.rsplit("/", 1)[-1]
response = requests.get(URL, timeout=60)
response.raise_for_status()
raw = response.content
assert hashlib.sha256(raw).hexdigest() == EXPECTED
archive.write_bytes(raw)
decoded = zstandard.ZstdDecompressor().stream_reader(io.BytesIO(raw))
files = []
with tarfile.open(fileobj=decoded, mode="r|") as bundle:
    for member in bundle:
        rel = PurePosixPath(member.name)
        if rel.is_absolute() or ".." in rel.parts or not member.isfile():
            continue
        dest = ROOT / "unpacked" / str(rel)
        dest.parent.mkdir(parents=True, exist_ok=True)
        content = bundle.extractfile(member).read()
        dest.write_bytes(content)
        files.append({"path": rel.as_posix(), "sha256": hashlib.sha256(content).hexdigest(), "bytes": len(content)})
(ROOT / "provenance.json").write_text(json.dumps({"url": URL, "sha256": EXPECTED,
    "package_page": "https://packages.msys2.org/packages/mingw-w64-x86_64-gmp", "files": files}, indent=2), encoding="utf-8")
print(json.dumps([f for f in files if f["path"].endswith(("libgmp-10.dll", "gmp.h", ".BUILDINFO", ".PKGINFO"))], indent=2))
