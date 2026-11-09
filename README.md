# ICLR / ICML / NeurIPS 2024—2026 研究趋势

独立实现的可审计数据与主题分析项目。研究对象是明确主会、录用且有真实标题和摘要的公开论文。九届论文共同拟合一个主题空间；另外运行词语LSA和固定MiniLM语义模型，在同一组论文上比较ARI/AMI。

## 结论

**强化学习 + 推理（RL / reasoning / reinforcement / reward）是这两年三会增长最快的方向。** 同届同主题按论文等权，单位为百分点：

| 会议 | 变化 | 论文数 |
|---|---:|---|
| ICLR 2025→2026 | **+3.75 pp** | 32 → 247 |
| ICML 2025→2026 | **+2.24 pp** | 36 → 212 |
| NeurIPS 2024→2025 | **+1.92 pp** | 17 → 124 |

同向增长：多模态推理（ICLR +2.60 pp）、LLM Agent（ICML +2.01 pp）。反向：图神经网络（ICLR −1.37 pp、ICML −1.99 pp）、传统神经网络理论。

两个独立模型在同一批 37,662 篇上给出同向结果：ARI 0.292、AMI 0.500。**这只说明两个模型的分区有中等程度一致，不代表主题质量或正确率。**

## 从哪开始看

1. `reports/report.html` — 主线中文报告，单文件离线，内嵌 22 个可下载的全量表，断网可开。
2. `reports/iclr_topic_rates_report.html` — ICLR 公开投稿的 50 主题评分与条件接收率。
3. `RUN_RESULTS.md` — 逐届对账、模型参数、验证结论，以及"哪些不能声称"。
4. `scripts/iclr_topic_rates/` — 补充轮的完整过程代码：把 38,890 篇公开投稿投影到冻结的 50 主题空间，算评分与条件接收率。含口径说明与未通过的新分批校验记录。

数据规模：9 个届次、5,014 个详情页全部补采成功、43,702 条规范化记录、37,662 篇进入模型。赛道分布 main 37,662 / unknown 3,853 / datasets_benchmarks 1,681 / position 506，隔离 21 条冲突记录。

## 四条口径边界

1. **只有录用成果。** 不能反推投稿分布，也不能推出"选这个主题更容易中"。
2. **主题编号跨模型不可对齐。** 50 个主题分别在各自后端学出，比较只用 ARI/AMI。
3. **评分覆盖 7 个届次**，来自公开存档 227,128 条观测，不是实时接口。ICML 2024 与 NeurIPS 2026 保持缺失，不按 0 分处理。各届量表不同（1–10 / 0–10 / 1–5 / 1–6），跨年份不合并。
4. **条件录用率只有 ICLR 三届。** 三会统筹所需的独立完整决定队列未建立，该指标为 `not_estimable`。NeurIPS 2026 覆盖 61.8%，按预设门槛排除出 2024–2025 横向矩阵。50 个主题标签仍是自动关键词，`topic_review.csv` 全部 `pending`，未经人工命名。


程序分别保存官网录用成果、带原分母的会议规模、公开投稿/评审。不会从录用节目册推断全部投稿分布、主题接收率或选题录用优势。实际受阻通道、缺口、论文数和验收状态以最终 `RUN_RESULTS.md`、`output/validation.json` 为准。

## 安装与执行

在本项目根目录中使用Python 3.12：

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install -r docs/requirements.lock.txt
python -m pip install -e '.[semantic,fast-http]'
python scripts/run.py --help
python scripts/run.py --config configs/latest.json --output output collect
python scripts/run.py --config configs/latest.json --output output prepare
python scripts/run.py --config configs/latest.json --output output backfill
python scripts/run.py --config configs/latest.json --output output prepare --with-details
python scripts/run.py --config configs/latest.json --output output model --backend lsa
ORT_DISABLE_TELEMETRY=1 python scripts/run.py --config configs/semantic.json --output output model --backend onnx
python scripts/compare_models.py --output output
python scripts/run.py --config configs/latest.json --output output analyze --backend lsa
python scripts/run.py --config configs/semantic.json --output output analyze --backend onnx
python scripts/run.py --config configs/semantic.json --output output report --backend onnx
python scripts/run.py --config configs/latest.json --output output validate
PYTHONPATH=src python -m unittest discover -s tests -v
python -m pip wheel --no-deps --no-build-isolation . --wheel-dir dist/wheels
python scripts/build_release.py --output output --dist dist
```

详情失败重试使用 `backfill --retry-failed`，保留失败历史；不会自动重试平台验证或身份冲突。固定权重第一次运行会下载，记录SHA256并排除在发行包之外。`scripts/warm_embeddings.py` 可在详情补采期间预先缓存当前可用文本的真实语义向量；仅编码，不声称主题模型已完成。

## 输出与追踪

- `output/raw/http/`：成功与失败响应的压缩原文、URL、UTC时间、状态、大小、SHA256。
- `output/bulk/`：原始事件、逐届论文、隔离记录与公开评审。
- `output/details/`：原始计划、尝试、补丁、目录差异、失败URL及剩余量。
- `output/processed/`：统一JSONL/CSV、覆盖和质量报告；作者关键词与模型主题词分开。
- `output/models/{lsa,onnx}/`：语料、向量、逐论文主题、主题词、代表论文、人工命名工作表及模型清单。
- `output/analysis/`：逐来源官方规模、实采差值、主题份额、百分点变化、覆盖筛选和评分可计算状态。
- `output/report.html`：单文件中文报告，内嵌全量论文和统计下载，浏览样本最多5000行。
- `dist/`：阶段检查点、最终源码/数据包、逐文件SHA256和CRC验收。

参见 [重现说明](docs/REPRODUCE.md)、[数据契约](docs/DATA_CONTRACT.md)、[来源口径](docs/OFFICIAL_SOURCES.md) 和 [验收约定](docs/ACCEPTANCE.md)。

## 已知边界

本轮OpenReview首次notes请求返回HTTP403，已停止该通道；离线测试覆盖API1/2、分页与真实邀请量表的恢复能力，不表示实际评审采集成功。官网导航不能证明单篇赛道；2026 NeurIPS目录新增条目缺乏逐篇证据时保持unknown。自动主题词、相似度、silhouette与模型一致性都不是主题正确率或研究新颖性证明。

代码采用MIT许可；论文文本、会议资源和预训练权重保留原权利。项目参考AI-Paper-Trends的问题意识，未复制其实现，也未沿用其他会话的数据数量。
