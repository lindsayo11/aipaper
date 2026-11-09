"""Offline Chinese report for topic rates, counts, scores, and diagnostics."""
import base64
import csv
import html
import json
import pathlib
import urllib.parse

ROOT=pathlib.Path(__file__).resolve().parent
WORK=ROOT.parent
RESULTS=ROOT/'results'


def e(v):return html.escape(str(v if v is not None else ''))


def pct(v):return '—' if v is None else f'{v*100:.2f}%'


def table(headers,rows):
    return '<div class="scroll"><table><thead><tr>'+''.join('<th>'+e(h)+'</th>' for h in headers)+'</tr></thead><tbody>'+''.join('<tr>'+''.join('<td>'+e(v)+'</td>' for v in row)+'</tr>' for row in rows)+'</tbody></table></div>'


def main():
    verification=json.loads((RESULTS/'cohort_verification.json').read_text())
    projection=json.loads((RESULTS/'projection_manifest.json').read_text())
    compatibility=json.loads((RESULTS/'model_compatibility_validation.json').read_text())
    metrics=json.loads((RESULTS/'iclr_topic_metrics_150.json').read_text())
    from analyze_topic_rates import load_projection_rows
    records,_=load_projection_rows(RESULTS)
    test_path=RESULTS/'test_results.json'
    tests=json.loads(test_path.read_text()) if test_path.exists() else {'tests_run':None}
    cohorts=verification['cohorts']
    annual=table(['届次','公开投稿','当前录用','当前拒稿','撤稿','直接拒稿','录用／录用及拒稿','录用／全部公开投稿','已发出决定记录口径'],[
        [c['year'],c['public_submissions'],c['accepted'],c['rejected'],c['withdrawn'],c['desk_rejected'],
         f'{pct(c["current_conditional_acceptance_rate"])} ({c["accepted"]}/{c["current_decided_denominator"]})',
         pct(c['accepted_over_all_public_submissions']),
         f'{pct(c["issued_decision_acceptance_rate"])} ({c["issued_accepted"]}/{c["issued_decision_denominator"]})'] for c in cohorts])
    heat='<div class="scroll"><table class="heat"><thead><tr><th>原主题编号与自动关键词</th><th>2024</th><th>2025</th><th>2026</th></tr></thead><tbody>'
    for topic in range(50):
        rows=sorted([r for r in metrics if r['topic_id']==topic],key=lambda r:r['year'])
        heat+='<tr><th>'+e('T'+str(topic)+' · '+rows[0]['topic_keywords'])+'</th>'
        for r in rows:
            value=r['current_public_conditional_acceptance_rate']
            alpha=.06+.83*(value or 0)
            color='#fff' if value is not None and value>.68 else '#15383c'
            tip=f"{r['year']}, accepted={r['current_accepted']}, rejected={r['current_rejected']}, denominator={r['current_decided_denominator']}"
            heat+='<td style="background:rgba(0,105,95,'+str(round(alpha,3))+');color:'+color+'" title="'+e(tip)+'"><strong>'+e(pct(value))+'</strong><small>'+e(str(r['current_accepted'])+'/'+str(r['current_decided_denominator']))+'</small></td>'
        heat+='</tr>'
    heat+='</tbody></table></div>'
    current=[r for r in metrics if r['year']==2026]
    baseline={r['topic_id']:r for r in metrics if r['year']==2024}
    hot=table(['2026 公开投稿规模前五主题','公开投稿数','投稿份额','相较 2024 份额变化','公开决定队列比例'],[
        ['T'+str(r['topic_id'])+' · '+r['topic_keywords'],r['public_topic_submissions'],pct(r['topic_submission_share']),
         f"{100*(r['topic_submission_share']-baseline[r['topic_id']]['topic_submission_share']):+.2f} 个百分点",pct(r['current_public_conditional_acceptance_rate'])]
        for r in sorted(current,key=lambda r:(-r['public_topic_submissions'],r['topic_id']))[:5]])
    samples=[]
    for r in metrics:
        group=[p for p in records if p['year']==r['year'] and p['topic_id']==r['topic_id']]
        for status in ['accepted','rejected']:
            candidates=sorted([p for p in group if p['current_status']==status],key=lambda p:(-p['similarity'],p['openreview_id']))[:2]
            for p in candidates:
                samples.append({k:p[k] for k in ['year','topic_id','title','current_status','mean_rating','similarity','openreview_id']})
    downloads=''
    for name,label in [('iclr_topic_metrics_150.csv','150 行主题统计'),('iclr_cohort_summary.csv','三届分母汇总'),('iclr_topic_year_changes.csv','主题年度变化')]:
        b=(RESULTS/name).read_bytes()
        downloads+='<a class="download" download="'+e(name)+'" href="data:text/csv;base64,'+base64.b64encode(b).decode()+'">'+e(label)+' CSV ↓</a>'
    checks=table(['核对项','结果'],[
        ['公开投稿 ID 集合', '38,890 个 ID，两个独立发布的存档集合一致'],
        ['当前录用／拒稿状态', '28,043 篇均有同结果的正式 Decision note'],
        ['主题归属与分母', '38,890 条均有主题；150 行按届次完整对账'],
        ['原模型结果', '原 37,662 篇归属表未改写；未执行拟合或聚类训练'],
        ['中心文件', projection['centers_sha256']],
        ['原上下文核验', '89/89 复现；平均相似度绝对误差 '+f"{compatibility['original_context_replay']['mean_similarity_error']:.2e}"],
        ['重新分批核验', '严格标准未通过，原始失败结果完整保留；1000 篇分层样本一致率 96.4%'],
        ['统计与产物测试',str(tests['tests_run'])+' 项通过' if tests.get('tests_run') is not None else '见数据包测试记录']])
    payload=json.dumps({'metrics':metrics,'samples':samples},ensure_ascii=False).replace('<','\\u003c').replace('\u2028','\\u2028').replace('\u2029','\\u2029')
    page='''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>ICLR 公开投稿：50 个原主题的评分与条件接收比例</title><style>
    :root{--ink:#15383c;--muted:#5a7475;--line:#d5e2dc;--green:#086d62}*{box-sizing:border-box}body{font-family:system-ui,-apple-system,"Microsoft YaHei",sans-serif;color:var(--ink);background:#f5f8f5;line-height:1.8;margin:0}main{max-width:1260px;margin:auto;padding:42px 24px}h1{font-size:34px;line-height:1.35;max-width:1000px;margin:12px 0 18px}h2{font-size:24px;margin:42px 0 18px}h3{font-size:18px;margin:15px 0 8px}.kicker{font-size:12px;letter-spacing:.16em;color:var(--green)}.lead{font-size:18px;max-width:1050px}.muted,small{color:var(--muted)}.grid{display:grid;grid-template-columns:repeat(4,1fr);gap:15px;margin:26px 0}.card{background:#fff;border:1px solid var(--line);padding:20px;border-radius:10px}.card strong{font-size:30px;display:block}.notice{background:#e7f1e9;border-left:4px solid var(--green);padding:17px 22px;margin:20px 0}.warning{background:#fff4de;border-left-color:#b77b20}.scroll{overflow:auto;background:white;border:1px solid var(--line);border-radius:8px;max-height:680px}table{border-collapse:collapse;width:100%;font-size:13px}td,th{text-align:left;padding:11px 13px;border-bottom:1px solid var(--line);vertical-align:top}th{background:#e8efea;position:sticky;top:0;white-space:nowrap;z-index:1}td{overflow-wrap:anywhere}td:first-child{min-width:80px}.heat th:first-child{white-space:normal;min-width:380px;max-width:510px}.heat td{text-align:center;min-width:130px}.heat strong{display:block;font-size:15px}.heat small{display:block;color:inherit;font-size:11px}.toolbar{display:flex;gap:12px;align-items:center;flex-wrap:wrap;margin:18px 0}.toolbar input,.toolbar select{border:1px solid #b8cebd;border-radius:5px;padding:9px 12px;background:white;color:var(--ink);font:inherit}.toolbar input[type=search]{min-width:240px}.download{display:inline-block;border:1px solid #a5c8b2;border-radius:5px;padding:9px 15px;background:white;color:var(--green);margin:0 12px 12px 0;text-decoration:none}a{color:var(--green)}.sample-grid{display:grid;grid-template-columns:1fr 1fr;gap:12px}.paper{padding:17px;background:white;border:1px solid var(--line);border-radius:7px}.paper h3{font-size:15px;margin:5px 0}.paper small{display:block}.cols{display:grid;grid-template-columns:1fr 1fr;gap:25px}code{background:#e7eee8;padding:2px 5px;border-radius:4px;font-size:12px}li{margin:7px 0}footer{border-top:1px solid var(--line);padding-top:20px;margin-top:35px;font-size:12px;color:var(--muted)}@media(max-width:800px){main{padding:25px 15px}.grid{grid-template-columns:1fr 1fr}.cols,.sample-grid{grid-template-columns:1fr}h1{font-size:27px}}
    </style></head><body><main><div class="kicker">课程大作业 · 原语义主题空间的增量分析 · ICLR 2024—2026</div><h1>50 个原主题的评分与公开队列条件接收比例已算出</h1>
    <p class="lead">使用你提供的原聚类中心，为 ICLR 三届全部公开投稿补齐主题归属。结果覆盖 38,890 条记录、150 个“主题 × 届次”单元。原 LSA／MiniLM 聚类没有重训，原 37,662 篇论文的归属表保持不变。</p>
    <div class="grid"><div class="card"><strong>38,890</strong>公开投稿均已归主题</div><div class="card"><strong>28,043</strong>当前录用／拒稿有正式决定证据</div><div class="card"><strong>150</strong>主题与届次统计单元</div><div class="card"><strong>0 次</strong>模型拟合或聚类重训</div></div>
    <div class="notice"><strong>主口径：</strong>某主题的当前公开录用数 ÷（该主题当前公开录用数＋公开拒稿数）。撤稿、直接拒稿不进入这个分母。该结果是<strong>已核验公开存档队列的条件比例</strong>；不是会议官方全体有效投稿的主题接收率，也不是未来论文的录用概率。</div>
    <div class="notice warning"><strong>数值敏感性仍须保留：</strong>原量化编码器对分批方式敏感。重新分批的 1000 篇分层样本归属一致率为 96.4%，严格复现标准未通过；复原原批次后，39 个不一致案例及 50 个对照均精确复现，确认中心匹配。下列统计是在固定输入顺序和原主题中心下的<strong>探索性外推结果</strong>，不能把类别视为人工确认的真值。所有诊断原文随数据包交付。</div>
    <h2>1. 三届队列与三种分母</h2>@@ANNUAL@@
    <p class="muted">“已发出决定”口径包含后来撤稿但仍保留决定 note 的记录，因此与当前 venue 状态可能不同。两者分别计算，没有把缺失决定当作拒稿。官方 Fact Sheet 的有效投稿口径另有定义，本表不替代官方统计。</p>
    <h2>2. 逐主题统计：分母、平均分与敏感性一起看</h2>
    <div class="toolbar"><select id="year"><option>2026</option><option>2025</option><option>2024</option></select><select id="denominator"><option value="current">当前录用／录用及拒稿</option><option value="issued">已发出决定记录</option><option value="all">录用／全部公开投稿</option></select><input type="search" id="query" placeholder="主题关键词或编号"><label><input type="checkbox" id="enough">仅显示当前决定分母 ≥ 50</label><span id="row-count" class="muted"></span></div>
    <p id="scope" class="muted"></p><div class="scroll"><table><thead><tr><th>主题</th><th>自动关键词</th><th>公开投稿</th><th>当前录用</th><th>当前拒稿</th><th>所选分母</th><th>所选比例</th><th>录用均分／n</th><th>拒稿均分／n</th><th>排除离群后比例</th></tr></thead><tbody id="topic-body"></tbody></table></div>
    <p class="muted">评分先在每篇内部求均值，再在同届同主题按论文等权汇总；2024／2025 原量表为 1,3,5,6,8,10，2026 为 0,2,4,6,8,10。评分为公开存档的最近版本，年份与量表不混合。离群按原模型阈值标记，主统计保留它们；排除离群是额外敏感性分析，不能代替主分母。原始主题名称仍需人工命名复核。</p>
    <h2>3. 当前公开决定队列比例：50 主题 × 3 年</h2>@@HEAT@@
    <p class="muted">单元格同时列出录用数／决定分母。色深只编码上述比例，不编码置信度或未来成功概率；小分母行应结合计数阅读。</p>
    <h2>4. 公开投稿中的热点分布</h2>@@HOT@@
    <p class="muted">按 2026 年公开投稿规模列出前五个主题。份额变化描述已观察投稿兴趣，不能证明技术新颖性、因果关系或更高投稿胜算。原模型从已录用语料学习主题空间，对拒稿及较新方向的表达可能较弱。</p>
    <h2>5. 录用与拒稿代表论文</h2><p>选择同一届次、同一主题，查看各两篇距主题中心较近的公开论文。这些例子用于理解主题，不代表评审质量排名。</p>
    <div class="toolbar"><select id="sample-year"><option>2026</option><option>2025</option><option>2024</option></select><select id="sample-topic"></select></div><div id="samples" class="sample-grid"></div>
    <h2>6. 核验与可下载统计</h2>@@CHECKS@@<p>@@DOWNLOADS@@</p>
    <div class="cols"><div><h3>复用与补算</h3><ul><li>7,331 条公开文本与原输入完全相同，复用原归属。</li><li>新增 27,572 条投稿文本；另有 3,987 条已存在文本在公开存档中修订，仅补算这些文本的向量。</li><li>使用原 50×384 个未归一化拟合中心做欧氏最近中心预测；余弦相似度仅用于解释和原离群阈值。</li><li>标题、摘要之外的年份、评分、决定和作者关键词均未进入文本向量。</li><li>原数据、原归属表及原源码保留，文本修订导致的新归属只记录在本次公开队列表。</li></ul></div>
    <div><h3>仍未取得的范围</h3><ul><li>ICML 2024 与 NeurIPS 2026 可靠评分仍未取得。</li><li>ICML／NeurIPS 的未公开拒稿不能由公开样本补齐，其全体投稿主题接收率仍未计算。</li><li>本次没有重跑 LSA，也没有把原 50 主题说成最优主题数或人类审核结果。</li><li>量化分批敏感性属于明确的技术限制，原始严格核验失败记录保留；原上下文核验用于确认文件匹配，不作为新的独立准确率估计。</li></ul></div></div>
    <h2>7. 来源与方法</h2><ul><li><a href="https://github.com/papercopilot/openreview/tree/3bb756daff86e9b084ada9f1c9882da108a1be06">Paper Copilot 公开 OpenReview 存档，固定版本</a></li><li><a href="https://github.com/qhjqhj00/iclr-openreview-reviews/releases/tag/v1.0">ICLR 原始公开评审与决定 note 转存</a></li><li><a href="https://blog.iclr.cc/2026/03/31/a-retrospective-on-the-iclr-2026-review-process/">ICLR 2026 官方评审回顾：官方口径参照</a></li><li>Kassis, T., Agarwal, V., He, Y., Patel, D., &amp; Brueckner, A. M. (2026). <em>Scientific Agent Skills: A Library of Procedural Knowledge for Research Agents</em>. <a href="https://doi.org/10.48550/arXiv.2609.00065">arXiv:2609.00065</a>（统计工作流参考）。</li></ul>
    <footer>本报告无外部脚本、字体或图表依赖，可离线筛选和下载内嵌 CSV。全部投稿与逐篇归属、评分证据、模型中心哈希、运行代码、数值敏感性诊断及编码缓存随数据包交付。统计生成时间（UTC）：@@TIME@@。</footer>
    <script id="data" type="application/json">@@DATA@@</script><script>
    'use strict';const DATA=JSON.parse(document.getElementById('data').textContent);const byId=id=>document.getElementById(id);const fmt=v=>v===null?'—':(100*v).toFixed(2)+'%';const cell=(tag,text)=>{const el=document.createElement(tag);el.textContent=text;return el;};
    function render(){const year=Number(byId('year').value),q=byId('query').value.trim().toLowerCase(),mode=byId('denominator').value,enough=byId('enough').checked;const rows=DATA.metrics.filter(r=>r.year===year&&(!q||('t'+r.topic_id+' '+r.topic_keywords).toLowerCase().includes(q))&&(!enough||r.current_decided_denominator>=50));const body=byId('topic-body');body.replaceChildren();for(const r of rows){let denominator=r.current_decided_denominator,value=r.current_public_conditional_acceptance_rate;if(mode==='issued'){denominator=r.issued_decision_denominator;value=r.issued_decision_acceptance_rate;}if(mode==='all'){denominator=r.public_topic_submissions;value=r.all_public_submission_acceptance_rate;}const mean=(v,n)=>v===null?'—':v.toFixed(3)+' / '+n;const tr=document.createElement('tr');for(const v of ['T'+r.topic_id,r.topic_keywords,r.public_topic_submissions,r.current_accepted,r.current_rejected,denominator,fmt(value),mean(r.mean_accepted_paper_rating,r.accepted_scored_papers),mean(r.mean_rejected_paper_rating,r.rejected_scored_papers),fmt(r.nonoutlier_conditional_acceptance_rate)])tr.append(cell('td',v));body.append(tr);}byId('row-count').textContent=rows.length+' 个主题';byId('scope').textContent=mode==='current'?'主口径：当前公开录用／（当前公开录用＋拒稿）；撤稿与直接拒稿不进入分母。':mode==='issued'?'敏感性口径：按已发出的正式 Decision note 统计，包括决定后撤稿记录。':'描述性口径：当前公开录用／全部可见投稿。不是官方全部有效投稿口径。';}
    function renderSamples(){const year=Number(byId('sample-year').value),topic=Number(byId('sample-topic').value),out=byId('samples');out.replaceChildren();const rows=DATA.samples.filter(r=>r.year===year&&r.topic_id===topic);for(const r of rows){const card=document.createElement('article');card.className='paper';card.append(cell('small',(r.current_status==='accepted'?'当前录用':'当前拒稿')+' · '+year+' · T'+topic));const h=document.createElement('h3'),a=document.createElement('a');a.textContent=r.title;a.href='https://openreview.net/forum?id='+encodeURIComponent(r.openreview_id);a.target='_blank';a.rel='noopener noreferrer';h.append(a);card.append(h);card.append(cell('small','公开评审均分：'+(r.mean_rating===null?'缺失':r.mean_rating.toFixed(3))+'；主题余弦相似度：'+r.similarity.toFixed(3)));out.append(card);}if(!rows.length)out.append(cell('p','本单元没有可展示的录用／拒稿例子。'));}
    for(const r of DATA.metrics.filter(r=>r.year===2026)){const opt=document.createElement('option');opt.value=r.topic_id;opt.textContent='T'+r.topic_id+' · '+r.topic_keywords;byId('sample-topic').append(opt);}for(const id of ['year','denominator','query','enough'])byId(id).addEventListener('input',render);for(const id of ['sample-year','sample-topic'])byId(id).addEventListener('change',renderSamples);render();renderSamples();
    </script></main></body></html>'''
    mapping={'@@ANNUAL@@':annual,'@@HEAT@@':heat,'@@HOT@@':hot,'@@CHECKS@@':checks,
             '@@DOWNLOADS@@':downloads,'@@TIME@@':e(verification['created_at']),'@@DATA@@':payload}
    for key,value in mapping.items():page=page.replace(key,value)
    assert '@@' not in page and '<script src=' not in page
    from ai_trends.common import atomic_write
    atomic_write(RESULTS/'iclr_topic_rates_report.html',page)
    atomic_write(RESULTS/'report_script.js',page.split('</script><script>')[1].split('</script>')[0])
    print('Offline report',len(page.encode()),'bytes',flush=True)


if __name__=='__main__':
    import sys
    sys.path.insert(0,str(WORK/'source_existing/src'))
    main()
