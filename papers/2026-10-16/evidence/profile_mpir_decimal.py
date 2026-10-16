"""QPC decomposition of retained C writer; a new build, not release binary."""
from pathlib import Path
import hashlib,json,subprocess,time,statistics
import psutil
ROOT=Path(__file__).resolve().parent
OUT=ROOT/'experiments_20261016'/'mpir_profile'
SRC=ROOT/'package'/'共同材料'/'fib_mpir_v1_1_0.c'
INC=Path(r'C:\Users\lusun\mpir-win-src')
LIB=INC/'lib'/'x64'/'Release'/'mpir.lib'
VC=Path(r'C:\Program Files (x86)\Microsoft Visual Studio\2019\BuildTools\VC\Auxiliary\Build\vcvars64.bat')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def build():
    OUT.mkdir(exist_ok=True)
    s=SRC.read_text(encoding='utf-8-sig')
    def replace(a,b):
        nonlocal s
        assert s.count(a)==1,(a,s.count(a));s=s.replace(a,b)
    replace('static Pow10Entry *pow10_cache = NULL;', '''static LARGE_INTEGER prof_freq;
static LONGLONG prof_pow=0,prof_div=0,prof_getstr=0,prof_leaf_io=0;
static LONGLONG prof_now(void) {LARGE_INTEGER t;QueryPerformanceCounter(&t);return t.QuadPart;}
static double prof_seconds(LONGLONG t) {return (double)t/(double)prof_freq.QuadPart;}
static Pow10Entry *pow10_cache = NULL;''')
    replace('    mpz_ui_pow_ui(entry->value, 10UL, (unsigned long)exponent);',
            '    {LONGLONG t=prof_now();mpz_ui_pow_ui(entry->value, 10UL, (unsigned long)exponent);prof_pow+=prof_now()-t;}')
    replace('        mpz_get_str(buffer, 10, value);',
            '        {LONGLONG t=prof_now();mpz_get_str(buffer, 10, value);prof_getstr+=prof_now()-t;}')
    replace('        for (size_t i = digits; i < width; ++i) {',
            '        LONGLONG leaf_io_started=prof_now();\n        for (size_t i = digits; i < width; ++i) {')
    replace('        free(buffer);\n        InterlockedExchangeAdd64',
            '        prof_leaf_io+=prof_now()-leaf_io_started;\n        free(buffer);\n        InterlockedExchangeAdd64')
    replace('        mpz_tdiv_qr(high, low, value, divisor);',
            '        {LONGLONG t=prof_now();mpz_tdiv_qr(high, low, value, divisor);prof_div+=prof_now()-t;}')
    replace('    char elapsed[32];\n\n    setvbuf(stdout',
            '    char elapsed[32];\n    LONGLONG arith_start,arith_end,width_start,width_end,writer_start,writer_end,close_start,close_end,pow_at_writer;\n    QueryPerformanceFrequency(&prof_freq);\n\n    setvbuf(stdout')
    replace('    fibonacci_two_squares(n, result);','    arith_start=prof_now();\n    fibonacci_two_squares(n, result);\n    arith_end=prof_now();')
    replace('    digits = mpz_sizeinbase(result, 10);','    width_start=prof_now();\n    digits = mpz_sizeinbase(result, 10);')
    replace('    clear_pow10_cache();\n\n    InterlockedExchange64',
            '    clear_pow10_cache();\n    width_end=prof_now();\n\n    InterlockedExchange64')
    replace('    out = fopen(output_path, "wb");',
            '    writer_start=prof_now();pow_at_writer=prof_pow;\n    out = fopen(output_path, "wb");')
    replace('    if (fclose(out) != 0) {','    close_start=prof_now();\n    if (fclose(out) != 0) {')
    replace('    out = NULL;\n\n    InterlockedExchange(&g_phase',
            '    out = NULL;\n    close_end=prof_now();writer_end=close_end;\n\n    InterlockedExchange(&g_phase')
    fields=['arithmetic','width_correction','writer_total','writer_pow10','writer_division','writer_get_str','writer_padding_fwrite','fclose']
    expr=['arith_end-arith_start','width_end-width_start','writer_end-writer_start','prof_pow-pow_at_writer','prof_div','prof_getstr','prof_leaf_io','close_end-close_start']
    fmt='PROFILE_JSON {\\"n\\":%'+ '" PRIu64 "'+ ''.join(',\\"'+k+'_s\\":%.9f' for k in fields)+'}\\n'
    # Generate normal C adjacent string literals around PRIu64.
    statement='    printf("'+fmt+'", n, '+', '.join('prof_seconds('+e+')' for e in expr)+');\n'
    replace('    exit_code = 0;\n\ncleanup:',statement+'    exit_code = 0;\n\ncleanup:')
    src=OUT/'fib_mpir_profile.c';src.write_text(s,encoding='utf-8',newline='\n')
    exe=OUT/'fib_mpir_profile.exe';bat=OUT/'build.cmd'
    bat.write_bytes((f'@echo off\r\ncall "{VC}" >nul\r\ncl /nologo /utf-8 /O2 /W4 /I"{INC}" /Fo"{OUT / "profile.obj"}" "{src}" /link /OUT:"{exe}" /LIBPATH:"{LIB.parent}" mpir.lib\r\n').encode('utf-8'))
    raw=bat.read_bytes();assert raw.count(b'\n')==raw.count(b'\r\n') and not raw.startswith(b'\xef\xbb\xbf')
    p=subprocess.run(['cmd','/d','/c',str(bat)],cwd=OUT,capture_output=True,timeout=120)
    (OUT/'build_stdout.txt').write_bytes(p.stdout);(OUT/'build_stderr.txt').write_bytes(p.stderr)
    assert p.returncode==0,p.stdout.decode(errors='replace')
    (OUT/'build_manifest.json').write_text(json.dumps({'retained_source_sha256':sha(SRC),'profile_source_sha256':sha(src),'exe_sha256':sha(exe),'static_library_sha256':sha(LIB),'compiler':str(VC),'flags':'/utf-8 /O2 /W4 x64','scope':'new instrumented retained-source build; recurrence, writer operations and leaf size unchanged; not a binary-matched release rebuild'},indent=2),encoding='utf-8')
    return exe
def run(exe,n,rep):
    d=OUT/f'n{n}_rep{rep}';d.mkdir(exist_ok=True)
    if (d/'metrics.json').exists():return json.loads((d/'metrics.json').read_text())
    start=time.perf_counter();peak=0;minimum=psutil.virtual_memory().available;guard=None
    with (d/'stdout.txt').open('wb') as out,(d/'stderr.txt').open('wb') as err:
        p=subprocess.Popen([str(exe),str(n),str(d/'output.txt')],stdout=out,stderr=err,creationflags=subprocess.CREATE_NO_WINDOW)
        pp=psutil.Process(p.pid)
        while p.poll() is None:
            try:
                m=pp.memory_info();peak=max(peak,m.peak_wset);minimum=min(minimum,psutil.virtual_memory().available)
                if minimum<6*2**30:guard='available_below_6GiB';p.kill()
                if time.perf_counter()-start>600:guard='timeout_600s';p.kill()
            except psutil.NoSuchProcess:pass
            time.sleep(.05)
        rc=p.wait()
    wall=time.perf_counter()-start
    assert rc==0 and guard is None,(rc,guard)
    row=json.loads(next(l.removeprefix('PROFILE_JSON ') for l in (d/'stdout.txt').read_text(encoding='utf-8').splitlines() if l.startswith('PROFILE_JSON ')))
    h=hashlib.sha256();count=0;prefix=f'F({n}) = '.encode()
    with (d/'output.txt').open('rb') as f:
        assert f.read(len(prefix))==prefix
        while block:=f.read(2**20):
            block=block.rstrip(b'\r\n');assert block.isdigit();count+=len(block);h.update(block)
    expected='ee790ff513e4d66ccf5e59c355c696a323dfd968e30f63d1466fd2fdf68f270f' if n==10**9 else hashlib.sha256(b'354224848179261915075').hexdigest()
    assert h.hexdigest()==expected
    row.update(rep=rep,process_wall_s=wall,peak_wset_bytes=peak,min_available_bytes=minimum,guard=guard,payload_digits=count,payload_sha256=h.hexdigest())
    row['writer_other_s']=row['writer_total_s']-sum(row[k] for k in ['writer_pow10_s','writer_division_s','writer_get_str_s','writer_padding_fwrite_s','fclose_s'])
    (d/'metrics.json').write_text(json.dumps(row,indent=2),encoding='utf-8')
    print('PROFILE_DONE',json.dumps(row),flush=True);return row
def main():
    exe=build();run(exe,100,1)
    rows=[run(exe,10**9,i) for i in range(1,4)]
    med={k:statistics.median(r[k] for r in rows) for k in rows[0] if k.endswith('_s')}
    (OUT/'summary.json').write_text(json.dumps({'rows':rows,'medians':med,'scope':'sequential QPC trials of new instrumented build; stage medians independently calculated'},indent=2),encoding='utf-8')
    print('PROFILE_SUMMARY',json.dumps(med),flush=True)
if __name__=='__main__':main()
