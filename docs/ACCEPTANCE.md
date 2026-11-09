# 验收约定与失败边界

| 要求 | 新鲜证据 | 完成判定 |
| --- | --- | --- |
| 九个官网批量接口 | source_coverage.json、原文 gzip、逐届 checkpoint | 明确每届success/partial/blocked/failed；并不证明全部投稿完整 |
| 分页完整、原文可追踪 | 离线分页边界测试、逐页SHA256、实际count和next | count对上且next终止；每条事件追溯自己的源页 |
| 详情补采 | details/plan.jsonl、attempts、summary、failed_urls | 所有计划均有终态；成功、缺摘要、冲突、失败单列 |
| 保守清洗 | processed/quality.json、quarantine、边界测试 | 唯一ID；标题/forum冲突不提供摘要；决定/赛道冲突保持unknown |
| 两种实际模型 | models/lsa和onnx/manifest、assignments、模型对照 | 两manifest completed；输入与输出ID完全一致 |
| 统计分母 | analysis/*表格、official_statistics、来源原文 | 原始规模口径不与样本混合；缺失不填0；评分论文等权 |
| 离线报告 | report.html、语法检查、导出回读哈希、XSS边界测试 | 无外部资源；源文本/URL安全；内嵌导出逐字节匹配 |
| 最终发行 | release_manifest、ZIP内部MANIFEST.sha256.json | 源码构建、ZIP CRC和每个成员SHA256通过 |

本轮若公开OpenReview通道受阻，将该子任务标为blocked，而非已完成评审分析。只有将来具有独立完整决定队列证明，且每篇决定论文均可归主题时，才允许发布主题条件录用率。主题增长、相似度、ARI/AMI、silhouette都不是研究新颖性、因果关系或未来录用率。

本轮官方数量与实采差异以RUN_RESULTS.md和reconciliation表为准。即使差异为0也不证明全部投稿/评审队列完整。官网目录新增但缺乏逐篇赛道和决定证据的论文，保持unknown；官网导航不能提升到main。
