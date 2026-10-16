from pathlib import Path
from fractions import Fraction
import json

ROOT=Path(__file__).resolve().parent
OUT=ROOT/'experiments_20261016'/'followup'
square=json.loads((OUT/'square_summary.json').read_text())
asym=json.loads((OUT/'asymmetric_summary.json').read_text())
same=json.loads((OUT/'discriminate_summary.json').read_text())
build=json.loads((OUT/'build_manifest.json').read_text())
fail=[r for r in square if r['dll_label']=='wheel231' and r['wrapped_requests']]
fail.sort(key=lambda r:r['a_bits'])
slopes=[str(Fraction(y['wrapped_requests'][0]['signed64']-x['wrapped_requests'][0]['signed64'],y['a_bits']-x['a_bits'])) for x,y in zip(fail,fail[1:])]
manifest={'square_cases':len(square),'asymmetric_cases':len(asym),'matched_result_cases':len(same),
  'guard_terminations':sum(r['guard'] is not None for r in square+asym+same),
  'sampled_signed_request_slopes_bytes_per_input_bit':slopes,
  'single_exact_affine_function_on_samples':len(set(slopes))==1,
  'mathematical_result_width_is_sufficient_trigger':False,
  'fft_rounded_length':None,'first_overflowing_expression':None,
  'matching_wheel_headers_available':False,'msys2_header_widths':build['widths']}
(OUT/'analysis.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
text='''# Windows GMP 边界后续实验

2026年10月16日。本记录补充早先的单次平方二分结果。所有故障案例在独立子进程内执行。父进程设120秒超时和6 GiB可用物理内存保护，保留退出码与完整分配请求。分配回调直接由C实现，并透传至DLL原分配器。三组实验共39个案例，均未由保护器终止。原始stdout、stderr、逐次结果和构建记录位于本目录。

## 独立来源与类型测量

MSYS2包：mingw-w64-x86_64-gmp 6.3.0-2。官方来源与可核对哈希见[包页面](https://packages.msys2.org/packages/mingw-w64-x86_64-gmp)。下载包SHA-256为8924433974c4add46cb46ea4f6ef283b5c5139d3f552375115b5580f855015cc。解压后的mingw64/bin/libgmp-10.dll SHA-256为37248cda33845e7c5c35a574e57da762dd0a8268f0270d179f30a33746809681。包元数据记录CI构建者msys2/msys2-autobuild/0852421d/6195286796，构建日期2023-09-15，构建环境含mingw-w64-x86_64-gcc 13.2.0-2。

使用同包gmp.h编译C探针，sizeof(mp_limb_t)=8、sizeof(mp_size_t)=4、sizeof(mp_bitcnt_t)=4、sizeof(unsigned long)=4、sizeof(void*)=8字节。头文件SHA-256为178db66910305eed62d2d3fdd1f203a45febaa2aaa64690b608c7d95f2a1a3cc。此测量只界定该MSYS2包的头文件；没有取得两份wheel各自的配套头文件，不能替代它们的ABI证明。取得包的脚本、下载URL、哈希清单和BUILDINFO均保留。

## 三份DLL的相邻平方结果

| 来源 | DLL SHA-256 | 2,147,352,576位 | 2,147,352,577位完整请求 |
|---|---|---|---|
'''
for label in ['wheel231','wheel221','msys2']:
    text+=f'| {label} | {build["dlls"][label]["sha256"]} | 成功 | 18,446,744,073,709,028,384 = 2^64−523,232字节 |\n'
text+='''
令T=2^32−2^18=4,294,705,152位，L=T/64=2^26−2^12=67,104,768个limb。平方成功点的数学结果为T−1位，失败点为T+1位。失败结果的数学位数由输入推得，并未读到失败后的结果对象。不能把这个相邻平方结果单独解释成全部运算的结果位数上限。

## 阈值以上请求采样

| 平方操作数位数 | 完整请求的有符号64位解释/字节 | 请求低32位 |
|---|---:|---:|
'''
for r in fail:
    e=r['wrapped_requests'][0]
    text+=f'| {r["a_bits"]:,} | {e["signed64"]:,} | {e["low32"]:,} |\n'
text+='''
前6个不同位数样本形成−523,232字节的平台；较大样本为−369,632字节。相邻样本的精确斜率不相同，不支持一个对原始位数成立的单一非恒定仿射公式。尚未在所有内部取整跳点进行采样。−523,232/8=−65,404，−369,632/8=−46,204，说明这些数在算术上可写成负的8字节单位；未证明内部变量就是该负limb数。

## 不等长乘法与相同结果位数对照

以下记录使用不同的操作数地址。A、B为各自位数，数学结果为2^(A+B−2)，因此位数为A+B−1。每个列出的案例在三份DLL上的结果相同。

| A | B | 数学结果位数 | 输入limb数之和 | 结果 |
|---:|---:|---:|---:|---|
'''
for r in [x for x in asym+same if x['dll_label']=='wheel231']:
    before=next(e for e in r['events'] if e['event']=='before_mul')
    outcome='成功' if r['exit_code']==0 else '分配请求回绕'
    text+=f'| {r["a_bits"]:,} | {r["b_bits"]:,} | {before["expected_result_bits"]:,} | {before["a_limbs"]+before["b_limbs"]:,} | {outcome} |\n'
text+='''
最后两行的数学结果同为4,294,705,089位，规范化后均为67,104,768个limb，结果一败一成。它们的输入limb总数相差1。这排除了单纯的数学结果位数或规范化结果limb数解释，也排除了仅平方专用路径才能触发的解释。输入limb长度、内部取整以及工作区尺寸应列入下一步原生调用栈追踪。

## 历史机制与待检验假设

Mark Sofroniou（Wolfram Research）2013年的[GMP 5.1.2故障记录](https://gmplib.org/list-archives/gmp-devel/2013-September/003365.html)指出，int型中间乘积在赋给mp_size_t之前溢出，随后造成巨大的size_t分配请求。这是有源码与调用栈的历史案例。本次现象支持检验相似的尺寸运算机制，但尚未取得原DLL匹配源码及首个异常表达式。

MSYS2的mp_size_t与mp_bitcnt_t实测为32位；所核查MPIR Win64源码将相应类型定义为64位。两者存在可核查的类型差异。该差异构成待检验假设，尚不能单凭头文件确定FFT长度计算是本次故障原因。内部FFT取整长度未测得。所有Windows案例运行于同一build 27766，稳定版Windows独立复现仍待补充。
'''
(OUT/'Windows_GMP_边界后续实验_20261016.md').write_text(text,encoding='utf-8')
print(json.dumps(manifest,indent=2))
