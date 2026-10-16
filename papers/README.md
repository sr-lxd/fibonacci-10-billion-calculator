# 论文稿件与实测资料

2026 年 10 月 16 日四份修订稿：

- [中文稿](2026-10-16/zh/manuscript.md)：[Word](2026-10-16/zh/manuscript.docx)、[PDF](2026-10-16/zh/manuscript.pdf)。
- [arXiv 英文稿](2026-10-16/en/manuscript.md)：[TeX](2026-10-16/en/manuscript.tex)、[Word](2026-10-16/en/manuscript.docx)、[PDF](2026-10-16/en/manuscript.pdf)、[PDFLaTeX 源包](2026-10-16/en/arxiv_source.tar.gz)。
- [SoftwareX 稿](2026-10-16/softwarex/manuscript.md)：[Word](2026-10-16/softwarex/manuscript.docx)、[PDF](2026-10-16/softwarex/manuscript.pdf)。
- [PeerJ Computer Science 稿](2026-10-16/peerj/manuscript.md)：[Word](2026-10-16/peerj/manuscript.docx)、[PDF](2026-10-16/peerj/manuscript.pdf) 和独立表格。
- [故障定位报告](2026-10-16/evidence/Windows_GMP_平方异常定位_20261016.md)、[C 最小复现器](2026-10-16/evidence/gmp_square_minimal.c)、[二分摘要](2026-10-16/evidence/bisect_summary_20261016.json)及[完整实测补充包](2026-10-16/evidence/实测补充材料_20261015.zip)。

两份不同的 Windows GMP DLL 在受保护的稀疏数平方试验中，均于 2,147,352,576 位成功、2,147,352,577 位失败。该相邻结果适用于所测构建与输入；内部 FFT 取整长度和产生回绕的源码表达式尚未定位。四份完整输出与本次直接调用 Linux GMP 生成的参考文件全文一致，旧参考文件只作历史材料核查。暂未取得稳定版 Windows 的复现结果，也未完成 DOI 归档。
