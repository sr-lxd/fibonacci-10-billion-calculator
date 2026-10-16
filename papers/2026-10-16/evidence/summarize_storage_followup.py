from pathlib import Path
import hashlib
import json

ROOT=Path(__file__).resolve().parent
OUT=ROOT/'experiments_20261016'/'followup'/'storage'
data=json.loads((OUT/'summary.json').read_text())
expected='ee790ff513e4d66ccf5e59c355c696a323dfd968e30f63d1466fd2fdf68f270f'
checks=[]
for rep in range(1,4):
    path=OUT/f'mpir_file_rep{rep}'/'output.txt'
    sha=hashlib.sha256();count=0
    with path.open('rb') as stream:
        prefix=b'F(1000000000) = '
        assert stream.read(len(prefix))==prefix
        while chunk:=stream.read(8*1024*1024):
            chunk=chunk.replace(b'\r',b'').replace(b'\n',b'')
            assert chunk.isdigit()
            count+=len(chunk);sha.update(chunk)
    assert count==208987640 and sha.hexdigest()==expected
    checks.append({'rep':rep,'digits':count,'payload_sha256':sha.hexdigest()})
for record in data['records']:
    if record['label'].startswith('linux'):
        assert record['sha256']==expected
data['numeric_file_checks']=checks
groups=data['groups']
f=groups['mpir_file']['process_wall_median_s'];n=groups['mpir_nul']['process_wall_median_s']
t=groups['linux_tmp']['conversion_close_s_median'];c=groups['linux_mntc']['conversion_close_s_median']
data['descriptive_ratios']={'mpir_nul_over_file':n/f,'linux_mntc_over_tmp_conversion':c/t}
(OUT/'summary.json').write_text(json.dumps(data,indent=2),encoding='utf-8')
report=f'''# 十亿项存储输出对照

2026年10月16日。同一主机，n=1,000,000,000。MPIR使用未修改的v1.1.0发布EXE；写本机文件和写NUL各3次。Linux沿用原两平方和分治输出函数，写WSL2 /tmp与/mnt/c各3次。全部顺序执行，第二轮反转四个条件的顺序。没有控制主机的其他后台任务，未清空文件缓存。

| 条件 | 次数 | 中位数/s | 计时范围 |
|---|---:|---:|---|
| MPIR文件 | 3 | {f:.3f} | 进程创建至退出 |
| MPIR NUL | 3 | {n:.3f} | 进程创建至退出 |
| Linux /tmp | 3 | {t:.3f} | 十进制转换、写入与关闭文件 |
| Linux /mnt/c | 3 | {c:.3f} | 十进制转换、写入与关闭文件 |

MPIR NUL/文件的中位数比为{n/f:.4f}；Linux /mnt/c与/tmp转换关闭阶段的中位数比为{c/t:.4f}。这是各自后端内部的输出目标对照，表中不同后端的计时边界仍不同。Linux fsync单独记录，不计入转换关闭时间。NUL实验也包括算术、位数校正、转换及状态输出；它只去除了数字结果文件的实际存储。

3份MPIR文件及6份Linux文件的数字载荷均为208,987,640位，SHA-256为{expected}。NUL不产生可供校验的数字文件，因此不计入数字一致性证据。

本对照在十亿项完成，没有重测百亿项完整输出，不能据此解释百亿项阶段差的具体组成或给出目标规模的存储加速比。原始命令、环境、stdout/stderr、逐次时间和校验摘要随附；完整数字文件在本机保存，不收入补充压缩包。
'''
(OUT/'十亿项存储输出对照_20261016.md').write_text(report,encoding='utf-8')
print(json.dumps(groups,indent=2))
