"""Contemporaneous n=1e9 sink controls; serialize all performance trials."""
from pathlib import Path
import hashlib
import json
import os
import statistics
import subprocess
import time
import psutil

ROOT=Path(__file__).resolve().parent
OUT=ROOT/'experiments_20261016'/'followup'/'storage'
EXE=Path(r'C:\Users\lusun\fibonacci-10-billion-calculator\fib_mpir_v1.1.0.exe')
def wp(p):return '/mnt/'+p.drive[0].lower()+p.as_posix()[2:]
def run(label,rep):
    case=OUT/f'{label}_rep{rep}';case.mkdir(parents=True,exist_ok=False)
    linux=label.startswith('linux')
    if linux:
      dest=f'/tmp/fib_storage_followup_20261016/{label}_rep{rep}' if label=='linux_tmp' else wp(case)
      cmd=['wsl.exe','-d','Ubuntu','--cd','/tmp','--exec','python3',wp(ROOT/'benchmark_linux.py'),
           '--source',wp(ROOT/'experiments_20261015'/'historical_v4_3.py'),
           '--directory',dest,'--algorithm','two_squares','--mode','full','--n','1000000000']
    else:
      cmd=[str(EXE),'1000000000','NUL' if label=='mpir_nul' else str(case/'output.txt')]
    start=time.perf_counter();guard=None;peak=0;minimum=psutil.virtual_memory().available
    with (case/'stdout.txt').open('wb') as stdout,(case/'stderr.txt').open('wb') as stderr:
      p=subprocess.Popen(cmd,stdout=stdout,stderr=stderr,creationflags=subprocess.CREATE_NO_WINDOW)
      proc=psutil.Process(p.pid)
      while p.poll() is None:
        try:
          available=psutil.virtual_memory().available;minimum=min(minimum,available);peak=max(peak,proc.memory_info().rss)
          if not linux and (available<6*(1<<30) or time.perf_counter()-start>600):
            guard='memory_or_timeout';p.kill()
          elif linux and time.perf_counter()-start>600:
            # Request termination only of the exact unique case argument.
            subprocess.run(['wsl.exe','-d','Ubuntu','--exec','pkill','-f',dest],capture_output=True)
            guard='timeout';p.wait(timeout=10)
        except (psutil.NoSuchProcess,psutil.AccessDenied):pass
        time.sleep(.05)
      code=p.wait()
    elapsed=time.perf_counter()-start
    result={'label':label,'rep':rep,'command':cmd,'exit_code':code,'guard':guard,
       'process_wall_s':elapsed,'peak_wset_bytes':peak,'min_available_bytes':minimum}
    if code or guard:raise RuntimeError(result)
    if linux:
      if label=='linux_tmp':
        for name in ['metrics.json','environment.json']:
          content=subprocess.run(['wsl.exe','-d','Ubuntu','--exec','cat',dest+'/'+name],capture_output=True,check=True).stdout
          (case/name).write_bytes(content)
      metrics=json.loads((case/'metrics.json').read_text())
      result.update({k:metrics[k] for k in ['arithmetic_s','conversion_close_s','explicit_fsync_s','sha256']})
    result['exe_sha256']=hashlib.sha256(EXE.read_bytes()).hexdigest() if not linux else None
    (case/'control.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print('DONE',json.dumps(result),flush=True)
    return result
def main():
    OUT.mkdir(parents=True,exist_ok=True)
    (OUT/'protocol.json').write_text(json.dumps({'n':10**9,'repeats':3,
      'windows':psutil.windows_version() if hasattr(psutil,'windows_version') else os.sys.getwindowsversion().build,
      'time':time.strftime('%Y-%m-%d %H:%M:%S %z'),
      'claim':'Sink comparisons within each backend only; no target-scale speedup or medium-durability claim.'},indent=2),encoding='utf-8')
    records=[]
    order=['mpir_file','mpir_nul','linux_tmp','linux_mntc']
    for rep in range(1,4):
      sequence=order if rep%2 else list(reversed(order))
      for label in sequence:records.append(run(label,rep))
    groups={}
    for label in order:
      rows=[r for r in records if r['label']==label]
      groups[label]={'count':len(rows),'process_wall_median_s':statistics.median(r['process_wall_s'] for r in rows)}
      if label.startswith('linux'):
        for field in ['arithmetic_s','conversion_close_s','explicit_fsync_s']:
          groups[label][field+'_median']=statistics.median(r[field] for r in rows)
    (OUT/'summary.json').write_text(json.dumps({'records':records,'groups':groups},indent=2),encoding='utf-8')
    print('SUMMARY',json.dumps(groups),flush=True)
if __name__=='__main__':main()
