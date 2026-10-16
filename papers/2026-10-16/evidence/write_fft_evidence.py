from pathlib import Path
import json,hashlib,shutil,zipfile
ROOT=Path(__file__).resolve().parent
R=ROOT/'experiments_20261016'/'staircase'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    first=json.loads((R/'staircase_summary.json').read_text())
    more=json.loads((R/'extension_summary.json').read_text())
    assert len(first)==12 and len(more)==8 and all(r['prediction_matches'] for r in more)
    assert not any(r['guard'] for r in first+more)
    src=R/'source'/'gmp-6.3.0'
    files=['mpn/generic/mul_fft.c','mpn/generic/mulmod_bnm1.c','mpn/generic/nussbaumer_mul.c','gmp-impl.h','tal-reent.c']
    hashes={p:sha(src/p) for p in files}
    (R/'source_files_sha256.json').write_text(json.dumps(hashes,indent=2),encoding='utf-8')
    rows=[]
    for r in first+more:
        rows.append(f'| {r["dll_label"]} | {r["input_limb_sum"]:,} | {r["a_bits"]:,} | {r["b_bits"]:,} | {r["request_signed64"] if r["request_signed64"] is not None else "成功"} |')
    report='''# Windows GMP FFT 阶梯与源码机制实验

2026年10月16日

三份 DLL 在新台阶处的请求变化均符合事先登记的源码模型预测。模型指向 mpn_mul_fft 中的有符号 mp_size_t 位长度计算，并解释了此前两种异常请求。内部栈与寄存器值尚未直接采集。

## 实验过程

先完成12个MSYS2独立进程案例。输入limb之和为67,104,768时成功；其余11个采样点直到67,121,152均请求2^64−523,232字节。超过2^26便立即改变请求值的预测没有成立。

随后校验GNU GMP 6.3.0官方源码包，SHA-256为a3c2b80201b89e68616f4ad30bc66aee4927c3ce50e33929ca819d5c43538898，下载地址 https://ftp.gnu.org/gnu/gmp/gmp-6.3.0.tar.xz 。校验值也与MSYS2官方PKGBUILD一致。源码文件哈希见source_files_sha256.json。

默认gmp-impl.h将mpn_fft_mul映射为mpn_nussbaumer_mul。nussbaumer_mul.c先根据输入总limb数选择rn。mulmod_bnm1_next_size取nh=(s+1)>>1，再调用FFT尺寸辅助函数并将结果乘2。mulmod_bnm1的FFT部分处理n=rn/2。

对实际MSYS2 DLL的辅助函数单独查询：s=67,104,769时rn=67,108,864，pl=33,554,432，k=11。mul_fft.c第926行将N、Nprime、nprime、M等声明为mp_size_t；第937行N = pl * GMP_NUMB_BITS。匹配头文件的mp_size_t实测为有符号32位。pl×64=2^31，按显式补码模拟得到N=−2,147,483,648。

按源码继续计算，M=−1,048,576，Nprime=−2,093,056，nprime=−32,704。第974行的临时limb数2×(nprime+1)为−65,406，乘8后为−523,248。tal-reent.c的分配函数再加16字节头部，最终请求为模2^64意义下的−523,232。原2,776,967,654位平方经同一模型得到−369,632。分配头部的大小来自源码结构与Win64指针/size_t宽度，未通过本次回调直接读出。

模型使用显式32位补码与向零截断除法，避免让Python整数除法负值舍入规则改变结果。C有符号溢出本身未定义，此处模拟的是已观测机器行为。source_model.json保留所有输入、中间值及辅助函数返回值。辅助函数查询不等于运算过程的调用栈，两个证据层分别标注。

## 新预测及验证

extension_predictions.json在8个追加案例开始前写出。模型预测输入和67,170,304与67,170,305之间，请求由−523,232变为−522,720。三份DLL均精确符合。MSYS2另测67,174,400与67,174,401，均为−522,720。

| DLL | 输入limb和 | A位数 | B位数 | 请求的有符号64位解释/字节 |
| --- | ---: | ---: | ---: | ---: |
'''+ '\n'.join(rows)+'''

所有20个案例顺序执行，均有120秒超时和6 GiB可用物理内存保护；保护器没有触发。操作数是最高位为1的稀疏整数，不同地址相乘。三份DLL身份与哈希沿用前一轮清单。

## 结论与下一步

输入limb之和是所测近等长稀疏案例更好的边界解释。源码中的有符号32位N计算、后续工作区取整与分配头部共同解释了全部记录值，并预测了新台阶。可将定位范围缩小到这个具体候选表达式；最后一步是以匹配构建捕获内部调用栈与N的实际值。

Windows环境仍为build 27766。未完成稳定版Windows复现，未对原DLL实施修补，也未完成DOI归档。上游报告草案随附，尚未发送。
'''
    (R/'Windows_GMP_FFT阶梯与源码分析_20261016.md').write_text(report,encoding='utf-8')
    manifest=json.loads((ROOT/'experiments_20261016'/'followup'/'build_manifest.json').read_text())
    identity='\n'.join(f'- {k}: {v["sha256"]}' for k,v in manifest['dlls'].items())
    draft='''To: gmp-bugs@gmplib.org
Subject: GMP 6.3.0 Win64 sparse multiplication: signed FFT size model matches wrapped allocation requests

Dear GMP maintainers,

I can reproduce a wrapped allocation request in three different prepackaged Windows x64 GMP 6.3.0 DLLs, including MSYS2 mingw-w64-x86_64-gmp 6.3.0-2 (build metadata lists GCC 13.2.0-2). The failures occur in direct C calls without gmpy2, Fibonacci recurrence or decimal conversion.

For x=2^(b-1), mpz_mul(y,x,x) succeeds at b=2147352576 and fails at b=2147352577. A forwarding allocation callback records size_t=18446744073709028384 (2^64-523232), while stderr prints size=4294444064. With unequal operands, two products both of width4294705089 bits differ: input limb sum67104769 fails, 67104768 succeeds.

The matching MSYS2 gmp.h gives sizeof(mp_limb_t)=8, sizeof(mp_size_t)=4 and sizeof(mp_bitcnt_t)=4. Separate DLL helper queries and official 6.3.0 source inspection suggest the signed mp_size_t expression N=pl*GMP_NUMB_BITS in mpn/generic/mul_fft.c (line937). At the first failure, rounded rn=67108864, pl=rn/2=33554432, k=11, so pl*64=2^31. A two's-complement arithmetic model follows through nprime=-32704 and the temporary-allocation header to reproduce the full request. It also reproduces the original larger-case request2^64-369632.

A further prediction was recorded before eight tests: input limb sums67170304 and67170305 should request2^64-523232 and2^64-522720, respectively. All three DLLs match. We have not yet captured an internal stack or inspected N inside a binary-matched build, so this is a strongly corroborated source explanation rather than a debugger-confirmed instruction.

DLL SHA-256:
'''+identity+'''

Host: Intel Core i5-14400F,32GB RAM, Windows11 build27766 (preview). Memory guards did not trigger. A stable-Windows replication has not yet been obtained. The supplied DLLs are prepackaged; original configure output/config.log and wheel-matched headers are unavailable. The MSYS2 package metadata and official source archive checksum are retained. WSL2/Linux GMP and native Windows MPIR both complete the original target task; these differ in build and environment and are not an OS-only comparison.

Attached material contains the tested C reproducer, guarded runner, allocation logs and model data. No DLLs, executables or core dumps are included. Build the C source with MSVC x64 (cl /O2 gmp_boundary_followup.c), then run it in a disposable guarded child as probe.exe <full-path-to-libgmp-10.dll> <a-bits> <b-bits> <square|multiply>. For the boundary square pass2147352577 twice and square. The runner documents timeout/memory protection.

Could you confirm whether this signed length calculation is the expected limitation of these Win64 configurations, or a defect to fix? I can provide the retained package provenance and additional tests.

Regards,
Xudong Lu
'''
    bundle=R/'upstream_report';bundle.mkdir(exist_ok=True)
    (bundle/'gmp-bugs_draft.txt').write_text(draft,encoding='utf-8')
    for name in ['gmp_boundary_followup.c','run_boundary_followup.py','model_fft_sizes.py','run_fft_staircase.py','run_fft_extension.py']:
        shutil.copy2(ROOT/name,bundle/name)
    for name in ['staircase.csv','source_manifest.json','source_model.json','source_files_sha256.json','extension_predictions.json','extension_summary.json','Windows_GMP_FFT阶梯与源码分析_20261016.md']:
        shutil.copy2(R/name,bundle/name)
    with zipfile.ZipFile(R/'GMP上游报告待发送_20261016.zip','w',zipfile.ZIP_DEFLATED) as z:
        for p in bundle.iterdir():z.write(p,p.name)
    print('EVIDENCE_AND_UNSENT_DRAFT_READY',len(first)+len(more))
if __name__=='__main__':main()
