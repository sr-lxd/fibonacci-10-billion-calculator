# 论文稿件与实测资料

2026 年 10 月 16 日四份修订稿：

- [中文稿](2026-10-16/zh/manuscript.md)：[Word](2026-10-16/zh/manuscript.docx)、[PDF](2026-10-16/zh/manuscript.pdf)。
- [arXiv 英文稿](2026-10-16/en/manuscript.md)：[TeX](2026-10-16/en/manuscript.tex)、[Word](2026-10-16/en/manuscript.docx)、[PDF](2026-10-16/en/manuscript.pdf)、[PDFLaTeX 源包](2026-10-16/en/arxiv_source.tar.gz)。
- [SoftwareX 稿](2026-10-16/softwarex/manuscript.md)：[Word](2026-10-16/softwarex/manuscript.docx)、[PDF](2026-10-16/softwarex/manuscript.pdf)。
- [PeerJ Computer Science 稿](2026-10-16/peerj/manuscript.md)：[Word](2026-10-16/peerj/manuscript.docx)、[PDF](2026-10-16/peerj/manuscript.pdf) 和独立表格。
- [故障定位报告](2026-10-16/evidence/Windows_GMP_平方异常定位_20261016.md)、[C 最小复现器](2026-10-16/evidence/gmp_square_minimal.c)、[二分摘要](2026-10-16/evidence/bisect_summary_20261016.json)及[完整实测补充包](2026-10-16/evidence/实测补充材料_20261015.zip)。
- [三构建边界与不等长乘法后续实验](2026-10-16/evidence/Windows_GMP_边界后续实验_20261016.md)、[全宽请求C复现器](2026-10-16/evidence/gmp_boundary_followup.c)、[配套头文件类型探针](2026-10-16/evidence/gmp_header_widths.c)和[存储对照记录](2026-10-16/evidence/storage_summary_20261016.json)。

三份不同哈希的 Windows GMP DLL（含MSYS2独立来源）在受保护的稀疏数平方试验中，均于 2,147,352,576 位成功、2,147,352,577 位失败。同数学结果位数的不等长乘法案例，因输入limb数之和相差1而出现一败一成；不能把平方边界当作单纯的数学结果位数上限。MSYS2配套头文件的类型宽度已实测，具体内部FFT长度和回绕表达式仍未定位。四份完整输出与新生成的Linux GMP参考文件全文一致，旧参考文件只作历史材料核查。暂未取得稳定版Windows复现，也未完成DOI归档。
