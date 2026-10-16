"""Build and serially run sparse/asymmetric native C probes with memory guards."""
from pathlib import Path
import argparse
import hashlib
import json
import subprocess
import time
import psutil

ROOT=Path(__file__).resolve().parent
OUT=ROOT/'experiments_20261016'/'followup'
VC=Path(r'C:\Program Files (x86)\Microsoft Visual Studio\2019\BuildTools\VC\Auxiliary\Build\vcvars64.bat')
DLLS={
 'wheel231':Path(r'C:\Users\lusun\AppData\Roaming\Python\Python313\site-packages\gmpy2.libs\libgmp-10.dll'),
 'wheel221':ROOT/'experiments_20261015'/'isolated_gmpy2_221'/'gmpy2.libs'/'libgmp-10.dll',
 'msys2':OUT/'msys2'/'unpacked'/'mingw64'/'bin'/'libgmp-10.dll',
}
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def build():
    dest=OUT/'build';dest.mkdir(parents=True,exist_ok=True)
    exe=dest/'gmp_boundary_followup.exe'
    header=OUT/'msys2'/'unpacked'/'mingw64'/'include'
    commands=['@echo off',f'call "{VC}" >nul',
      f'cl /nologo /utf-8 /O2 /W4 /Fo"{dest / "probe.obj"}" "{ROOT / "gmp_boundary_followup.c"}" /link /OUT:"{exe}"',
      'if errorlevel 1 exit /b 1',
      f'cl /nologo /utf-8 /O2 /W4 /I"{header}" /Fo"{dest / "widths.obj"}" "{ROOT / "gmp_header_widths.c"}" /link /OUT:"{dest / "gmp_header_widths.exe"}"']
    batch=dest/'build.cmd';batch.write_bytes(('\r\n'.join(commands)+'\r\n').encode('utf-8'))
    raw=batch.read_bytes();assert raw.count(b'\n')==raw.count(b'\r\n') and not raw.startswith(b'\xef\xbb\xbf')
    p=subprocess.run(['cmd','/d','/c',str(batch)],cwd=dest,capture_output=True,timeout=120)
    (dest/'build_stdout.txt').write_bytes(p.stdout);(dest/'build_stderr.txt').write_bytes(p.stderr)
    if p.returncode:raise RuntimeError(p.stdout.decode(errors='replace'))
    widths=subprocess.run([str(dest/'gmp_header_widths.exe')],capture_output=True,text=True,check=True)
    metadata={'header':str(header/'gmp.h'),'header_sha256':sha(header/'gmp.h'),
      'widths':json.loads(widths.stdout),'probe_sha256':sha(exe),'source_sha256':sha(ROOT/'gmp_boundary_followup.c'),
      'dlls':{k:{'path':str(v),'sha256':sha(v)} for k,v in DLLS.items()}}
    (OUT/'build_manifest.json').write_text(json.dumps(metadata,indent=2),encoding='utf-8')
    print('BUILD',json.dumps(metadata),flush=True)
    return exe
def case(exe,label,a,b,mode):
    dest=OUT/'cases'/f'{label}_{mode}_{a}_{b}';dest.mkdir(parents=True,exist_ok=False)
    start=time.perf_counter();guard=None;peak=0;minimum=psutil.virtual_memory().available
    with (dest/'stdout.jsonl').open('wb') as out,(dest/'stderr.txt').open('wb') as err:
      p=subprocess.Popen([str(exe),str(DLLS[label]),str(a),str(b),mode],stdout=out,stderr=err,creationflags=subprocess.CREATE_NO_WINDOW)
      process=psutil.Process(p.pid)
      while p.poll() is None:
        try:
          peak=max(peak,process.memory_info().rss);available=psutil.virtual_memory().available;minimum=min(minimum,available)
          if available<6*(1<<30):guard='available_below_6_GiB';p.kill()
          elif time.perf_counter()-start>120:guard='timeout_120_s';p.kill()
        except (psutil.NoSuchProcess,psutil.AccessDenied):pass
        time.sleep(.05)
      code=p.wait()
    lines=(dest/'stdout.jsonl').read_text(errors='replace').splitlines()
    events=[json.loads(x) for x in lines if x.startswith('{')]
    wrapped=[e for e in events if e.get('event')=='allocation' and e['size_t_bytes']>1<<63]
    result={'dll_label':label,'a_bits':a,'b_bits':b,'mode':mode,'exit_code':code,'guard':guard,
      'elapsed_s':time.perf_counter()-start,'peak_wset_bytes':peak,'min_available_bytes':minimum,
      'events':events,'wrapped_requests':wrapped,'stderr':(dest/'stderr.txt').read_text(errors='replace')}
    (dest/'result.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print('CASE',json.dumps(result),flush=True)
    if guard:raise RuntimeError(guard)
    return result
def main():
    p=argparse.ArgumentParser();p.add_argument('--phase',choices=['square','asymmetric','discriminate'],default='square');args=p.parse_args()
    exe=build() if args.phase=='square' else OUT/'build'/'gmp_boundary_followup.exe'
    B=2147352576;results=[]
    if args.phase=='square':
      for label in DLLS:
        for b in [1000,B,B+1]:results.append(case(exe,label,b,b,'square'))
      for delta in [2,64,65,4096,131072,629615078]:
        b=B+delta;results.append(case(exe,'wheel231',b,b,'square'))
    elif args.phase=='asymmetric':
      for label in DLLS:
        for a,b in [(B-1,B),(B,B+1),(B+1,B+2),(B-64,B+65),(B-64,B+64),(B+64,B+64)]:
          results.append(case(exe,label,a,b,'multiply'))
    else:
      for label in DLLS:
        for a,b in [(B-63,B+1),(B-64,B+2)]:
          results.append(case(exe,label,a,b,'multiply'))
    (OUT/f'{args.phase}_summary.json').write_text(json.dumps(results,indent=2),encoding='utf-8')
if __name__=='__main__':main()
