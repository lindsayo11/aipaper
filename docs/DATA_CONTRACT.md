# 数据接口约定

本次新运行，不能继承执行计划末节中的历史数量。

公共 IO 位于 `ai_trends.common`：read_json/read_jsonl、write_json/write_jsonl/write_csv、utcnow、sha256、HttpClient。

processed/papers.jsonl 每篇含 paper_id,venue,year,title,abstract,authors(list),keywords(list),source,source_id,source_url,openreview_id,track,track_evidence,decision,presentation(list),text_version,collected_at,metadata(dict)。同届 ID 不跨年合并。评分输入 processed/reviews.jsonl 保留 review_id,paper_id,rating_raw,rating,confidence,scale_min,scale_max,score_stage,source_url,updated_at。

模型输入筛选 track=main、decision=accepted、title/abstract 非空。仅标题摘要作为文本。模型输出 models/{lsa|onnx}/assignments.csv 与 .jsonl（paper_id,topic_id,similarity,outlier）、topics.json（topic_id,keywords,size,representatives）、manifest.json（输入/模型哈希、配置和诊断）。代表论文项含 paper_id,title,source_url,similarity。所有合格论文进入同一共享主题模型。

分析输出 analysis/{backend}/ 下，official_statistics.json/csv 可含同届多来源，严格区分原分母。reconciliation.csv、topic_trends.csv、topic_changes.csv、heatmap.csv、scores.csv、decision_samples.csv、analysis_manifest.json。没有独立完整决定队列不发布主题接收率。

报告入口 report.build_report(config, output, backend)；模型入口 modeling.run_model(config, output, backend)；分析入口 analysis.analyze(config, output, backend)。

采集、清洗、详情、两模型、分析、报告和验收入口均已集成；每个实际运行阶段的完成或受阻状态独立记录，不以可调用入口冒充实跑完成。

CSV采用UTF-8 BOM；列表/字典列使用JSON文本。为防止表格软件把源文本当作公式，可能触发公式的字符串以单引号转义；规范原文及缺失值请以JSONL为准。数值列不使用该字符串转义。
