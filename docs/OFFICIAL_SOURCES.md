# 会议规模来源与统计口径

本表来自本轮实际访问。抓取 UTC 时间、响应大小、SHA256 及压缩原文路径均保留在 `output/raw/http/`；PDF 按页提取文本和对应原文元数据保留在 `output/source_evidence/`。规范化统计输入为 `configs/official_statistics.json`；分析阶段复制为逐模型统计表，并与实际主会名单独立对账。这里的规模不从节目册论文数反推。

| 会议届次 | 来源及层级 | 投稿口径 | 录用数 | 来源公布接收率 | 关键限制 |
|---|---|---|---:|---:|---|
| ICLR2024 | [官网FactSheet](https://media.iclr.cc/Conferences/ICLR2024/ICLR2024-Fact_Sheet.pdf) | 7262 submissions | 2260 | 31% | 未明确raw/valid，率取整 |
| ICLR2025 | [官网FactSheet](https://media.iclr.cc/Conferences/ICLR2025/ICLR2025_Fact_Sheet.pdf) | 11603 submissions | 3704 | 32% | 未明确raw/valid，率取整 |
| ICLR2026 | [官网Final FactSheet](https://media.iclr.cc/Conferences/ICLR2026/ICLR2026_Fact_Sheet.pdf) | 19525 submissions | 5357 | 27% | 当前文档没有可核验发布日期；与回顾差2篇 |
| ICLR2026 | [会议主席回顾，2026-03-31](https://blog.iclr.cc/2026/03/31/a-retrospective-on-the-iclr-2026-review-process/) | 19525 valid format-compliant | 5355 | 27.4% | 779 desk reject、5042撤稿、13763最终accept/reject；reviewed保持缺失 |
| ICML2024 | [官网FactSheet](https://media.icml.cc/Conferences/ICML2024/ICML2024_Fact_Sheet.pdf) | 未列分母 | 超过2600 | 27.5% | accepted=null，单列下界2600，避免伪精确 |
| ICML2024 | [RIKEN AIP机构官方转述，更新2024-06-11](https://aip.riken.jp/news/icml2024/?lang=en) | 9473 submissions | 2609 | 27.5% | 机构级，不能称会议原始公告 |
| ICML2025 | [官网FactSheet](https://media.icml.cc/Conferences/ICML2025/ICML2025_Fact_Sheet.pdf) | 未列分母 | 3260 main | 27% | 不由取整率反推投稿数 |
| ICML2025 | [RIKEN AIP机构官方转述，更新2025-06-10](https://aip.riken.jp/news/icml2025/) | 12107 submissions | 3260 | 26.9% | 机构级，有更细率和投稿数 |
| ICML2026 | [官网FactSheet](https://media.icml.cc/Conferences/ICML2026/ICML2026_Fact_Sheet.pdf) | 24661 main conference submissions | 6552 | 未公布 | 仅另列计算率；不捏造公布率 |
| ICML2026 | [RIKEN AIP机构官方转述，2026-05-24](https://aip.riken.jp/news/icml2026/) | 23918 submissions | 6352 | 26.6% | 时间/范围与当前官网不同；原文未解释差额，清单包括Position |
| NeurIPS2024 | [官网FactSheet](https://media.neurips.cc/Conferences/NeurIPS2024/NeurIPS2024-Fact_Sheet.pdf) | 15671 main submissions | 4037 main | 25.8% | D&B460/1820独立，合并4497/17491不作主会分母 |
| NeurIPS2025 | [官网FactSheet](https://media.neurips.cc/Conferences/NeurIPS2025/press/NeurIPS2025-Fact_Sheet.pdf) | 21575 submissions | 5290 | 未公布 | 数量由主席回顾明确为主会；不从PDF捏造公布率 |
| NeurIPS2025 | [会议主席回顾，2025-09-30](https://blog.neurips.cc/2025/09/30/reflections-on-the-2025-review-process-from-the-program-committee-chairs/) | 21575 main valid | 5290 | 24.52% | 不推断reviewed数量 |
| NeurIPS2026 | [RIKEN AIP机构官方转述，2026-10-14](https://aip.riken.jp/news/neurips2026/?lang=en) | 30709 main valid with PDF | 7900 | 25.7% | 原文7900带星号且未找到解释；目前仅机构级 |

截至本轮访问，[NeurIPS2026官网Press页](https://neurips.cc/Conferences/2026/Press)仅链接2025及更早FactSheet。通过会议官网和会议博客检索未检得主会2026原始规模公告，故使用机构官方转述并明确层级。没有把未检得来源写成没有该来源存在的证明。

`raw_submissions`、`valid_submissions`、`reviewed`仅在原文明确对应含义时填值。原文只称submissions的数放 `reported_submissions`；其是否包含后来撤稿或直接拒稿未知。`source_date=null`表示没有核验到来源发布日期，与本轮真实 `collected_at` 不同。`computed_rate_percent`是指定来源录用数除指定投稿数的算术值，不等同于 `official_rate`。

ICLR2026回顾的27.4%与5355/19525一致，和5355/13763不一致。后者仅是已作accept/reject决定子集的比例，不替换会议公布率。13763不等于所有进入审稿的论文数。两份官方录用数5355与5357均保留；本项目不能自行判定哪一个才是唯一正确数。

三会同年热度矩阵以已观察主会录用名单为分母。90%筛选使用可比较精确登记来源中的最大录用数，避免挑最小分母使覆盖看起来完整。任一会议未观察到主会论文、没有精确参照、或覆盖低于90%，该年不进入三会矩阵。机构级参照在字段中保留来源层级。此门槛只筛明显缺口，不证明完整性；不证明公开投稿/决定队列完整。

公开评审为空时评分表只有表头，并给出不可计算原因。程序不把未知决定当拒稿，永远不从节目册或自愿公开拒稿样本估计主题接收率。若未来具备完整决定队列，必须先单独完成队列证明和每篇主题归属核验，再扩展实现；目前的 `conditional_acceptance_rate` 保持null。

额外赛道证据：[ICML2024 Position Paper征稿说明](https://icml.cc/Conferences/2024/CallForPositionPapers)要求标题以 `Position Paper:` 开头。该政策原文和快照已保存；实际页面如采用另一前缀，应另查对应单篇或赛道证据，不能悄然扩张规则。

来源表另存official_rate_precision_digits与official_rate_rounding，保留公布百分数的小数位，不能把取整的31%当作精确31.000%。approximate字段主要描述数量是否为估计/下界；公布率的显示精度独立记录。
