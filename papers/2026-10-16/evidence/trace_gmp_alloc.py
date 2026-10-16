"""Observe documented GMP allocation API before importing gmpy2.

This separate diagnostic keeps the original allocators and delegates unchanged.
It is never used to report uninstrumented performance measurements.
"""
from __future__ import annotations
import ctypes,hashlib,json,os,time
from pathlib import Path

KEEP=[]
STATE={}
def install(case):
    package=Path(os.environ.get('FIB_GMP_PACKAGE',Path.home()/'AppData/Roaming/Python/Python313/site-packages'))
    libs=package/'gmpy2.libs'
    KEEP.append(os.add_dll_directory(str(libs)))
    dllpath=libs/'libgmp-10.dll'
    dll=ctypes.CDLL(str(dllpath));KEEP.append(dll)
    alloc_type=ctypes.CFUNCTYPE(ctypes.c_void_p,ctypes.c_size_t)
    realloc_type=ctypes.CFUNCTYPE(ctypes.c_void_p,ctypes.c_void_p,ctypes.c_size_t,ctypes.c_size_t)
    free_type=ctypes.CFUNCTYPE(None,ctypes.c_void_p,ctypes.c_size_t)
    olda,oldr,oldf=ctypes.c_void_p(),ctypes.c_void_p(),ctypes.c_void_p()
    get=dll.__gmp_get_memory_functions
    get.argtypes=[ctypes.POINTER(ctypes.c_void_p)]*3
    get(ctypes.byref(olda),ctypes.byref(oldr),ctypes.byref(oldf))
    a,r,f=alloc_type(olda.value),realloc_type(oldr.value),free_type(oldf.value)
    fp=(case/'allocation_trace.jsonl').open('w',buffering=1,encoding='utf-8');KEEP.append(fp)
    fp.write(json.dumps(dict(event='allocator_install',dll=str(dllpath),dll_sha256=hashlib.sha256(dllpath.read_bytes()).hexdigest(),old_allocate=olda.value,old_reallocate=oldr.value,size_t_bits=ctypes.sizeof(ctypes.c_size_t)*8))+'\n')
    def event(kind,size,old=None):
        if size>=2**30:
            fp.write(json.dumps(dict(time=time.time(),kind=kind,size_t_bytes=size,old_size=old,size_mod_2pow32=size%(2**32)))+'\n')
            fp.flush();os.fsync(fp.fileno())
    @alloc_type
    def alloc(size):event('allocate',size);return a(size)
    @realloc_type
    def realloc(ptr,old,new):event('reallocate',new,old);return r(ptr,old,new)
    @free_type
    def free(ptr,size):f(ptr,size)
    KEEP.extend([alloc,realloc,free,a,r,f])
    setter=dll.__gmp_set_memory_functions
    setter.argtypes=[alloc_type,realloc_type,free_type]
    setter(alloc,realloc,free)
    STATE.update(dll=dll,file=fp,expected=[ctypes.cast(cb,ctypes.c_void_p).value for cb in [alloc,realloc,free]])

def verify_after_import():
    addresses=[ctypes.c_void_p() for _ in range(3)]
    STATE['dll'].__gmp_get_memory_functions(*(ctypes.byref(v) for v in addresses))
    observed=[v.value for v in addresses]
    active=observed==STATE['expected']
    STATE['file'].write(json.dumps(dict(event='allocator_after_gmpy2_import',callbacks_still_active=active,observed=observed,expected=STATE['expected']))+'\n')
    STATE['file'].flush();os.fsync(STATE['file'].fileno())
    if not active:raise RuntimeError('gmpy2 replaced the diagnostic allocator callbacks during import; do not interpret an empty trace as allocation evidence')
