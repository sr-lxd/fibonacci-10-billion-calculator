"""Capture allocator stack; test one positive-wrap point in guarded children."""
from pathlib import Path
import json,subprocess,hashlib,sys
import run_boundary_followup as base
ROOT=Path(__file__).resolve().parent
OUT=ROOT/'experiments_20261016'/'final_native'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def build():
    OUT.mkdir(exist_ok=True)
    s=(ROOT/'gmp_boundary_followup.c').read_text(encoding='utf-8')
    s=s.replace('static alloc_fn old_alloc;', '''static HMODULE trace_module;
static void dump_stack(void) {
    CONTEXT c; RtlCaptureContext(&c);
    for(int step=0;step<32 && c.Rip;step++) {
        DWORD64 image=0,frame=0;void *data=NULL;
        PRUNTIME_FUNCTION fn=RtlLookupFunctionEntry(c.Rip,&image,NULL);
        if(image==(DWORD64)(uintptr_t)trace_module && fn && fn->BeginAddress==0x40130) {
            printf("{\\"event\\":\\"fft_unwound_registers\\",\\"rip_rva\\":%llu,\\"pl_r12d\\":%d,\\"nprime_r13d\\":%d,\\"Nprime_ebx\\":%d,\\"k_esi\\":%d}\\n",(unsigned long long)(c.Rip-image),(int)c.R12,(int)c.R13,(int)c.Rbx,(int)c.Rsi);
        }
        if(fn)RtlVirtualUnwind(UNW_FLAG_NHANDLER,image,c.Rip,fn,&c,&data,&frame,NULL);
        else{c.Rip=*(DWORD64 *)(uintptr_t)c.Rsp;c.Rsp+=8;}
    }
    void *frames[32]; USHORT n=CaptureStackBackTrace(0,32,frames,NULL);
    for(USHORT i=0;i<n;i++) {
        uintptr_t p=(uintptr_t)frames[i],base=(uintptr_t)trace_module;
        if(p>=base && p<base+0x1000000ULL) {
            DWORD64 image=0;PRUNTIME_FUNCTION f=RtlLookupFunctionEntry((DWORD64)p,&image,NULL);
            printf("{\\"event\\":\\"gmp_stack_frame\\",\\"index\\":%u,\\"rva\\":%llu,\\"begin_rva\\":%lu}\\n",(unsigned)i,(unsigned long long)(p-base),f?f->BeginAddress:0UL);
        }
    }
    fflush(stdout);
}
static alloc_fn old_alloc;''')
    s=s.replace('        fflush(stdout);\n    }','        fflush(stdout);\n        if(size>((size_t)1<<63)) dump_stack();\n    }')
    s=s.replace('a>3000000000ULL || b>3000000000ULL','a>5000000000ULL || b>5000000000ULL')
    s=s.replace('    init_ui(&x,1);', '''    trace_module=lib;
    const char *names[]={"__gmpn_mul_fft","__gmp_tmp_reentrant_alloc","__gmpn_mulmod_bnm1","__gmpn_nussbaumer_mul"};
    for(int j=0;j<4;j++)printf("{\\"event\\":\\"symbol\\",\\"name\\":\\"%s\\",\\"rva\\":%llu}\\n",names[j],(unsigned long long)((uintptr_t)GetProcAddress(lib,names[j])-(uintptr_t)lib));
    init_ui(&x,1);''')
    s=s.replace('    shift(&x,&x,(unsigned long)(a-1));\n    if(!square) shift(&y,&y,(unsigned long)(b-1));', '''    {uint64_t left=a-1;while(left){unsigned long k=(unsigned long)(left>2147483647ULL?2147483647ULL:left);shift(&x,&x,k);left-=k;}}
    if(!square){uint64_t left=b-1;while(left){unsigned long k=(unsigned long)(left>2147483647ULL?2147483647ULL:left);shift(&y,&y,k);left-=k;}}''')
    s=s.replace('    clear(&z);clear(&y);', '''    typedef unsigned long (__cdecl *pop_fn)(const Z *);
    pop_fn pop=(pop_fn)GetProcAddress(lib,"__gmpz_popcount");
    unsigned long ones=pop(&z);uint64_t bits=(uint64_t)sizebase(&z,2);
    printf("{\\"event\\":\\"sparse_validation\\",\\"popcount\\":%lu,\\"bits\\":%llu,\\"correct\\":%s}\\n",ones,(unsigned long long)bits,ones==1 && bits==a+b-1?"true":"false");
    if(ones!=1 || bits!=a+b-1) return 4;
    clear(&z);clear(&y);''')
    s=s.replace('    {uint64_t left=a-1;while(left)', '''    if(a>3000000000ULL){size_t limbs=(size_t)((a+63)/64);x.limbs=old_realloc(x.limbs,(size_t)x.alloc*8,limbs*8);memset(x.limbs,0,limbs*8);((uint64_t *)x.limbs)[limbs-1]=1ULL<<((a-1)%64);x.alloc=(int)limbs;x.size=(int)limbs;}
    else {uint64_t left=a-1;while(left)''')
    # Raw GMP-allocator construction supplies a valid canonical mpz above the
    # separate public-shift interface failure; only a>b-limit square is used.
    src=OUT/'gmp_final_probe_v2.c';src.write_text(s,encoding='utf-8',newline='\n')
    exe=OUT/'gmp_final_probe_v2.exe';batch=OUT/'build_v2.cmd'
    batch.write_bytes((f'@echo off\r\ncall "{base.VC}" >nul\r\ncl /nologo /utf-8 /O2 /W4 /Fo"{OUT / "probe.obj"}" "{src}" /link /OUT:"{exe}"\r\n').encode('utf-8'))
    raw=batch.read_bytes();assert raw.count(b'\n')==raw.count(b'\r\n') and not raw.startswith(b'\xef\xbb\xbf')
    p=subprocess.run(['cmd','/d','/c',str(batch)],cwd=OUT,capture_output=True,timeout=120)
    (OUT/'build_v2_stdout.txt').write_bytes(p.stdout);(OUT/'build_v2_stderr.txt').write_bytes(p.stderr)
    assert p.returncode==0,p.stdout.decode(errors='replace')
    (OUT/'build_v2_manifest.json').write_text(json.dumps({'source_sha256':sha(src),'exe_sha256':sha(exe),'changes':'stack and nonvolatile-register unwind at abnormal allocation; large sparse mpz created with GMP allocator and explicit canonical limbs after public-shift construction failed before multiplication; popcount/size verification if multiplication returns'},indent=2),encoding='utf-8')
    return exe
def main():
    exe=build();base.OUT=OUT
    plan={'cases':[[1000,1000,'square'],[2147352577,2147352577,'square'],[4294967297,4294967297,'square']],
          'guards':'existing 120-second timeout and 6GiB available-physical-memory guard','positive_wrap_test':'one sparse square, isolated process; no claim of silent error unless a returned result fails validation'}
    (OUT/'pre_run_plan_v2.json').write_text(json.dumps(plan,indent=2),encoding='utf-8')
    base.DLLS['msys2_v2']=base.DLLS['msys2']
    rows=[base.case(exe,'msys2_v2',a,b,mode) for a,b,mode in plan['cases']]
    (OUT/'summary_v2.json').write_text(json.dumps(rows,indent=2),encoding='utf-8')
    print('FINAL_NATIVE_DONE',[(r['a_bits'],r['exit_code'],r['guard']) for r in rows],flush=True)
if __name__=='__main__':main()
