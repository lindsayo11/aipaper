# ICLR / ICML / NeurIPS 投稿与研究趋势大作业：从零执行和分阶段交付

版本日期：2026-10-28。范围为 **ICLR、ICML、NeurIPS 的 2024—2026 届**；每次采集保留实际 UTC 时间和来源哈希。该文档是实施合同，历史会话中曾报告的数据数量不能直接作为新一轮结果。项目参考 [AI-Paper-Trends](https://github.com/zhihengli-casia/AI-Paper-Trends) 的问题意识，独立实现代码和审计逻辑。

## 0. 成功标准与不能混用的三种数据

1. **录用成果语料**：官网节目册中的标题、作者、摘要、作者关键词、来源链接、明确赛道和展示形式。可研究已录用论文主题与分布，不能由它反推全部投稿或主题录用率。
2. **会议规模统计**：逐届有证据的投稿数、有效投稿数、进入审稿数、录用数与公布的接收率。保留每个数的来源等级、统计时间、分母及取整程度；与实际采到的论文数并排对账。
3. **公开投稿和评审**：OpenReview 的可公开论文、决定和正式评审。只有能核验覆盖范围和缺失状态，才能计算相应队列的评分和条件录用率。ICML、NeurIPS 自愿公开拒稿不能代表全部拒稿。

完成标准：九个届次的官网批量数据完成真实采集与原始快照；详情补采写明计划、成功、失败、剩余；全部合格主会摘要进入共享主题模型；两种实际运行的模型、完整统计和中文报告生成；测试、构建及产物一致性验证通过；**每个阶段都提供可下载的持久文件**。评审接口受限时须明确记录为受阻，评分和主题录用率留空；这不等于评审分析已经完成。

## 1. 环境、代码结构和初始可交付物

以 Python 3.12、`numpy`、`scipy`、`scikit-learn`、`lxml`、`matplotlib` 建立基础环境；可选 CPU 语义模型使用 `onnxruntime` 与 `tokenizers`，不要求 Torch。将版本写入运行清单。基础模型无需模型下载；语义模型从固定 revision 下载 tokenizer 与 ONNX 权重，记录两个文件的 SHA256。ONNX Runtime 初始化**之前**设置 `ORT_DISABLE_TELEMETRY=1`，并在 API 层关闭事件；这遵循[官方隐私说明](https://github.com/microsoft/onnxruntime/blob/main/docs/Privacy.md)。若运行进程中曾在未关闭遥测时初始化，应显式失败并要求新进程。

目标目录：

```text
configs/latest.json               范围、请求限速、模型参数
configs/semantic.json             相同语料的 MiniLM 配置
src/ai_trends/common.py           HTTP、缓存、哈希、原子写入
src/ai_trends/collectors.py       官网/OpenReview/详情页
src/ai_trends/processing.py       清洗、关联、去重、隔离
src/ai_trends/modeling.py         LSA、MiniLM、聚类与主题词
src/ai_trends/analysis.py         数量、趋势、评分和分母
src/ai_trends/report.py           中文离线 HTML 报告
src/ai_trends/cli.py              分阶段入口和运行清单
scripts/run.py                    源码树入口
scripts/compare_models.py         两模型同一论文集的对照
scripts/build_release.py          源码包/数据包与哈希清单
tests/                            真实边界的离线行为测试
docs/                             实施说明、数据口径、实跑结果
output/                           带时间、来源和状态的产物
```

**第一个交付点**：项目骨架、配置、接口约定、这份 Markdown 和最小可运行的采集代码打成 `source_checkpoint.zip`，立即保存为持久文件并返回文件 ID。验证文件可以下载，再扩展规模。不要用临时工作目录路径代替交付。

## 2. 逐届数据接口核实

每届先请求官网 `https://{iclr.cc|icml.cc|neurips.cc}/virtual/<year>/papers.html`，从页面真实声明发现 JSON 地址，再获取 `*-orals-posters.json` 及存在时的 `*-abstracts.json`。2024/2025 常有内嵌摘要；2026 可有独立摘要映射。分页需沿 `next` 继续直到完整，不将单页当全部。成功响应保留压缩原文、请求 URL、最终 URL、时间、大小和 SHA256；401/403、验证码及空体不能作为成功缓存。按域名限速、有限退避、断点重启，禁止绕过平台验证。

逐届检查项：列表事件数、去重论文数、main 数、有摘要数、摘要覆盖率、赛道分布、OpenReview 状态、采样上限和源 URL。oral/poster/spotlight 常是同一论文的多次事件；用会期范围的真实 forum ID、官方 UID、标题与作者做保守合并，并保留所有事件 ID。跨会议、跨年重投不自动合并。展示形式不等于录用决定；官网导航中的 Main Track 字样不能证明单篇赛道。

OpenReview 从会议 group 获取真实邀请配置，notes 用游标完整分页，分开解析论文投稿、决定、正式评审及对评审本身的质量评分。支持 API 版本差异和 `{"value":...}`。检查 `readers`，只保留公开内容；可选授权凭据仅从环境读取，不写入源码、日志或 HTTP 缓存。若出现 `ChallengeRequiredError` 或人机验证，同一运行停止该通道，并将九届的受阻状态显式写入覆盖表。审稿数为零不能解释成论文得分为零。

**第二个交付点**：九届批量原始响应、`papers.jsonl`、`reviews.jsonl`（可能为空）、`source_coverage.json/csv`、逐届检查点及采集日志组成 `bulk_snapshot.zip`；同时交付可直接阅读的 `papers.csv` 和采集器源码。记录未完成届次，不把部分结果标成完整。

## 3. 官网详情补采与列表对账

对所有已认定 main 且缺摘要的论文优先请求公开详情页；比较官网实时目录与批量 JSON 的事件 ID、规范化标题和作者。批量名单缺少的目录条目另行保存。解析 JSON-LD 标题/作者、专用摘要节点、公开 forum 链接和页面级赛道证据。没有明确赛道/决定证据的新论文保持 `unknown`，不自动加入主会模型。详情 URL 去除地点重定向引起的重复，按批次持久检查点、有限并发、失败可重试；不得让补采覆写原快照。

尤其要核查 NeurIPS 2026 的静态文件与实时目录差异。先验证当日官网状态，再决定是否按地点或历史快照扩展。第三方目录只能作为显式标注的补充证据；只有官方论文 ID 加标题/作者精确对上且赛道来源可审计，才允许提升赛道。报告列出官方登记录用数、实采明确 main 数和差值；两者相等仍不证明提交队列完整。

**第三个交付点**：`detail_checkpoint.zip` 包含已完成的详情原文缓存、补采 JSONL、尝试记录、失败 URL、索引对账及摘要修复率。若数千请求未完成，持续发布新的有时间戳检查点；这是阶段性数据，不冒充最终结果。

## 4. 清洗、数据模型、关联和质量门槛

统一论文字段：`paper_id, venue, year, title, abstract, authors, keywords, source, source_id, source_url, openreview_id, track, track_evidence, decision, presentation, text_version, collected_at, metadata`。作者关键词为空则保留空列表；模型产生的主题词另存，不能冒充作者关键词。记录文本是节目册版本还是投稿版本，评分对应的时间阶段保留。

赛道取 `main / position / datasets_benchmarks / workshop / unknown`；决定取 `accepted / rejected / withdrawn / desk_rejected / under_review / unknown`。清理实体、格式标签与空白，不破坏科研文本中的数学符号。相同 ID 而标题冲突的详情补丁隔离，绝不将另一篇摘要拼到该论文；同届精确 forum ID 可跨来源关联。保留原始决定及源组、重复展示事件、数据时间于元数据中。输出 `quarantine.jsonl`、逐届赛道摘要覆盖和状态分布。

评分字段为 `review_id, paper_id, rating_raw, rating, confidence, scale_min, scale_max, score_stage, source_url, updated_at`；无法解析或不在量表内保持缺失。相同评审 ID 按更新时间去重。公开决定数据须另外记录已知/未知/撤稿/直接拒稿，禁止把未知状态充当 rejected。

**第四个交付点**：合并后 `processed/papers.jsonl`、`papers.csv`、`reviews.jsonl`、`quality.json`、`coverage.csv`、`quarantine.jsonl` 与合并输入哈希组成 `processed_snapshot.zip`。所有原始快照保留，可反向追踪一条论文。先验证主会摘要缺失和跨来源标题冲突，再建模。

## 5. 无监督主题建模与真实模型对照

默认研究集合为**已识别 main、accepted、有真实标题和摘要**的论文。先拟合全会议全年份共享主题空间，避免分别聚类再用同一个数字对齐不同主题。基线为词/短语 TF-IDF → TruncatedSVD → L2 → MiniBatchKMeans；语义版为固定 revision 的 `sentence-transformers/all-MiniLM-L6-v2` 量化 ONNX → attention-mask 池化 → 长文 token 分块与加权合并 → L2 → KMeans。固定种子、记录特征和缓存指纹，按文本指纹缓存向量以便增量补摘要。默认 50 主题是可调课堂分析粒度，需要人工审查，不声称最佳 K。可选 BERTopic/HDBSCAN 入口与本次**实际运行**后端分别记录。

文本特征只能用标题与摘要；年份、评分、决定不进入向量。输出每篇的 `topic_id`、相似度、离群标识；每主题自动关键词、规模、中心附近五篇代表论文和 `topic_review.csv` 人工命名表。模型清单记录 encoder、版本、权重哈希、数据哈希、种子、离群比例与缓存命中。同一论文 ID 交集上比较两个模型的 ARI、AMI；一致性不是主题质量或正确率。

**第五个交付点**：先交付 `lsa_results.zip`（主会语料、逐论文归属、主题词和代表论文、模型配置与基线图）；语义编码时间较长时可独立交付编码断点。语义运行完成再交付 `semantic_results.zip` 和模型对照表。模型未运行成功时不得把预期结果写成已完成。

## 6. 投稿/录用规模、主题热度、评分和接收率

来源表每行记录 `raw_submissions`、`valid_submissions`、`reviewed`、`accepted`、`official_rate`、`denominator_definition`、`source_level`、`source_url`、`source_date`、`approximate` 和口径备注。优先会议官网与 Fact Sheet；机构官方转述标为机构级，不冒充会议原文；矛盾的时点与口径并列，不硬改成一个看似精确的数。例如 ICLR 2026 回顾与 Fact Sheet 的录用数不同；ICML 2026 官网 Fact Sheet 与早期机构转述使用不同数量及投稿范围，必须保留时间与定义。每届实采已确认 main 数与相应来源统计并排对账，缺失为 `null`。

主题热度：同届同会议主题的已观察主会录用数 / 同届同会议**全部已观察主会录用数**，同时报告没有摘要而不能归主题的论文数。年度变化用百分点，保留前后年份及样本数；不补缺失年份为零。跨会议只比较相同年份：若某会议实采录用远低于登记来源，例如不足其 90%，该年不进入三会热度矩阵，但仍在逐届报告中标记为部分样本。这是明显缺口筛选，并非完整性认证。已接收成果有时滞与选择偏差，增长趋势只是检索线索。

评分先在每篇内部对合法正式评审求均值，再在主题内部按论文等权求均值；会议、年份、量表和评分阶段不混合。总体接收率采用来源公布的原分母，不由当前接收论文列表计算。分主题条件接收率只有在**事先有独立完整决定队列证明**，并且决定总数、录用总数和每一篇被决定论文的主题归属均核对成功后才发布；否则保持空值。若将来有拒稿公开样本，应显式把其文本纳入建模并标为样本，仍不可外推全体投稿。

**第六个交付点**：`analysis_results.zip` 包含逐届官方统计、名单差值、主题年度表、变化表、热度矩阵、评分分层表、决定样本表、来源和解释字段。实际无评分时输出空表与不可计算原因，不制造曲线。

## 7. 中文报告、选题用途和验收

报告为单文件 HTML，内嵌图表/CSS/JS，无外部 CDN，来源标题、摘要和 URL 必须转义与校验协议。展示九届规模与来源等级、覆盖缺口、共同年份主题热度、近期变化、主题示例论文、论文检索和模型参数。浏览表为性能按会议/年份/赛道分层展示最多 5,000 行，清楚标注全量 CSV/JSONL 的下载位置；统计使用全量数据。统计文件以内嵌下载方式跟随单文件报告。

选题支持只能提供可追溯的热点和代表论文。人工复核某主题的任务、方法、数据/模态、瓶颈，查当下相关工作和征稿范围，形成**待验证的 idea 假设**；主题增长不证明新颖性、因果关系或投稿录用优势。AI agent 可编排采集、质量门槛、建模、表格、报告与待复核清单；自动讲述必须从表格与论文证据引用，且人审后才能形成研究建议。

验收包括：9 个配置届次全有明确源状态；HTTP 原文哈希可回读；ID 唯一、标题冲突不污染摘要；主会模型输入 ID 与输出归属 ID 相等；空评分/未知状态处理正确；来源规模与实采结果绝不共用默认分母；报告恶意 HTML/URL 不执行，静态脚本语法和内嵌导出内容对得上；离线行为测试、端到端真实运行、构建、ZIP CRC 与逐文件 SHA256 均通过。结构验证不等于网络完整性证明。

**第七个交付点**：`report.html`、`RUN_RESULTS.md`、`source_complete.zip`、`data_and_results.zip`，以及 `release_manifest.json`（时间、文件大小、SHA256、每阶段验收状态）。源码包提供可搜索的全部源码阅读版、配置、测试、逐步运行命令；数据包含原始网页响应快照、清洗前后 JSONL/CSV、模型和统计结果。预训练权重如未获重分发安排，提供固定 revision 与哈希以及首次下载说明。每个文件在**持久文件服务中创建成功并取得文件 ID 后**才发给用户；逐项核验成功，不把工作目录链接作为下载地址。

## 8. 分阶段命令与中断恢复约定

以下命令是项目应提供的目标接口；编写/集成后须运行 `--help` 和真实阶段验证：

```bash
python -m pip install -e .
python scripts/run.py --config configs/latest.json --output output collect
python scripts/run.py --config configs/latest.json --output output prepare
python scripts/run.py --config configs/latest.json --output output backfill
python scripts/run.py --config configs/latest.json --output output prepare --with-details
python scripts/run.py --config configs/latest.json --output output model --backend lsa
python -m pip install -e '.[semantic]'
ORT_DISABLE_TELEMETRY=1 python scripts/run.py --config configs/semantic.json --output output model --backend onnx
python scripts/run.py --config configs/latest.json --output output analyze --backend lsa
python scripts/run.py --config configs/semantic.json --output output analyze --backend onnx
python scripts/run.py --config configs/semantic.json --output output report --backend onnx
python scripts/run.py --config configs/latest.json --output output validate
python scripts/build_release.py --output output --dist dist
```

每阶段读上阶段检查点而不重抓成功响应；不同范围/配置哈希必须另建运行目录。失败写 `failed` 和错误，不以最后一个进程退出码掩盖局部数据源受阻。若详情采集或语义编码需长时间，先交付已经完成的阶段文件并持续更新版本与覆盖状态；最终包只在最后验收后发布。需重新采集时附新日期快照，旧报告保持可复核，不静默覆盖旧数字。

## 9. 今日执行状态与后续记录

截至本文初次保存，已重建基础 I/O 与逐届采集器，2024—2026 九个官网批量接口已返回成功并写本地原始快照；公开 OpenReview notes 首次请求触发 HTTP 403 平台验证，后续同通道停止重试。分析、模型和报告模块正在集成；**这里没有宣称详情补采或两种完整模型已经在本轮数据上跑完**。后续实跑的篇数、摘要覆盖、主题结果、失败 URL、测试数与所有持久文件 ID 以 `RUN_RESULTS.md` 和阶段清单为准，绝不沿用此前已丢失文件的运行数。
