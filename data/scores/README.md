# 评分对账（data/scores）

一句话：主题评分表合计 **30,134** 篇，`analysis_manifest.json` 原记录 **30,075**，相差 **59**。这里放逐条对账的结论与两侧清单——差额不是漏采或重复，是两种连接口径的净差。

```
30,134（评分表，标题+OpenReview ID 归一匹配）
= 30,075（严格 paper_id 直连）
+    162（模型侧是来源页哈希，按 OpenReview ID 对齐后才连上）
-    103（有评审观测但标题冲突被隔离，或匹配后无可用评分）
```

- **+162**：ICLR 2025 109 篇、NeurIPS 2025 53 篇。模型侧 `paper_id` 形如 `ICLR-2025-src-0c4cfb…`，评审档案按 `venue-year-or-<OpenReview ID>` 记录，严格 ID 直连会漏计。
- **−103**：标题与档案不一致被隔离（ICLR2025 8、ICLR2026 1、ICML2025 6、ICML2026 39、NeurIPS2024 1、NeurIPS2025 48），或匹配后无评分。

## 文件

| 文件 | 内容 |
| --- | --- |
| `score_reconciliation.json` | 完整结论：逐届分解、主题级复算、证据包 SHA256 |
| `score_counts_by_venue_year.csv` | 逐届模型论文数、账本数、严格 ID 数、净差、观测数、量表 |
| `gap59_added_alternate_id.csv` | + 侧的 162 行：模型 paper_id、档案 id、标题、篇数与均分 |
| `gap59_removed_quarantined.csv` | 103 行：隔离原因、档案标题、观测数 |
| `count_definitions.csv` | 每个计数的定义、总体与复算位置 |

## 逐条账本在哪

30,134 行的 `score_ledger/paper_scores.csv`（13 MB）随证据包分发，不在版本库：Release [`scores-2026-11-20`](https://github.com/lindsayo11/aipaper/releases/tag/scores-2026-11-20) 的 `public_review_scores_and_evidence.zip`（26,194,296 B，SHA256 `80d19e9a1f45ad5aa93724fb9dbcc1406e3541412e7ba1ea01ca68cb0b353874`）。

解压后：

```bash
python reconciliation/verify.py            # 包内自检：行数、逐条均值、量表、差额恒等式
```

仓库内复算（会额外对齐 `data/analysis/scores.csv` 的 350 行）：

```bash
python scripts/verify_score_ledger.py --detail
```

## 两个容易看错的地方

- **63,391 条观测没有原始评审 ID**：来自公开规范化镜像（`not_preserved_by_normalized_mirror`），账本用 `observation_id` 定位，评分值不受影响；每行的 `n_original_review_ids` 给出保留原始 ID 的条数。
- **量表逐届不同**（1—10 / 0—10 / 1—5 / 1—6），不跨年份合并；ICML 2024、NeurIPS 2026 无公开评分，保持缺失，不按 0 分处理。
