"""Create small direct-download artifacts and a separate reusable vector cache."""
import csv
import hashlib
import io
import json
import pathlib
import shutil
import zipfile

ROOT=pathlib.Path(__file__).resolve().parent
WORK=ROOT.parent
RESULTS=ROOT/'results'
DIST=WORK/'deliverables_topic_rates'


def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        while b:=f.read(1024*1024):h.update(b)
    return h.hexdigest()


def zip_entries(target,entries,text_entries=None,jsonl_counts=None,csv_counts=None):
    temp=target.with_name(target.name+'.building')
    manifest=[]
    with zipfile.ZipFile(temp,'w',zipfile.ZIP_DEFLATED,compresslevel=6,allowZip64=True) as z:
        for path,name in entries:
            h=hashlib.sha256();size=0
            with path.open('rb') as src,z.open(name,'w',force_zip64=True) as dst:
                while b:=src.read(1024*1024):dst.write(b);h.update(b);size+=len(b)
            manifest.append(dict(path=name,bytes=size,sha256=h.hexdigest()))
        for name,text in (text_entries or {}).items():
            body=text.encode();z.writestr(name,body)
            manifest.append(dict(path=name,bytes=len(body),sha256=hashlib.sha256(body).hexdigest()))
        z.writestr('MANIFEST.sha256.json',json.dumps(manifest,ensure_ascii=False,indent=2))
    with zipfile.ZipFile(temp) as z:
        assert z.testzip() is None
        for r in manifest:
            h=hashlib.sha256()
            with z.open(r['path']) as f:
                while b:=f.read(1024*1024):h.update(b)
            assert h.hexdigest()==r['sha256'],r['path']
        for name,count in (jsonl_counts or {}).items():
            with z.open(name) as f:found=sum(1 for line in f if json.loads(line))
            assert found==count,(name,found,count)
        for name,count in (csv_counts or {}).items():
            with z.open(name) as f:found=sum(1 for _ in csv.DictReader(io.TextIOWrapper(f,encoding='utf-8-sig',newline='')))
            assert found==count,(name,found,count)
    temp.replace(target)
    return dict(name=target.name,bytes=target.stat().st_size,sha256=sha(target),files=len(manifest)+1,
                crc_verified=True,per_file_sha256_verified=True)


def main():
    DIST.mkdir(exist_ok=True)
    projection=json.loads((RESULTS/'projection_manifest.json').read_text())
    verification=json.loads((RESULTS/'cohort_verification.json').read_text())
    tests=json.loads((RESULTS/'test_results.json').read_text())
    assert verification['status']=='passed' and tests['successful']
    for src,dest in [(RESULTS/'iclr_topic_rates_report.html',DIST/'iclr_topic_rates_report.html'),
                     (RESULTS/'iclr_topic_metrics_150.csv',DIST/'iclr_topic_metrics_150.csv')]:
        tmp=dest.with_name(dest.name+'.copying');shutil.copyfile(src,tmp);tmp.replace(dest)
    readme='''# ICLR 2024—2026 原 50 主题的公开队列统计

先打开 `iclr_topic_rates_report.html`，或直接查看 `results/iclr_topic_metrics_150.csv`。

## 本次完成

- 38,890 条公开投稿全部有主题；150 行“主题 × 届次”评分、规模与比例。
- 主比例的分母为当前公开录用＋公开拒稿，共 28,043 篇；每篇都与正式 Decision note 同结果。
- 三届公开 ID 集合在两个独立存档间完全一致。该证明只针对公开快照队列，不是官方全体有效投稿队列的证明。
- 未重训或重跑 LSA／KMeans。原 37,662 篇归属表未改写。
- 7,331 条文本完全相同，复用原归属；27,572 条新增投稿、3,987 条修订文本补算向量。

## 重要口径

主指标是当前公开录用数 /（当前公开录用数＋公开拒稿数），剔除撤稿与直接拒稿。CSV 另给“已发出的决定 note”及“全部公开投稿”口径，三者不能混用，更不能替代会议官方有效投稿接收率。缺失状态不当作拒稿。

评分先在论文内求均值，再在同届同主题按论文等权平均；2024／2025 使用 {1,3,5,6,8,10}，2026 使用 {0,2,4,6,8,10}。年份和量表不混合。无评分保持缺失；0 分在 2026 合法。

主题空间仍是原已录用语料学出的 50 个主题。拒稿等新文本是向这个空间的外推，不是对全体投稿重新无监督拟合。自动关键词仍需人工命名和解释，不把主题热度当作新颖性、因果效应或未来投稿胜算。

## 量化分批敏感性（保留失败记录）

中心形状、原语料文本指纹、模型 revision、tokenizer 和权重哈希均匹配。新分批下 1000 篇分层样本归属一致率为 96.4%，250 篇原代表论文为 98.8%；预设严格新分批标准没有通过，记录保留在 `fresh_batch_validation.json/csv`。

复原原 35,992＋1,670 两阶段编码中的相关批次后，全部 39 个不一致案例和各主题一个对照（共 89 篇）均复现原标签，相似度平均绝对误差约 1.54e-8。这一诊断确认上传中心文件与原模型匹配，不能冒充新的独立准确率评估，也没有把最初失败改记为通过。

本次以固定顺序、原量化模型和原未归一化中心作欧氏最近中心预测；原表保留。编码序列指纹及缓存命名空间绑定输入顺序。新分批的数值差异说明结果应作为探索性主题统计；CSV 同时提供离群排除和复用可核对标题的旧标签的敏感性口径。9 条历史标题冲突不重新用于旧标签敏感性表，改用公开文本的新外推标签。

## 文件与下载

- `results/iclr_topic_metrics_150.csv/json`：150 行主统计，包含录用、拒稿、撤稿、直接拒稿、分母、评分和敏感性列。
- `projection_20261028/results/iclr_public_topic_assignments.csv/jsonl`：38,890 篇逐论文归属、分数、决定与来源链接；JSONL 同时包含全部摘要。
- `results/iclr_cohort_summary.csv`：三届总体分母和状态计数。
- `results/iclr_topic_year_changes.csv`：主题份额与条件比例的年际变化。
- `results/cohort_verification.json`：公开队列、正式决定和主题分母的验证记录。
- `results/model_compatibility_validation.json`、`fresh_batch_validation.*`、`original_batch_context_check.*`：全部技术诊断。
- `results/test_results.*`：统计公式与真实数据测试。
- `upload/centroids.npy`：用户提供的原中心副本，未改写。
- `recovered_existing/models/onnx/`：已验证的原主题词、归属和模型清单。
- `source_existing/`：原项目代码／配置，作为编码和文件格式参考；未改动原模型。
- `projection_20261028/*.py`：本次外推、统计、报告和测试代码。

主结果包包含全部 ICLR 全文元数据、逐篇归属与运行代码；较大的向量缓存和上一轮评分证据另行提供。报告不需要外部网页或 CDN，即可离线筛选和导出主要 CSV。ICML 2024、NeurIPS 2026 的可靠评分仍未取得；ICML／NeurIPS 的未公开拒稿仍不能补成全体主题接收率。

## 重现

按包内目录放置文件后，使用 Python 3.12 与 `projection_20261028/requirements.txt` 中的版本。`python projection_20261028/test_topic_rates.py` 可直接检查已有结果。`python projection_20261028/analyze_topic_rates.py` 优先读取主包内的 `iclr_public_topic_assignments.jsonl`；如只保留 CSV，也支持核验后重算。随后运行 `python projection_20261028/build_topic_report.py` 可重新生成报告。这些步骤不编码文本、不拟合模型。

若要从原始文本重做外推，还需用户原附件 `aipaper.zip` 解压出的 `aipaper/papers.csv`、上一轮 `supplement/results/public_submissions.jsonl` 及单独的增量缓存包。编码器权重按固定 revision 和哈希下载，未重复打包。完整缓存复用可避免再次编码新增语料；部分断点重启的量化分批仍可能产生细微数值变化。

主要来源：Paper Copilot OpenReview archive 固定 revision `3bb756daff86e9b084ada9f1c9882da108a1be06`；qhjqhj00/iclr-openreview-reviews v1.0；各会议官方评分表和 ICLR 官方评审回顾。上一轮 227,128 条评分及来源证据单独提供。统计工作流参考 Kassis et al. (2026), *Scientific Agent Skills*, https://doi.org/10.48550/arXiv.2609.00065 。
'''
    entries=[]
    for p in sorted(RESULTS.glob('*')):
        if p.is_file() and not p.name.startswith('.') and p.name!='report_script.js' and not p.name.endswith(('.tmp','.writing')):
            entries.append((p,'projection_20261028/results/'+p.name))
            if p.name in ['iclr_topic_metrics_150.csv','iclr_topic_metrics_150.json','iclr_cohort_summary.csv','iclr_topic_year_changes.csv']:
                entries.append((p,'results/'+p.name))
    entries.append((RESULTS/'iclr_topic_rates_report.html','iclr_topic_rates_report.html'))
    for p in sorted(ROOT.glob('*.py')):entries.append((p,'projection_20261028/'+p.name))
    for p in sorted((WORK/'recovered_existing/models/onnx').glob('*')):
        if p.is_file() and not p.name.startswith('.'):entries.append((p,'recovered_existing/models/onnx/'+p.name))
    for path in ['source_existing/src','source_existing/configs']:
        for p in sorted((WORK/path).rglob('*')):
            if p.is_file() and p.suffix in ['.py','.json'] and '__pycache__' not in p.parts:
                entries.append((p,str(p.relative_to(WORK))))
    entries.append((WORK/'source_existing/LICENSE','source_existing/LICENSE'))
    entries.append((WORK/'upload/centroids.npy','upload/centroids.npy'))
    entries.append((WORK/'supplement/results/supplement_manifest.json','supplement/results/supplement_manifest.json'))
    for p in sorted((ROOT/'additional_discovery').glob('*')):
        if p.is_file() and not p.name.startswith('.'):entries.append((p,'projection_20261028/additional_discovery/'+p.name))
    requirement_text='numpy==2.3.5\nscipy==1.17.0\nscikit-learn==1.8.0\nonnxruntime==1.31.1\ntokenizers==0.23.3\n'
    artifacts=[]
    artifacts.append(zip_entries(DIST/'iclr_topic_rates_results.zip',entries,
        {'README.md':readme,'projection_20261028/requirements.txt':requirement_text},
        csv_counts={'projection_20261028/results/iclr_public_topic_assignments.csv':38890,'results/iclr_topic_metrics_150.csv':150},
        jsonl_counts={'projection_20261028/results/iclr_public_topic_assignments.jsonl':38890}))
    # Repackage the previous rating delivery into a more compact direct download.
    previous=WORK/'supplement/results'
    score_entries=[]
    for name in ['reviews.csv','topic_scores_50.csv','coverage_summary.csv','existing_paper_review_join.csv',
                 'source_inventory.csv','quarantine_title_mismatches.csv','supplement_manifest.json']:
        score_entries.append((previous/name,'previous_scores/'+name))
    score_entries.append((WORK/'supplement/release_evidence/source_provenance.json','evidence/source_provenance.json'))
    for p in sorted((WORK/'supplement/release_evidence').glob('copilot_*.jsonl')):score_entries.append((p,'evidence/'+p.name))
    for p in sorted((WORK/'supplement/release_evidence').glob('qh_*.jsonl')):score_entries.append((p,'evidence/'+p.name))
    for p in sorted((WORK/'supplement/raw/qh_selected').glob('*_notes.jsonl')):score_entries.append((p,'evidence/'+p.name))
    score_entries.append((previous/'prism_icml2025_score_evidence.jsonl','evidence/prism_icml2025_score_evidence.jsonl'))
    artifacts.append(zip_entries(DIST/'public_review_scores_and_evidence.zip',score_entries,
        {'README.md':'上一轮 227,128 条评分观测的紧凑交付：reviews.csv 为全量评分观测；163,737 条保留原始评审 ID，其余为公开规范化列表位置。七届原模型主题评分在 topic_scores_50.csv。evidence 为公开评分列表、原始 note 字段投影及源 URL／版本／哈希。不同年份和量表不合并；本次 ICLR 主题接收比例另见结果包。\n'},
        csv_counts={'previous_scores/reviews.csv':227128,'previous_scores/topic_scores_50.csv':450}))
    cache_path=pathlib.Path(projection['encoder']['cache_path'])
    assert cache_path.is_file()
    cache_entries=[(cache_path,str(cache_path.relative_to(WORK)))]
    cache_entries.append((RESULTS/'projection_plan.json','projection_20261028/results/projection_plan.json'))
    cache_entries.append((RESULTS/'projection_manifest.json','projection_20261028/results/projection_manifest.json'))
    for p in sorted((ROOT/'model_assets').rglob('*.json')):
        if p.name!='tokenizer.json':cache_entries.append((p,str(p.relative_to(WORK))))
    artifacts.append(zip_entries(DIST/'minilm_incremental_vector_cache.zip',cache_entries,
        {'README.md':'已完成的新增／修订文本向量缓存，绑定编码输入顺序和原 encoder 指纹。与结果包按路径一起解压即可复用；不含重新训练的模型或预训练权重。完整缓存可避免重算 31,559 条文本。原模型权重通过固定 revision 和 SHA256 获取。部分断点重启的分批量化敏感性仍需参照诊断记录。\n'}))
    for p in [DIST/'iclr_topic_rates_report.html',DIST/'iclr_topic_metrics_150.csv']:
        artifacts.append(dict(name=p.name,bytes=p.stat().st_size,sha256=sha(p)))
    manifest=dict(status='completed',artifacts=artifacts,scope='verified_public_ICLR_snapshot_cohort',
                  original_models_retrained=False,numerical_batch_sensitivity_preserved=True)
    (DIST/'topic_rates_delivery_manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2))
    print(json.dumps(manifest,ensure_ascii=False,indent=2),flush=True)


if __name__=='__main__':main()
