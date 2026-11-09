# ICLR 公开投稿：向冻结主题空间的投影

这组脚本是主线之后的补充轮，回答主线报告没能回答的问题：**50 个主题在公开投稿队列里的评分与条件接收率**。

主线报告的评分表来自本轮结果（`data/analysis/scores.csv`），ICLR 三届的条件接收率见 `reports/iclr_topic_rates_report.html`。

## 做法

不重训模型、不改写原 37,662 篇的归属。把 38,890 篇公开投稿（录用 + 拒稿 + 撤稿）按同一 encoder 与同一组未归一化中心做欧氏最近中心预测，即**向已冻结的主题空间外推**，再按论文内求均值、同届同主题等权汇总。

## 执行顺序

```bash
# 1. 冻结投影（38,890 篇 -> 50 主题）
python frozen_projection.py

# 2. 校验中心与原始批次身份一致（复现原 35,992+1,670 两阶段编码）
python confirm_centroid_identity.py
python check_original_batch_context.py

# 3. 统计评分与条件接收率
python analyze_topic_rates.py
python finish_topic_analysis.py

# 4. 生成报告与打包
python build_topic_report.py
python package_topic_results.py

# 测试
python -m pytest test_topic_rates.py
```

## 输入

需要主线产物中的 `models/onnx/centroids.npy`、`topics.json`、`assignments.jsonl`，以及公开评审归档（`public_review_scores_and_evidence.zip` 内的 `reviews.csv`）。完整度校验依赖 `corpus_fingerprints.json`。

## 口径

- 主指标分母是**当前公开录用 + 公开拒稿**，剔除撤稿与直接拒稿；CSV 另给"已发出的决定 note"与"全部公开投稿"两种分母，三者不可混用。
- 各届量表不同：ICLR 2024/2025 `1–10`、2026 `0–10`；ICML 2025 `1–5`、ICML 2026 `1–6`；NeurIPS 2024 `1–10`、2025 `1–6`。跨年份不合并。
- 新分批下 1000 篇分层样本归属一致率 96.4%，**未达预设的严格新分批标准**，失败记录保留在 `fresh_batch_validation.*`。因此这些数字是探索性主题统计，不是精度保证。
- 该证明只针对公开快照队列，不等于官方全体有效投稿队列，也不能当作会议官方接收率。
