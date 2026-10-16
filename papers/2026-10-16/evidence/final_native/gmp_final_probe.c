/* Full-width allocator trace and asymmetric multiplication, using the DLL ABI.
 * Run ONLY in a disposable guarded child. This file does not infer header types.
 * Usage: probe.exe <DLL> <a-bits> <b-bits> <square|multiply>
 */
#include <windows.h>
#include <stdint.h>
#include <inttypes.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef struct { int alloc; int size; void *limbs; } Z;
typedef void (__cdecl *init_fn)(Z *);
typedef void (__cdecl *init_ui_fn)(Z *, unsigned long);
typedef void (__cdecl *shift_fn)(Z *, const Z *, unsigned long);
typedef void (__cdecl *mul_fn)(Z *, const Z *, const Z *);
typedef void (__cdecl *clear_fn)(Z *);
typedef size_t (__cdecl *sizebase_fn)(const Z *, int);
typedef void * (__cdecl *alloc_fn)(size_t);
typedef void * (__cdecl *realloc_fn)(void *, size_t, size_t);
typedef void (__cdecl *free_fn)(void *, size_t);
typedef void (__cdecl *getmem_fn)(alloc_fn *, realloc_fn *, free_fn *);
typedef void (__cdecl *setmem_fn)(alloc_fn, realloc_fn, free_fn);
static HMODULE trace_module;
static void dump_stack(void) {
    void *frames[32]; USHORT n=CaptureStackBackTrace(0,32,frames,NULL);
    for(USHORT i=0;i<n;i++) {
        uintptr_t p=(uintptr_t)frames[i],base=(uintptr_t)trace_module;
        if(p>=base && p<base+0x1000000ULL) {
            DWORD64 image=0;PRUNTIME_FUNCTION f=RtlLookupFunctionEntry((DWORD64)p,&image,NULL);
            printf("{\"event\":\"gmp_stack_frame\",\"index\":%u,\"rva\":%llu,\"begin_rva\":%lu}\n",(unsigned)i,(unsigned long long)(p-base),f?f->BeginAddress:0UL);
        }
    }
    fflush(stdout);
}
static alloc_fn old_alloc;
static realloc_fn old_realloc;
static free_fn old_free;

static void trace(const char *kind, size_t size) {
    if (size >= ((size_t)1 << 30)) {
        printf("{\"event\":\"allocation\",\"kind\":\"%s\",\"size_t_bytes\":%" PRIu64
               ",\"signed64\":%" PRId64 ",\"low32\":%" PRIu32 "}\n",
               kind, (uint64_t)size, (int64_t)(uint64_t)size, (uint32_t)size);
        fflush(stdout);
        if(size>((size_t)1<<63)) dump_stack();
    }
}
static void * __cdecl traced_alloc(size_t n) { trace("allocate",n); return old_alloc(n); }
static void * __cdecl traced_realloc(void *p,size_t old,size_t n) { trace("reallocate",n); return old_realloc(p,old,n); }
static void __cdecl traced_free(void *p,size_t n) { old_free(p,n); }

int main(int argc, char **argv) {
    HMODULE lib;
    uint64_t a,b;
    int square;
    Z x,y,z;
    init_fn init; init_ui_fn init_ui; shift_fn shift; mul_fn mul;
    clear_fn clear; sizebase_fn sizebase; getmem_fn getmem; setmem_fn setmem;
    if (argc!=5) return 2;
    a=_strtoui64(argv[2],NULL,10); b=_strtoui64(argv[3],NULL,10);
    square=strcmp(argv[4],"square")==0;
    if(a<2 || b<2 || a>5000000000ULL || b>5000000000ULL || (square && a!=b)) return 2;
    SetErrorMode(SEM_FAILCRITICALERRORS|SEM_NOGPFAULTERRORBOX|SEM_NOOPENFILEERRORBOX);
    setvbuf(stdout,NULL,_IONBF,0);
    lib=LoadLibraryA(argv[1]); if(!lib) {printf("load_error=%lu\n",GetLastError());return 2;}
#define LOAD(v,t,n) v=(t)GetProcAddress(lib,n); if(!v) return 2
    LOAD(init,init_fn,"__gmpz_init"); LOAD(init_ui,init_ui_fn,"__gmpz_init_set_ui");
    LOAD(shift,shift_fn,"__gmpz_mul_2exp"); LOAD(mul,mul_fn,"__gmpz_mul");
    LOAD(clear,clear_fn,"__gmpz_clear"); LOAD(sizebase,sizebase_fn,"__gmpz_sizeinbase");
    LOAD(getmem,getmem_fn,"__gmp_get_memory_functions"); LOAD(setmem,setmem_fn,"__gmp_set_memory_functions");
    getmem(&old_alloc,&old_realloc,&old_free);setmem(traced_alloc,traced_realloc,traced_free);
    trace_module=lib;
    const char *names[]={"__gmpn_mul_fft","__gmp_tmp_reentrant_alloc","__gmpn_mulmod_bnm1","__gmpn_nussbaumer_mul"};
    for(int j=0;j<4;j++)printf("{\"event\":\"symbol\",\"name\":\"%s\",\"rva\":%llu}\n",names[j],(unsigned long long)((uintptr_t)GetProcAddress(lib,names[j])-(uintptr_t)lib));
    init_ui(&x,1);init_ui(&y,1);init(&z);
    {uint64_t left=a-1;while(left){unsigned long k=(unsigned long)(left>2147483647ULL?2147483647ULL:left);shift(&x,&x,k);left-=k;}}
    if(!square){uint64_t left=b-1;while(left){unsigned long k=(unsigned long)(left>2147483647ULL?2147483647ULL:left);shift(&y,&y,k);left-=k;}}
    printf("{\"event\":\"before_mul\",\"a_bits\":%" PRIu64 ",\"b_bits\":%" PRIu64
           ",\"same_pointer\":%s,\"a_limbs\":%d,\"b_limbs\":%d,\"expected_result_bits\":%" PRIu64 "}\n",
           a,b,square?"true":"false",x.size,square?x.size:y.size,a+b-1);
    mul(&z,&x,square?&x:&y);
    printf("{\"event\":\"after_mul\",\"result_limbs\":%d,\"result_bits\":%" PRIu64 "}\n",z.size,(uint64_t)sizebase(&z,2));
    typedef unsigned long (__cdecl *pop_fn)(const Z *);
    pop_fn pop=(pop_fn)GetProcAddress(lib,"__gmpz_popcount");
    unsigned long ones=pop(&z);uint64_t bits=(uint64_t)sizebase(&z,2);
    printf("{\"event\":\"sparse_validation\",\"popcount\":%lu,\"bits\":%llu,\"correct\":%s}\n",ones,(unsigned long long)bits,ones==1 && bits==a+b-1?"true":"false");
    if(ones!=1 || bits!=a+b-1) return 4;
    clear(&z);clear(&y);clear(&x);FreeLibrary(lib);return 0;
}
