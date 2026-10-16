from pathlib import Path
from datetime import datetime,timezone
import json,hashlib,statistics,subprocess,shutil
from fft_size_model import model
R=Path(__file__).resolve().parent
E=R/'experiments_20261016';S=E/'staircase';F=E/'final_native';P=E/'windows_gmp_profile'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def utc(t):return datetime.fromtimestamp(t,timezone.utc).isoformat(timespec='microseconds')
def main():
    pred=S/'extension_predictions.json';case=S/'cases'/'msys2_multiply_2149449665_2149449665'/'stdout.jsonl'
    receipt={'prediction_sha256':sha(pred),'prediction_mtime_utc':utc(pred.stat().st_mtime),'prediction_birthtime_utc':utc(pred.stat().st_birthtime),
             'first_case_stdout_birthtime_utc':utc(case.stat().st_birthtime),'source':'NTFS local file metadata, recorded after the runs; not an externally timestamped registration',
             'order_verified':pred.stat().st_mtime<=case.stat().st_birthtime}
    assert receipt['order_verified']
    (S/'prediction_registration_receipt.json').write_text(json.dumps(receipt,indent=2),encoding='utf-8')
    native=json.loads((F/'summary_v2.json').read_text())
    regs=[e for e in native[1]['events'] if e['event']=='fft_unwound_registers'];assert regs[0]['pl_r12d']==33554432 and regs[0]['nprime_r13d']==-32704
    expected=[(67104769,-523232),(67170305,-522720),(86780240,-369632)]
    for s,r in expected:assert model(s,11)['request_i64']==r
    g=json.loads((P/'summary.json').read_text());m=json.loads((E/'mpir_profile'/'summary.json').read_text())
    gm=g['medians'];mm=m['medians']
    ratio=mm['writer_total_s']/gm['writer_total_s']
    record={'windows_gmp_medians':gm,'windows_mpir_medians':mm,'MPIR_to_GMP_writer_ratio':ratio,
            'prediction_receipt':receipt,'source_model':{str(s):model(s,11) for s,_ in expected},
            'unwound_frame':regs[0],'large_sparse_case':{'operand_bits':native[2]['a_bits'],'exit_code':native[2]['exit_code'],'guard':native[2]['guard'],
              'returned_result':any(e['event']=='after_mul' for e in native[2]['events']),
              'abnormal_request':native[2]['wrapped_requests'][0]}}
    (E/'final_revision_metrics.json').write_text(json.dumps(record,indent=2),encoding='utf-8')
    report='''# 最终补充实验与对照记录

2026年10月16日

## 实际DLL指令与调用帧

REA/Ghidra12.1.4只读分析已核验的MSYS2 DLL，SHA-256为37248cda33845e7c5c35a574e57da762dd0a8268f0270d179f30a33746809681。__gmpn_mul_fft入口RVA为0x40130；RVA0x40202的SHL EDI,6将pl乘64，随后RVA0x4020c的SAR EDI,CL有符号右移得到M，均为32位。RVA0x4030f将工作区计数符号扩展到64位，RVA0x40319调用重入临时分配函数。后者RVA0x206d的LEA RSI,[RDX+0x10]直接确认16字节头部。汇编与反编译证据含目标哈希、分析器版本和限制，分别随附。

在异常分配回调内用CaptureStackBackTrace与RtlVirtualUnwind捕获实际调用帧。返回地址RVA0x4031e正是上述CALL之后；恢复的非易失寄存器为pl(R12D)=33,554,432、k(ESI)=11、Nprime(EBX)=−2,093,056、nprime(R13D)=−32,704，全部与模型一致。N本身在该时刻已被后续运算覆盖，未将恢复的其他寄存器冒充N。此证据确认MSYS2实际经过该分配路径；另两份wheel尚未逐份做同样指令与帧检查。

## 正值回绕风险采样

单个更大稀疏平方输入b=4,294,967,297。原先用公共移位接口构造时，进程在到达乘法日志前退出，故该记录不算乘法试验。第二个探针用GMP原分配器构造规范化mpz：67,108,865个limb，最高位为1、其余为0。乘法已开始，随后在更深的FFT调用中退出：pl=33,555,456、k=10、nprime=−65,504，请求为2^64−1,048,032字节。120秒和6 GiB保护未触发。没有返回结果，popcount与位数的成功后校验没有执行。因此本例没有观察到静默错误；它显示递归子路径仍可先发生负尺寸分配。大输入的静默损坏假设保留为未验证风险，不写成已发生事实。

## Windows上同代码库对照

直接使用上一轮QPC计时C源码，仅将mpir.h改为同包gmp.h，用同一MSVC x64、/O2/W4和C盘文件目标，链接MSYS2 GMP DLL。源码自动检查除include外完全一致。先验证F(100)，再顺序运行3次F(10^9)，所有载荷SHA-256与新参考相同。静态MPIR与共享GMP及头文件/库配置属于改变因素；两批顺序执行，未做交错随机化。

| 阶段 | MPIR中位数/s | Windows GMP中位数/s |
| --- | ---: | ---: |
'''
    for k,label in [('arithmetic_s','算术'),('width_correction_s','位数校正'),('writer_total_s','输出器总计'),('writer_division_s','除法'),('writer_get_str_s','叶块转换'),('writer_padding_fwrite_s','补零与fwrite')]:
        report+=f'| {label} | {mm[k]:.6f} | {gm[k]:.6f} |\n'
    report+=f'''
输出器比值为{ratio:.3f}。Windows GMP输出42.92秒，与WSL2 Python/GMP的37.90秒接近；这个结果把主要差异缩小到算术库及其构建，而非Windows系统本身。两者C/Python外层代码仍有区别。MPIR除法与叶块转换的实测分解解释了其主要耗时，但尚未把百亿项发布EXE总时间逐秒归因。

各阶段独立取中位数，分项之和不必等于总计中位数；操作均将写出交给运行库/系统缓存，未另加持久化同步。NUL对照与本次分解表明结果文件写入不是十亿项主要瓶颈，不表述为排除全部运行库I/O或所有规模的磁盘影响。

## 预测登记

本地NTFS元数据：预测文件最后写入{receipt['prediction_mtime_utc']}，首个追加案例stdout创建{receipt['first_case_stdout_birthtime_utc']}。预测文件SHA-256为{receipt['prediction_sha256']}。receipt明确这是事后读取的本地时间记录，而非外部时间戳。

## 文档基线

用户提到04:48版本。没有同名快照；最接近且有完整记录的是Git f81e508，提交时间2026-10-16T04:45:06Z（北京时间12:45:06）。package_before_staircase_20261016与该轮稿件对应。最终修订沿用其主结构，差异说明以这个明确基线生成，不把推定基线写成精确的04:48快照。
'''
    (E/'最终补充实验_20261016.md').write_text(report,encoding='utf-8')
    print('FINAL_METRICS',json.dumps(record,ensure_ascii=False))
if __name__=='__main__':main()
