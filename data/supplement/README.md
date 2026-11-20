# 补充轮结果表与图

8 组结果表和 4 张图，取自补充轮交付件 `项目数据分析补充结果.xlsx`（292,428 B，SHA256 `52907d69…`），原样导出、数值不改写。导出与复算脚本：`scripts/export_supplement_tables.py`。

## 表

| 文件 | 行数 | 回答什么 |
| --- | ---: | --- |
| `tables/sample_scale.csv` | 9 | 逐届规范化记录、主会分析样本、参考录用数与覆盖比例；2026 三会因 NeurIPS 覆盖 61.84% 不纳入同期比较 |
| `tables/field_completeness.csv` | 10 | 标题/摘要/作者/关键词/OpenReview 标识在全部 43,702 条与 37,662 篇分析样本中的缺失 |
| `tables/abstract_length.csv` | 9 | 逐届摘要英文词数的均值、中位数、四分位与 P95 |
| `tables/topic_change_common_years.csv` | 50 | 三会合并后 2024→2025 的主题占比变化（百分点）、篇数变化、三会等权变化 |
| `tables/topic_venue_difference.csv` | 50 | 2025 年三会各自的主题占比与最高占比会议 |
| `tables/topic_year_detail.csv` | 450 | 9 届 × 50 主题的论文数与主题占比（含分母） |
| `tables/score_coverage.csv` | 7 | 有公开评分的 7 个届次：主会样本、评分表样本合计、未计入数、量表 |
| `tables/iclr_public_submission_rates.csv` | 150 | ICLR 三届 × 50 主题的公开投稿、录用/拒稿/撤稿/直接拒稿与条件接收率 |

## 图

`reports/figures/` 四张，均为交付件内嵌原图：

- `fig1_venue_year_sample.png`：各会议年度进入分析的论文数（2026 NeurIPS 标注 61.84% 覆盖）
- `fig2_abstract_length_distribution.png`：37,662 篇摘要词数分布，中位数 179 词
- `fig3_topic_share_change_2024_2025.png`：三会合并样本的主题占比变化，思维链推理 +1.37 pp 居首
- `fig4_topic_venue_difference_2025.png`：2025 年主题占比的会议差异（3D 高斯泼溅重建在 NeurIPS 2.53%、ICLR 2.35%、ICML 0.40%）

## 复算状态

`verification.json` 记录逐格复算结果（关键列全部逐行比对）：

| 表 | 状态 | 比对规模 |
| --- | --- | --- |
| 数据规模 | 一致 | 9 行 × 3 列 |
| 字段完整性 | 一致 | 10 行 × 2 列 |
| 摘要长度 | 口径不同 | 样本数一致；词数统计整体高 1.34–2.44 词/篇 |
| 共同年份变化 | 一致 | 50 行 × 5 列（含占比变化逐值） |
| 会议主题差异 | 一致 | 50 行 × 4 列 |
| 主题年度明细 | 一致 | 450 行 × 2 列 |
| 评分覆盖 | 一致 | 7 行 × 4 列（对齐 `data/scores/`） |
| ICLR公开投稿 | 一致 | 150 行 × 6 列（对齐 `iclr_topic_rates_results.zip`） |

**摘要长度的差异**：交付表的分词实现没有随项目保留。用仓库内的空白分词复算，样本数逐届相同，但均值高 1.34–2.44 词（不是常数偏移，随论文里连字符/斜杠密度变化）。因此该表按交付口径保留、不复算，也不改写数值——它是本次交付里唯一不能逐位重算的表。

## 再生成

```bash
python scripts/export_supplement_tables.py --xlsx <项目数据分析补充结果.xlsx>   # 导出 + 复算
python scripts/export_supplement_tables.py --verify-only                        # 只复算
```

## 边界

- 这些是录用成果的分布，不能反推投稿分布，也不能推出"选这个主题更容易中"。
- 主题编号只在本后端（onnx / MiniLM）内有意义，跨模型不可对齐；命名只描述主题内容。
- 2026 只做单届描述，不进入 2024–2025 的三会横向比较。
