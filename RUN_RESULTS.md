# 本轮真实执行与验收结果

生成时间（UTC）：2026-10-28T09:13:53.982020+00:00。范围：ICLR、ICML、NeurIPS的2024—2026届。

已采集9届官网声明的批量接口，完成5014/5014个详情计划（成功5014，失败0，剩余0）。全部1670个已确认主会摘要缺口已修复。最终43702篇规范化记录中，37662篇明确主会录用、有标题和真实摘要的论文进入两种共享主题模型。

**仍受阻/不能声称完成的部分：** OpenReview首次notes请求HTTP403，随后九届同通道停止；本轮公开正式评审为0条，评分分析与主题条件录用率不可计算。NeurIPS2026静态文件与实时目录存在大缺口；没有逐篇赛道和决定证据的目录新增条目保持unknown，不据录用目录推断全部投稿。

## 逐届对账

| 会议 | 年份 | 原始事件 | 批量去重 | 最终全部记录 | 明确主会录用 | 主会缺摘要 | 首选登记数 | 实采减登记 | 来源层级 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| ICLR | 2024 | 2382 | 2296 | 2296 | 2260 | 0 | 2260 | 0 | conference_fact_sheet |
| ICLR | 2025 | 4040 | 3830 | 3830 | 3708 | 0 | 3704 | 4 | conference_fact_sheet |
| ICLR | 2026 | 5691 | 5468 | 5468 | 5353 | 0 | 5357 | -4 | conference_fact_sheet |
| ICML | 2024 | 2778 | 2634 | 2634 | 2535 | 0 | 2609 | -74 | institutional_restatement |
| ICML | 2025 | 3459 | 3339 | 3339 | 3258 | 0 | 3260 | -2 | conference_fact_sheet |
| ICML | 2026 | 6797 | 6629 | 6629 | 6341 | 0 | 6552 | -211 | conference_fact_sheet |
| NeurIPS | 2024 | 4610 | 4538 | 4538 | 4035 | 0 | 4037 | -2 | conference_fact_sheet |
| NeurIPS | 2025 | 6002 | 5858 | 5858 | 5287 | 0 | 5290 | -3 | conference_blog |
| NeurIPS | 2026 | 9278 | 5791 | 9110 | 4885 | 0 | 7900 | -3015 | institutional_restatement |

登记数保留原来源、时点和分母。ICLR2026官方5355/5357、ICML2026官网6552与机构6352均逐行保留，表中首选来源不是对矛盾的裁决。NeurIPS2026的7900/30709仅有机构官方转述证据。所有来源详见analysis/*/official_statistics与docs/OFFICIAL_SOURCES.md。

## 数据质量与追踪

- 原始批量事件共45037条；本轮最新批量规范化共40383篇。
- 最终ID唯一：True；同会议同年forum身份唯一：True；隔离记录：21。
- 最终赛道分布：`{"main": 37662, "unknown": 3853, "position": 506, "datasets_benchmarks": 1681}`。
- 目录新增条目3344；主会摘要修复率100.00%。目录新增不会自动提升到main或accepted。
- 初始阶段检查点的40,846篇包含被误当作forum的展示占位ID；经独立审查过滤YYYY-Oral--等占位并从原文重建后，批量为40,383篇。早期文件保留为历史阶段；最终数据及bulk_snapshot_v2采用修正规则。
- 同ID标题/决定/赛道冲突被隔离；未知决定不当作拒稿；作者关键词与模型主题词分开。
- source_coverage、details计划/尝试/失败URL、processed合并输入哈希及raw/http原文可逐条追溯。页面级导航没有被用于提升赛道。

## 两个实际运行的模型

| 后端 | 输入论文 | 实现 | 维度 | 主题 | 本次模型运行秒数 | 文本缓存命中 |
| --- | ---: | --- | ---: | ---: | ---: | ---: |
| lsa | 37662 | TFIDF-SVD-L2-MiniBatchKMeans | 128 | 50 | 31.015 | 0 |
| onnx | 37662 | MiniLM-quantized-ONNX-mask-pooling-chunked-L2-KMeans | 384 | 50 | 35.055 | 37662 |

语义编码实际另行执行：首批35992篇，耗时1292.52秒；补齐摘要后新增编码1670篇，耗时64.13秒。最终模型运行时间包含缓存复用，不冒充从零编码的耗时。
两模型交集37662篇；同ID集合=True，同文本指纹=True。ARI=0.291783，AMI=0.500098，仅表示分区一致性，不是正确率或最佳K证明。

所有会议和年份共享同一模型；仅标题/摘要进入向量，年份、评分、决定不进入特征。固定seed=42、K=50。MiniLM固定revision和tokenizer/权重SHA256见模型清单及REPRODUCE。BERTopic/HDBSCAN本轮未执行。主题自动关键词和50行topic_review.csv仍需人工命名复核；没有把代理审核冒充人类专家验证。

## 统计与解释

- 共同年份热度矩阵：[2024, 2025]；排除说明见analysis_manifest。2026 NeurIPS明显缺口使2026不进入三会横向矩阵。
- 主题份额分母为同届同会议全部已观察主会录用论文，包括缺摘要者；变化单位是百分点。没有数据的年份不补零。
- 评分先按论文内部求均值，再按论文等权汇总；会议/年份/量表/阶段隔离。本轮scores.csv为空表并保留表头和不可计算原因。
- 未有独立完整决定队列证明，conditional_acceptance_rate保持null。已录用成果主题增长是检索线索，不证明新颖性、因果或未来投稿优势。

## 新鲜验证

- 离线行为测试：60项，状态passed，退出码0。日志SHA256：`431404b784c7f0dbd9bedb1af20a9e8928beafbf15c6d36f5a7c36acae6271dd`。
- 源码wheel构建：passed；SHA256：`a7a47296ba949b51076341437c6e3a993b0aaa602eb2715b5a6326538f26b789`。
- 产物结构校验：passed；检查项21个。
- HTTP原文哈希回读、ID/模型输入输出一致、空评分、主题分母、报告安全转义/URL协议、内嵌导出逐字节一致及JavaScript语法均有实际检查。结构验证不证明网络完整性。
- 最终ZIP CRC及逐文件SHA256由构建脚本再次验证，记录在release_manifest和各ZIP的MANIFEST.sha256.json。
- 额外浏览器实交互尚未验证：环境无引擎，安装响应非有效ZIP；未将此记为通过。计划要求的静态脚本语法、HTML/URL安全与全量内嵌导出还原已通过，见browser_check.json。

## 重现

源码在 `src/ai_trends/`，复现步骤见 `docs/REPRODUCE.md`。报告 `reports/report.html` 单文件内嵌全量 CSV/JSONL 与统计表，断网可开。固定模型权重不重分发，首次下载的 revision 与 SHA256 见 REPRODUCE。

本仓库只放源码、报告与分析结果表。原始 HTTP 快照、清洗前后语料、模型向量合计约 513 MB，未纳入版本库（超出 GitHub 单文件上限），仅在本机留存。

---

## 补充：评分回填（2026-11-09）

上文"公开评审为 0 条、评分不可计算"记录的是主线实时接口的状态，保留不改。后续补充轮已从公开存档取得评分观测，现将主题评分回填：

- **来源**：`public_review_scores_and_evidence.zip`。`previous_scores/reviews.csv`（227,128 条观测，sha256 `db1e8c25…e69d`）、`previous_scores/topic_scores_50.csv`（sha256 `aa97d4c3…97d`）。溯源字段记在 `analysis/onnx/analysis_manifest.json` 的 `supplemental_inputs`。
- **结果**：`analysis/onnx/scores.json|csv` 由 0 行变为 **350 行**（7 个届次 × 50 主题）。`analysis/lsa` 保持空表——两模型主题编号不可对齐，不跨模型搬运。
- **缺失**：**ICML 2024、NeurIPS 2026** 未取得可核验评分，保持缺失，不按 0 分处理。
- **量表按实际观测记录，并非统一量表**：ICLR 2024/2025 `1—10`、ICLR 2026 `0—10`、ICML 2025 `1—5`、ICML 2026 `1—6`、NeurIPS 2024 `1—10`、NeurIPS 2025 `1—6`。跨年份不合并。
- **口径**：论文内先求均值，再在同届同主题按论文等权平均。条件录用率仍为 `not_estimable`（三会统筹所需的独立完整决定队列未建立）；ICLR 三届的单独口径见 `iclr_topic_rates_report.html`，不与本表混用。
- **影响**：`report.html` 已重新生成，评分章节由"不可计算"改为 350 行明细表并标注来源与量表差异。`processed/reviews.jsonl` 仍为 0 条，主线实时通道受阻的事实未被改写。
- **新版报告**：sha256 `f4b303eb3f9d9b4858a32e97524b718f48e6d6d5c775cec0db21252def800ec9`，89,624,737 字节，已纳入 `data_and_results.zip`（此前包内没有主报告）。
