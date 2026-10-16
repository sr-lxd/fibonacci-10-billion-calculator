"""Same QPC-instrumented C source, matching MSYS2 GMP header/DLL on Windows."""
from pathlib import Path
import subprocess,json,hashlib,re,shutil,statistics
import profile_mpir_decimal as base
ROOT=Path(__file__).resolve().parent
OUT=ROOT/'experiments_20261016'/'windows_gmp_profile'
MSYS=ROOT/'experiments_20261016'/'followup'/'msys2'/'unpacked'/'mingw64'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    OUT.mkdir(exist_ok=True)
    original=ROOT/'experiments_20261016'/'mpir_profile'/'fib_mpir_profile.c'
    text=original.read_text(encoding='utf-8');assert text.count('#include <mpir.h>')==1
    source=OUT/'fib_windows_gmp_profile.c';source.write_text(text.replace('#include <mpir.h>','#include <gmp.h>'),encoding='utf-8',newline='\n')
    api=sorted(set(re.findall(r'\bmpz_([a-z0-9_]+)\s*\(',text)))
    definition=OUT/'gmp.def';definition.write_text('LIBRARY libgmp-10.dll\nEXPORTS\n'+'\n'.join('__gmpz_'+s for s in api)+'\n',encoding='ascii')
    exe=OUT/'fib_windows_gmp_profile.exe';library=OUT/'gmp_import.lib'
    batch=OUT/'build.cmd'
    lines=['@echo off',f'call "{base.VC}" >nul',f'lib /nologo /def:"{definition}" /machine:x64 /out:"{library}"',
           'if errorlevel 1 exit /b 1',f'cl /nologo /utf-8 /O2 /W4 /I"{MSYS / "include"}" /Fo"{OUT / "profile.obj"}" "{source}" /link /OUT:"{exe}" "{library}"']
    batch.write_bytes(('\r\n'.join(lines)+'\r\n').encode('utf-8'))
    raw=batch.read_bytes();assert raw.count(b'\n')==raw.count(b'\r\n') and not raw.startswith(b'\xef\xbb\xbf')
    p=subprocess.run(['cmd','/d','/c',str(batch)],cwd=OUT,capture_output=True,timeout=120)
    (OUT/'build_stdout.txt').write_bytes(p.stdout);(OUT/'build_stderr.txt').write_bytes(p.stderr)
    assert p.returncode==0,p.stdout.decode(errors='replace')
    shutil.copy2(MSYS/'bin'/'libgmp-10.dll',OUT/'libgmp-10.dll')
    (OUT/'build_manifest.json').write_text(json.dumps({'same_code_except_include':source.read_text().replace('#include <gmp.h>','#include <mpir.h>')==text,
      'mpir_profile_source_sha256':sha(original),'gmp_profile_source_sha256':sha(source),'exe_sha256':sha(exe),
      'dll_sha256':sha(OUT/'libgmp-10.dll'),'header_sha256':sha(MSYS/'include'/'gmp.h'),
      'compiler':str(base.VC),'flags':'/utf-8 /O2 /W4 x64; same as MPIR profile','changed_factors':'GMP header and shared DLL replace MPIR header and static library; OS, compiler, C code and output destination retained'},indent=2),encoding='utf-8')
    base.OUT=OUT;base.run(exe,100,1)
    rows=[base.run(exe,10**9,i) for i in range(1,4)]
    med={k:statistics.median(r[k] for r in rows) for k in rows[0] if k.endswith('_s')}
    (OUT/'summary.json').write_text(json.dumps({'rows':rows,'medians':med,'scope':'three serial Windows C/GMP trials; same instrumented C source except header, same compiler and C-drive sink; separate batch'},indent=2),encoding='utf-8')
    print('GMP_PROFILE_SUMMARY',json.dumps(med),flush=True)
if __name__=='__main__':main()
