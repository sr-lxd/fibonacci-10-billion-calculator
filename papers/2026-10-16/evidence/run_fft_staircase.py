"""Serial guarded DLL tests; FFT helper queries use verified MSYS2 ABI only."""
from pathlib import Path
import ctypes,json,hashlib,math,csv
import run_boundary_followup as base
ROOT=Path(__file__).resolve().parent
OUT=ROOT/'experiments_20261016'/'staircase'
EXE=base.OUT/'build'/'gmp_boundary_followup.exe'
base.OUT=OUT
L=2**26-2**12
# Boundary triplets and one interior point test plateaus, not just increments.
SIZES=[L,L+1,L+2048,2**26-1,2**26,2**26+1,2**26+2048,
       2**26+4096,2**26+4097,2**26+8192,2**26+8193,2**26+12288]

def helpers():
    dll=ctypes.CDLL(str(base.DLLS['msys2']))
    best=dll.__gmpn_fft_best_k;best.argtypes=[ctypes.c_int,ctypes.c_int];best.restype=ctypes.c_int
    nxt=dll.__gmpn_fft_next_size;nxt.argtypes=[ctypes.c_int,ctypes.c_int];nxt.restype=ctypes.c_int
    rows=[]
    for s in SIZES:
        for sqr in [0,1]:
            k=best(s,sqr);rounded=nxt(s,k)
            rows.append(dict(input_limb_sum=s,square_flag=sqr,k=k,next_size=rounded,
                             next_size_bits=rounded*64,as_int32=ctypes.c_int32(rounded*64).value))
    (OUT/'helper_queries.json').write_text(json.dumps(rows,indent=2),encoding='utf-8')
    return rows

def main():
    OUT.mkdir(exist_ok=True)
    plan={'L':L,'sizes':SIZES,'prediction':'un+vn>L fails; signed request plateaus may change after 2^26 limbs; test actual requests before attributing to FFT',
          'probe_sha256':hashlib.sha256(EXE.read_bytes()).hexdigest(),'helper_scope':'MSYS2 matching-header ABI; helper calls are not an internal execution trace'}
    (OUT/'pre_run_plan.json').write_text(json.dumps(plan,indent=2),encoding='utf-8')
    try:helpers()
    except AttributeError as e:(OUT/'helper_queries_error.txt').write_text(str(e),encoding='utf-8')
    rows=[]
    for s in SIZES:
        u=s//2;v=s-u;a=64*(u-1)+1;b=64*(v-1)+1
        dest=OUT/'cases'/f'msys2_multiply_{a}_{b}'/'result.json'
        r=json.loads(dest.read_text()) if dest.exists() else base.case(EXE,'msys2',a,b,'multiply')
        r.update(input_limb_sum=s,request_signed64=r['wrapped_requests'][0]['signed64'] if r['wrapped_requests'] else None)
        rows.append(r)
        (OUT/'staircase_summary.json').write_text(json.dumps(rows,indent=2),encoding='utf-8')
    with (OUT/'staircase.csv').open('w',newline='',encoding='utf-8') as f:
        w=csv.writer(f);w.writerow(['input_limb_sum','a_bits','b_bits','exit_code','guard','signed_request_bytes'])
        for r in rows:w.writerow([r[k] for k in ['input_limb_sum','a_bits','b_bits','exit_code','guard','request_signed64']])
    print('STAIRCASE_COMPLETE',[(r['input_limb_sum'],r['request_signed64']) for r in rows],flush=True)

if __name__=='__main__':main()
