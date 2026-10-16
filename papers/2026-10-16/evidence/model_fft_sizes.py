"""Query verified MSYS2 internal helpers and model explicit two's-complement wrap.
Not a call-stack trace. C signed overflow itself is undefined by the C standard.
"""
from pathlib import Path
import ctypes,json,hashlib,math
from run_boundary_followup import DLLS
R=Path(__file__).resolve().parent/'experiments_20261016'/'staircase'
def cdiv(a,b):return (abs(a)//abs(b))*(-1 if (a<0)!=(b<0) else 1)
def query(s):
    dll=ctypes.CDLL(str(DLLS['msys2']))
    nxt=dll.__gmpn_mulmod_bnm1_next_size;nxt.argtypes=[ctypes.c_int];nxt.restype=ctypes.c_int
    best=dll.__gmpn_fft_best_k;best.argtypes=[ctypes.c_int,ctypes.c_int];best.restype=ctypes.c_int
    rn=nxt(s);pl=rn//2;k=best(pl,0)
    while pl % (1<<k):k-=1
    N=ctypes.c_int32(pl*64).value;M=N>>k;K=1<<k;maxLK=math.lcm(64,K)
    Nprime=(1+cdiv(2*M+k+2,maxLK))*maxLK;nprime=cdiv(Nprime,64)
    request=(2*(nprime+1)*8+16)%(1<<64)
    return dict(input_limb_sum=s,queried_rn=rn,model_pl=pl,queried_k=k,
                exact_pl_times_64=pl*64,model_N_signed32=N,model_M=M,
                model_Nprime=Nprime,model_nprime=nprime,model_request_signed64=ctypes.c_int64(request).value)
def main():
    sizes=[67104768,67104769,67108864,67108865,67121152,
           67108864+4096*14,67108864+4096*15,67108864+4096*15+1,
           67108864+4096*16,67108864+4096*16+1,
           2*((2776967654+63)//64)]
    rows=[query(s) for s in sizes]
    (R/'source_model.json').write_text(json.dumps({'scope':'MSYS2 helper queries plus source arithmetic model, not internal execution values','signed_overflow':'Explicit two-complement emulation; signed C overflow is undefined behavior','rows':rows},indent=2),encoding='utf-8')
    for r in rows:print(r,flush=True)
if __name__=='__main__':main()
