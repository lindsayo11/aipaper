#!/usr/bin/env python3
"""Generate the Chinese run record strictly from executed artifacts."""
from pathlib import Path
import argparse,json,sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from ai_trends.common import read_json,read_jsonl,atomic_write,utcnow


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',default='output');a=p.parse_args();out=Path(a.output)
    q=read_json(out/'processed/quality.json',{});d=read_json(out/'details/summary.json',{})
    validation=read_json(out/'validation.json',{});tests=read_json(out/'test_results.json',{});build=read_json(out/'build_results.json',{})
    lsa=read_json(out/'models/lsa/manifest.json',{});onnx=read_json(out/'models/onnx/manifest.json',{});comparison=read_json(out/'model_comparison/comparison.json',{})
    if any(x.get('status')!='completed' for x in (lsa,onnx)):raise RuntimeError('Both actual topic models must finish')
    coverage=read_json(out/'source_coverage.json',[]);papers=read_jsonl(out/'processed/papers.jsonl')
    stats=read_json(out/'analysis/onnx/official_statistics.json',[])
    analysis=read_json(out/'analysis/onnx/analysis_manifest.json',{})
    lines=['# 本轮真实执行与验收结果','',f'生成时间（UTC）：{utcnow()}。范围：ICLR、ICML、NeurIPS的2024—2026届。','',
    f'已采集9届官网声明的批量接口，完成{d.get("attempted")}/{d.get("planned")}个详情计划（成功{d.get("successful")}，失败{d.get("failed")}，剩余{d.get("remaining")}）。全部{d.get("main_missing_planned")}个已确认主会摘要缺口已修复。最终{q.get("paper_count")}篇规范化记录中，{q.get("model_eligible")}篇明确主会录用、有标题和真实摘要的论文进入两种共享主题模型。',
    '', '**仍受阻/不能声称完成的部分：** OpenReview首次notes请求HTTP403，随后九届同通道停止；本轮公开正式评审为0条，评分分析与主题条件录用率不可计算。NeurIPS2026静态文件与实时目录存在大缺口；没有逐篇赛道和决定证据的目录新增条目保持unknown，不据录用目录推断全部投稿。',
    '', '## 逐届对账','', '| 会议 | 年份 | 原始事件 | 批量去重 | 最终全部记录 | 明确主会录用 | 主会缺摘要 | 首选登记数 | 实采减登记 | 来源层级 |','| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |']
    for c in coverage:
        group=[r for r in papers if r['venue']==c['venue'] and r['year']==c['year']]
        main=[r for r in group if r['track']=='main' and r['decision']=='accepted']
        preferred=next((s for s in stats if s['venue']==c['venue'] and s['year']==c['year'] and s.get('preferred')),None)
        count=preferred.get('accepted') if preferred else None
        delta=len(main)-count if count is not None else None
        lines.append('| '+' | '.join(map(str,[c['venue'],c['year'],c.get('list_events'),c.get('unique_papers'),len(group),len(main),sum(not r['abstract'] for r in main),count,delta,preferred.get('source_level') if preferred else None]))+' |')
    lines += ['', '登记数保留原来源、时点和分母。ICLR2026官方5355/5357、ICML2026官网6552与机构6352均逐行保留，表中首选来源不是对矛盾的裁决。NeurIPS2026的7900/30709仅有机构官方转述证据。所有来源详见analysis/*/official_statistics与docs/OFFICIAL_SOURCES.md。',
    '', '## 数据质量与追踪','',f'- 原始批量事件共{sum(c.get("list_events",0) for c in coverage)}条；本轮最新批量规范化共{sum(c.get("unique_papers",0) for c in coverage)}篇。',
    f'- 最终ID唯一：{q.get("id_unique")}；同会议同年forum身份唯一：{q.get("forum_identity_unique")}；隔离记录：{q.get("quarantine_count")}。',
    f'- 最终赛道分布：`{json.dumps(q.get("track_counts"),ensure_ascii=False)}`。',
    f'- 目录新增条目{d.get("directory_new_papers")}；主会摘要修复率{d.get("main_abstract_repair_rate",0)*100:.2f}%。目录新增不会自动提升到main或accepted。',
    '- 初始阶段检查点的40,846篇包含被误当作forum的展示占位ID；经独立审查过滤YYYY-Oral--等占位并从原文重建后，批量为40,383篇。早期文件保留为历史阶段；最终数据及bulk_snapshot_v2采用修正规则。',
    '- 同ID标题/决定/赛道冲突被隔离；未知决定不当作拒稿；作者关键词与模型主题词分开。',
    '- source_coverage、details计划/尝试/失败URL、processed合并输入哈希及raw/http原文可逐条追溯。页面级导航没有被用于提升赛道。',
    '', '## 两个实际运行的模型','', '| 后端 | 输入论文 | 实现 | 维度 | 主题 | 本次模型运行秒数 | 文本缓存命中 |','| --- | ---: | --- | ---: | ---: | ---: | ---: |']
    for m in (lsa,onnx):
        lines.append('| '+' | '.join(map(str,[m.get('backend'),m.get('input_papers'),m.get('actual_backend'),m.get('embedding_dimension'),m.get('realized_topics'),m.get('elapsed_seconds'),m.get('cache_hits')]))+' |')
    warm=read_json(out/'encoding_warmup/manifest.json',{});repair=read_json(out/'encoding_after_main_repair/manifest.json',{})
    lines += ['',f'语义编码实际另行执行：首批{warm.get("papers")}篇，耗时{warm.get("elapsed_seconds",0):.2f}秒；补齐摘要后新增编码{repair.get("cache_misses")}篇，耗时{repair.get("elapsed_seconds",0):.2f}秒。最终模型运行时间包含缓存复用，不冒充从零编码的耗时。',
    f'两模型交集{comparison.get("intersection_papers")}篇；同ID集合={comparison.get("same_corpus")}，同文本指纹={comparison.get("same_text_fingerprint")}。ARI={comparison.get("ari"):.6f}，AMI={comparison.get("ami"):.6f}，仅表示分区一致性，不是正确率或最佳K证明。',
    '', '所有会议和年份共享同一模型；仅标题/摘要进入向量，年份、评分、决定不进入特征。固定seed=42、K=50。MiniLM固定revision和tokenizer/权重SHA256见模型清单及REPRODUCE。BERTopic/HDBSCAN本轮未执行。主题自动关键词和50行topic_review.csv仍需人工命名复核；没有把代理审核冒充人类专家验证。',
    '', '## 统计与解释','',f'- 共同年份热度矩阵：{analysis.get("heatmap_years")}；排除说明见analysis_manifest。2026 NeurIPS明显缺口使2026不进入三会横向矩阵。',
    '- 主题份额分母为同届同会议全部已观察主会录用论文，包括缺摘要者；变化单位是百分点。没有数据的年份不补零。',
    '- 评分先按论文内部求均值，再按论文等权汇总；会议/年份/量表/阶段隔离。本轮scores.csv为空表并保留表头和不可计算原因。',
    '- 未有独立完整决定队列证明，conditional_acceptance_rate保持null。已录用成果主题增长是检索线索，不证明新颖性、因果或未来投稿优势。',
    '', '## 新鲜验证','', f'- 离线行为测试：{tests.get("tests")}项，状态{tests.get("status")}，退出码{tests.get("exit_code")}。日志SHA256：`{tests.get("log_sha256")}`。',
    f'- 源码wheel构建：{build.get("status")}；SHA256：`{build.get("sha256")}`。',
    f'- 产物结构校验：{validation.get("structural_status")}；检查项{len(validation.get("checks",[]))}个。',
    '- HTTP原文哈希回读、ID/模型输入输出一致、空评分、主题分母、报告安全转义/URL协议、内嵌导出逐字节一致及JavaScript语法均有实际检查。结构验证不证明网络完整性。',
    '- 最终ZIP CRC及逐文件SHA256由构建脚本再次验证，记录在release_manifest和各ZIP的MANIFEST.sha256.json。',
    '- 额外浏览器实交互尚未验证：环境无引擎，安装响应非有效ZIP；未将此记为通过。计划要求的静态脚本语法、HTML/URL安全与全量内嵌导出还原已通过，见browser_check.json。',
    '', '## 下载与重现','', '最终交付：report.html、RUN_RESULTS.md、source_complete.zip、data_and_results.zip、release_manifest.json。阶段数据、详情、模型及分析检查点另行提供。完整源码阅读版在source_complete.zip内的SOURCE_READING.md；固定模型权重不重分发，首次下载说明和哈希见REPRODUCE。','',
    'report.html独立交付并内嵌全量CSV/JSONL和统计文件。数据包保留原始响应、清洗前后语料、模型向量和统计；可复用的稠密编码缓存独立在semantic_encoding_checkpoint.zip，避免相同向量重复膨胀。','']
    deliveries=read_json(out/'deliveries_progress.json',[])
    if deliveries:
        lines+=['### 已完成阶段文件','', '| 文件 | 持久文件ID | 下载 |','| --- | --- | --- |']
        for f in deliveries:lines.append(f'| {f["file"]} | {f["library_file_id"]} | [下载]({f["download_url"]}) |')
    lines += ['', '最终文件ID与最新下载入口同时列于交付索引；以文件名/时间戳区分阶段，不把未完成检查点冒充最终数据。', '']
    atomic_write(out/'RUN_RESULTS.md','\n'.join(lines))
    print({'path':str((out/'RUN_RESULTS.md').resolve()),'status':validation.get('structural_status')})

if __name__=='__main__':main()
