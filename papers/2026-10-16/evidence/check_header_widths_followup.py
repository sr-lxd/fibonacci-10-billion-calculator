from pathlib import Path
import hashlib
import json
import subprocess

ROOT=Path(__file__).resolve().parent
OUT=ROOT/'experiments_20261016'/'followup'/'header_types'
VC=Path(r'C:\Program Files (x86)\Microsoft Visual Studio\2019\BuildTools\VC\Auxiliary\Build\vcvars64.bat')
HEADERS={'msys2':ROOT/'experiments_20261016'/'followup'/'msys2'/'unpacked'/'mingw64'/'include'/'gmp.h',
         'mpir':Path(r'C:\Users\lusun\mpir-win-src\mpir.h')}
OUT.mkdir(parents=True,exist_ok=True)
results={}
for label,header in HEADERS.items():
    exe=OUT/(label+'_types.exe')
    option='/DPROBE_MPIR' if label=='mpir' else ''
    command=(f'@echo off\r\ncall "{VC}" >nul\r\ncl /nologo /utf-8 /O2 /W4 {option} /I"{header.parent}" '
             f'/Fo"{OUT/(label+".obj")}" "{ROOT/"gmp_header_widths.c"}" /link /OUT:"{exe}"\r\n')
    batch=OUT/(label+'_build.cmd');batch.write_bytes(command.encode('utf-8'))
    raw=batch.read_bytes();assert raw.count(b'\n')==raw.count(b'\r\n') and not raw.startswith(b'\xef\xbb\xbf')
    build=subprocess.run(['cmd','/d','/c',str(batch)],cwd=OUT,capture_output=True,check=True)
    (OUT/(label+'_build.txt')).write_bytes(build.stdout+build.stderr)
    run=subprocess.run([str(exe)],capture_output=True,text=True,check=True)
    results[label]={'header_sha256':hashlib.sha256(header.read_bytes()).hexdigest(),
                   'source_sha256':hashlib.sha256((ROOT/'gmp_header_widths.c').read_bytes()).hexdigest(),
                   'exe_sha256':hashlib.sha256(exe.read_bytes()).hexdigest(),
                   'widths':json.loads(run.stdout)}
assert results['msys2']['widths']['mp_size_bytes']==4
assert results['msys2']['widths']['mp_bitcnt_bytes']==4
assert results['mpir']['widths']['mp_size_bytes']==8
assert results['mpir']['widths']['mp_bitcnt_bytes']==8
(OUT/'type_widths.json').write_text(json.dumps(results,indent=2),encoding='utf-8')
print(json.dumps(results,indent=2))
