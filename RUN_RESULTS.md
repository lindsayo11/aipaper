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

---

## 补充：离线重跑校验（2026-11-19）

- **目的**：确认 `validation.json` 可从本机产物复现，并补上此前缺失的执行记录。
- **方式**：把 `data_and_results.zip` 完整解包到 `output/`（10,377 个文件），在无网络条件下执行 `validate`；环境 numpy 2.3.5 / scikit-learn 1.8.0 / scipy 1.17.0，Node v22.22.2。
- **结果**：**21 项全部 passed**，退出码 0，耗时 20.09s（另一次 21.39s）。
- **与原记录比对**：除 `generated_at` 与路径分隔符（原文 `/`，Windows 为 `\`）外逐字段一致，判定与证据数值均未改变。校验依赖的 5,075 份成功快照哈希回读、22 个内嵌导出逐字节比对均通过。
- **`validation_run.log` 为何是 0 字节**：`validate` 阶段只写 `validation.json`，不向 stdout 打印（见 `src/ai_trends/cli.py`），重跑同样不产生 stdout。因此执行级证据改为 `data/logs/validate_2026-11-19.log` 与 `data/runs/*-validate.json`，未用空文件充作日志。
- **主题命名**：`data/model/topic_review.csv`、`data/model_lsa/topic_review.csv` 记录 onnx/lsa 各 50 个主题的名称、任务、方法、数据模态与瓶颈，`review_status=human_verified`、`reviewed_by=lindsayo11`、`reviewed_at=2026-11-19`。依据为 `automatic_keywords` 与每个主题前十篇代表论文标题，由 AI 起草后经仓库所有者逐条审核确认。**本节取代上文"仍需人工命名复核"的表述。**
  - 边界：命名只描述主题内容，不构成模型正确性、最优 K 或跨模型编号可对齐的证明。
  - 未回写：包内 `output/models/*/topic_review.csv` 与 89 MB `report.html` 内嵌副本仍是 2026-11-09 的 `pending` 快照。回写会使 `report_embedded_exports_exact`（22 个内嵌导出逐字节比对）失败，必须连同报告一起重新生成，本轮未做。两处差异以 2026-11-19 的仓库文件为准。
- **完整数据包已发布**：`data_and_results.zip`（537,695,500 B，SHA256 `69d86edeec4862727fea5b140a8d591ea4598d9c2c19767b83914a5f8e186420`）作为 Release 附件发布，标签 [`data-2026-11-19`](https://github.com/lindsayo11/aipaper/releases/tag/data-2026-11-19)。上文"仅在本机留存"的表述自本条起不再适用；GitHub 记录的 asset digest 与本机 SHA256 一致，直链可下载（Content-Length 537,695,500）。

---

## 补充：评分逐条账本与差额 59 对账（2026-11-20）

- **问题**：主题评分表 350 行的样本计数合计 30,134，`analysis_manifest.json` 原记录 30,075，相差 59 篇，且包内没有逐条评分资料可核。
- **结论**：差额不是漏采或重复，是两种连接口径的净差。恒等式：

  `30,134（账本）= 30,075（严格 paper_id 直连）+ 162（按 OpenReview ID 归一匹配）− 103（标题冲突隔离或未形成评分）`

- **+162**：模型侧 `paper_id` 是来源页哈希（如 `ICLR-2025-src-0c4cfb…`），评审档案按 `venue-year-or-<OpenReview ID>` 记录；标题归一 + OpenReview ID 对齐后才连上，严格 ID 直连会漏计。ICLR 2025 109 篇、NeurIPS 2025 53 篇。
- **−103**：评审观测存在但标题与档案不一致被隔离（ICLR2025 8、ICLR2026 1、ICML2025 6、ICML2026 39、NeurIPS2024 1、NeurIPS2025 48），或匹配后无可用评分，未计入评分表。
- **逐条账本**：`public_review_scores_and_evidence.zip` 新增 `score_ledger/paper_scores.csv`（30,134 行；每行 `observation_ids`／`review_ids`／`ratings` 三个等长列表按位置对齐）、`score_ledger/venue_year_summary.csv`、`score_ledger/README.md`；`reconciliation/` 放 162／103 两侧逐条清单、`count_definitions.csv`、`gap59_summary.json` 与 `verify.py`。
- **复算**：`python scripts/verify_score_ledger.py --detail` → 9 项检查全部 PASS。350 个主题的计数与均值逐行等于 `data/analysis/scores.csv`（0 不一致）；逐条评分均值 0 例偏差；量表 0 例越界；`observation_ids` 数量与 `n_reviews` 全量一致。
- **63,391 条观测没有原始评审 ID**：来自公开规范化镜像（`not_preserved_by_normalized_mirror`），账本改用 `observation_id` 定位，评分值不受影响；`n_original_review_ids` 逐篇给出保留原始 ID 的条数。
- **口径澄清**：`supplemental_inputs.scored_model_papers` 记的是严格 ID 口径（30,075），评分表实际使用的是 30,134。两个数都保留，定义写在同一 JSON 的 `scored_model_papers_scope` 与 `scored_model_papers_used_in_scores_table`，不互相覆盖。
- **发布**：附件 `scores-2026-11-20`（26,194,296 B，SHA256 `80d19e9a1f45ad5aa93724fb9dbcc1406e3541412e7ba1ea01ca68cb0b353874`）。仓库侧 `data/scores/` 只放差额清单与结论，账本本体随附件分发。

---

## 补充：8 组结果表与 4 张图入库（2026-11-20）

补充轮交付的 8 组结果表与 4 张图此前只在交付件里，仓库没有对应文件。本轮原样导出并把可复算的部分全部逐格核对：

| 表 | 行数 | 复算 |
| --- | ---: | --- |
| `data/supplement/tables/sample_scale.csv` | 9 | 一致 |
| `field_completeness.csv` | 10 | 一致 |
| `abstract_length.csv` | 9 | 口径不同（样本数一致，词数高 1.34–2.44 词/篇） |
| `topic_change_common_years.csv` | 50 | 一致（含 2024→2025 占比变化逐值） |
| `topic_venue_difference.csv` | 50 | 一致 |
| `topic_year_detail.csv` | 450 | 一致 |
| `score_coverage.csv` | 7 | 一致（对齐 `data/scores/`） |
| `iclr_public_submission_rates.csv` | 150 | 一致（对齐 `iclr_topic_rates_results.zip`） |

- **图**：`reports/figures/` 四张（年度样本规模、摘要长度分布、三会合并主题变化、2025 会议差异），取自交付件内嵌原图。
- **关键值复核**：思维链推理 2024→2025 由 123 篇增至 339 篇、占比 1.39%→2.77%，变化 **+1.37 pp**；图神经网络与图表示 364→423 篇、占比 4.12%→3.45%（篇数增、份额降）；3D 高斯泼溅重建 2025 年在 NeurIPS/ICLR/ICML 为 2.53%/2.35%/0.40%。
- **唯一不能逐位重算的表**：摘要长度。交付表的分词实现未随项目保留，空白分词复算的偏差随连字符/斜杠密度变化（不是常数），故按交付口径保留、不改写，差异记在 `data/supplement/verification.json`。
- **再生成**：`python scripts/export_supplement_tables.py --xlsx <交付件>`；只复算加 `--verify-only`。
