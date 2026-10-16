"""Portable model of the observed negative-workspace path (GMP 6.3.0).

python fft_size_model.py 67104769 11
This emulates 32-bit wrap, not C's undefined signed-overflow semantics.
Positive nprime may enter additional recursive rounding, outside this model.
"""
import argparse,json,math
def trunc0(a,b):return (abs(a)//abs(b))*(-1 if (a<0)!=(b<0) else 1)
def model(s,k):
    assert s>0 and 0<k<31
    h=(s+1)>>1
    pl=((h+(1<<k)-1)>>k)<<k
    N=((64*pl+(1<<31))%(1<<32))-(1<<31)
    M=N>>k;W=math.lcm(64,1<<k)
    Nprime=(1+trunc0(2*M+k+2,W))*W
    nprime=trunc0(Nprime,64)
    request=(2*(nprime+1)*8+16)%(1<<64)
    return dict(s=s,k=k,h=h,pl=pl,exact_bits=64*pl,N=N,M=M,W=W,
                Nprime=Nprime,nprime=nprime,negative_path=nprime<0,
                request_u64=request,request_i64=request-(1<<64) if request>=(1<<63) else request)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('s',type=int);p.add_argument('k',type=int);a=p.parse_args()
    print(json.dumps(model(a.s,a.k),indent=2))
