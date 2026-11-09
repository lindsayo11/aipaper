"""Self-contained Chinese evidence report; untrusted metadata never becomes HTML/JS."""
from __future__ import annotations

import base64
from collections import Counter, defaultdict, deque
import csv
import gzip
import hashlib
import html
import io
import json
from pathlib import Path

from .common import atomic_write, read_json, read_jsonl, safe_url, utcnow


def escape(value):
    return html.escape(str(value if value is not None else ''), quote=True)


def script_json(value):
    """JSON data in an inert script element, safe even against closing tags."""
    return (json.dumps(value, ensure_ascii=False, allow_nan=False)
            .replace('&', '\\u0026').replace('<', '\\u003c').replace('>', '\\u003e')
            .replace('\u2028', '\\u2028').replace('\u2029', '\\u2029'))


def link(label, url):
    url = safe_url(url)
    return ('<a href="' + escape(url) + '" target="_blank" rel="noopener noreferrer">'
            + escape(label) + '</a>') if url else escape(label)


def load_table(directory, name):
    path = Path(directory) / (name + '.json')
    if path.exists():
        value = read_json(path, [])
        return value if isinstance(value, list) else value.get('rows', [])
    path = Path(directory) / (name + '.csv')
    if path.exists():
        with path.open(encoding='utf-8-sig', newline='') as f:
            return list(csv.DictReader(f))
    return []


def numeric(value, default=None):
    try:
        return float(value) if value not in (None, '', 'null', 'None') else default
    except (TypeError, ValueError):
        return default


def number(value):
    value = numeric(value)
    return '—' if value is None else (f'{int(value):,}' if value.is_integer() else f'{value:,.2f}')


def percent(value, unit='fraction'):
    value = numeric(value)
    if value is None:
        return '—'
    return f'{value * (100 if unit == "fraction" else 1):.2f}%'


def official_percent(row):
    value=numeric(row.get('official_rate'))
    if value is None:return '—'
    digits=max(0,min(6,int(numeric(row.get('official_rate_precision_digits'),2))))
    return f'{value:.{digits}f}%'


def stratified_sample(papers, maximum=5000):
    """Round robin across venue/year/track strata, independent of input order."""
    maximum = max(0, min(5000, int(maximum)))
    groups = defaultdict(list)
    for paper in papers:
        groups[(str(paper.get('venue', '')), str(paper.get('year', '')), str(paper.get('track', 'unknown')))].append(paper)
    queues = [deque(sorted(group, key=lambda p: str(p.get('paper_id', ''))))
              for _, group in sorted(groups.items())]
    result = []
    while queues and len(result) < maximum:
        pending = []
        for queue in queues:
            if len(result) >= maximum:
                break
            result.append(queue.popleft())
            if queue:
                pending.append(queue)
        queues = pending
    return result


def embedded_file(path, root):
    """Gzip keeps the complete dual-format corpus portable in a single HTML."""
    path = Path(path)
    body = path.read_bytes()
    return {'name': str(path.relative_to(root)), 'size_bytes': len(body),
            'sha256': hashlib.sha256(body).hexdigest(), 'encoding': 'gzip+base64',
            'data': base64.b64encode(gzip.compress(body, mtime=0)).decode('ascii')}


def table(headers, rows, class_name=''):
    if not rows:
        return '<p class="empty">当前没有可展示记录；缺失值未填成零。</p>'
    return ('<div class="table-wrap"><table class="' + class_name + '"><thead><tr>'
            + ''.join('<th>' + escape(h) + '</th>' for h in headers) + '</tr></thead><tbody>'
            + ''.join('<tr>' + ''.join('<td>' + cell + '</td>' for cell in row) + '</tr>' for row in rows)
            + '</tbody></table></div>')


def normalize_topics(value):
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        return value.get('topics', [])
    return []


def build_report(config, output, backend='onnx'):
    output = Path(output)
    processed = output / 'processed'
    model_dir = output / 'models' / backend
    analysis_dir = output / 'analysis' / backend
    papers = read_jsonl(processed / 'papers.jsonl')
    reviews = read_jsonl(processed / 'reviews.jsonl')
    quality = read_json(processed / 'quality.json', {})
    coverage = read_json(output / 'source_coverage.json', [])
    if isinstance(coverage, dict):
        coverage = coverage.get('rows', coverage.get('coverage', []))
    assignments = read_jsonl(model_dir / 'assignments.jsonl')
    assigned = {str(a['paper_id']): a for a in assignments}
    topics = normalize_topics(read_json(model_dir / 'topics.json', []))
    model_manifest = read_json(model_dir / 'manifest.json', {})
    analysis_manifest = read_json(analysis_dir / 'analysis_manifest.json', {})
    official = load_table(analysis_dir, 'official_statistics')
    reconciliation = load_table(analysis_dir, 'reconciliation')
    trends = load_table(analysis_dir, 'topic_trends')
    changes = load_table(analysis_dir, 'topic_changes')
    heatmap = load_table(analysis_dir, 'heatmap')
    scores = load_table(analysis_dir, 'scores')
    decisions = load_table(analysis_dir, 'decision_samples')
    detail_summary = read_json(output / 'details/summary.json', {})
    directory_reconciliation = load_table(output / 'details', 'reconciliation')
    validation = read_json(output / 'validation.json', read_json(output / 'validation_results.json', {}))
    comparison = {}
    for path in [output / 'model_comparison/comparison.json', output / 'models/model_comparison.json', output / 'models/comparison.json',
                 output / 'model_comparison.json', output / 'comparison.json']:
        if path.exists():
            comparison = read_json(path, {})
            break
    by_group = defaultdict(list)
    for paper in papers:
        by_group[(paper.get('venue'), int(paper.get('year', 0)))].append(paper)
    coverage_lookup = {(c.get('venue'), int(c.get('year', 0))): c for c in coverage}
    main = [p for p in papers if p.get('track') == 'main' and p.get('decision') == 'accepted']
    eligible = [p for p in main if p.get('title') and p.get('abstract')]
    missing = len(main) - len(eligible)
    sample = stratified_sample(papers, config.get('report', {}).get('max_rows', 5000))
    topic_map = {str(t.get('topic_id')): t for t in topics}
    for t in topics:
        if 'size' not in t:
            t['size'] = sum(str(a.get('topic_id')) == str(t.get('topic_id')) for a in assignments)
    topics = sorted(topics, key=lambda t: (-int(t.get('size', 0)), str(t.get('topic_id'))))
    sample_rows = []
    for paper in sample:
        a = assigned.get(str(paper.get('paper_id')), {})
        authors = paper.get('authors', [])
        sample_rows.append({k: paper.get(k, '') for k in ['paper_id', 'venue', 'year', 'track', 'title', 'abstract', 'decision']}
                           | {'authors': authors if isinstance(authors, list) else [str(authors)],
                              'source_url': safe_url(paper.get('source_url', '')),
                              'topic_id': a.get('topic_id'), 'similarity': a.get('similarity')})
    export_paths = [processed / 'papers.csv', processed / 'papers.jsonl', processed / 'reviews.jsonl',
                    processed / 'coverage.csv', processed / 'quality.json',
                    output / 'source_coverage.csv', model_dir / 'assignments.csv',
                    model_dir / 'topics.json', model_dir / 'topic_review.csv', model_dir / 'manifest.json']
    export_paths += [output / 'details/summary.json', output / 'details/reconciliation.csv']
    export_paths += sorted(analysis_dir.glob('*.csv'))
    export_paths += sorted(analysis_dir.glob('*manifest.json'))
    export_paths += [p for p in [output / 'model_comparison/comparison.json', output / 'model_comparison/comparison.csv',
                               output / 'models/model_comparison.json', output / 'models/comparison.json',
                               output / 'model_comparison.json', output / 'comparison.json'] if p.exists()]
    exports = [embedded_file(p, output) for p in dict.fromkeys(export_paths) if p.is_file()]

    coverage_rows = []
    for venue in config.get('venues', ['ICLR', 'ICML', 'NeurIPS']):
        for year in config.get('years', [2024, 2025, 2026]):
            group = by_group.get((venue, year), [])
            observed = [p for p in group if p.get('track') == 'main' and p.get('decision') == 'accepted']
            abstracts = sum(bool(p.get('abstract')) for p in observed)
            c = coverage_lookup.get((venue, year), {})
            refs = [r for r in official if r.get('venue') == venue and int(numeric(r.get('year'), 0)) == year]
            preferred = next((r for r in refs if str(r.get('preferred')).lower() in ('true', '1')), refs[0] if refs else {})
            official_n = preferred.get('accepted')
            n_value = numeric(official_n)
            ratio = len(observed) / n_value if n_value else None
            review_status = c.get('openreview_status', c.get('openreview', {}))
            if isinstance(review_status, dict):
                review_status = review_status.get('status', '未记录')
            status = c.get('status', '未采集')
            coverage_rows.append([
                escape(f'{venue} {year}'), '<span class="badge">' + escape(status) + '</span>',
                number(len(group)), number(len(observed)), number(abstracts),
                percent(abstracts / len(observed) if observed else None),
                number(official_n) if official_n is not None else escape(preferred.get('accepted_display', '—')), percent(ratio),
                escape(review_status or '未记录'), link('来源', c.get('source_url', ''))])
    coverage_table = table(['届次', '官网状态', '实采去重', '明确主会录用', '主会有摘要', '摘要覆盖率', '登记主会录用¹', '实采/登记¹', '公开评审状态', '官网'], coverage_rows)
    directory_rows = []
    for row in directory_reconciliation:
        pages = row.get('pages', [])
        if isinstance(pages, str):
            try:
                pages = json.loads(pages)
            except (ValueError, TypeError):
                pages = [pages]
        urls = ' · '.join(link('目录 ' + str(i + 1), url) for i, url in enumerate(pages)) if isinstance(pages, list) else ''
        directory_rows.append([escape(f"{row.get('venue', '')} {row.get('year', '')}"),
                               number(row.get('directory_events')), number(row.get('bulk_events')),
                               number(row.get('directory_absent_from_bulk_events')),
                               number(row.get('bulk_title_not_in_directory')), number(row.get('new_titles_vs_bulk')),
                               escape(row.get('status', '')), urls])
    directory_table = table(['届次', '实时目录事件', '批量事件', '目录有/批量无事件', '批量标题未见于目录', '新增标题', '状态', '实时目录'], directory_rows)
    if detail_summary:
        remaining = numeric(detail_summary.get('remaining'))
        failed = numeric(detail_summary.get('failed'), 0)
        status = detail_summary.get('status', '未记录')
        if status == 'running' or (remaining is not None and remaining > 0):
            detail_notice = '详情补采仍在执行；此处为阶段性检查点，未完成部分不能视为已覆盖。'
        elif failed > 0:
            detail_notice = '详情补采本轮尝试已结束，仍有失败 URL；失败记录不构成成功覆盖。'
        else:
            detail_notice = '详情补采按当前计划结束；页面成功响应与目录对账仍需结合逐条证据复核。'
        detail_metrics = [
            ('补采计划', detail_summary.get('planned')), ('已尝试', detail_summary.get('attempted')),
            ('成功', detail_summary.get('successful')), ('失败', detail_summary.get('failed')),
            ('剩余', detail_summary.get('remaining')), ('目录新增条目', detail_summary.get('directory_new_papers'))]
        metric_html = ''.join('<div><strong>' + number(value) + '</strong><span>' + escape(label)
                              + '</span></div>' for label, value in detail_metrics)
        detail_html = ('<div class="panel detail-panel"><div class="detail-title"><h3>详情补采与目录对账</h3>'
                       + '<span class="badge">' + escape(status) + '</span></div><p class="notice">'
                       + escape(detail_notice) + '</p><div class="detail-metrics">' + metric_html + '</div>'
                       + '<p>原计划缺摘要主会：<strong>' + number(detail_summary.get('main_missing_planned'))
                       + '</strong> 篇；已修复 <strong>' + number(detail_summary.get('main_repaired'))
                       + '</strong> 篇；摘要修复率 <strong>' + percent(detail_summary.get('main_abstract_repair_rate'))
                       + '</strong>。</p><p class="caption">检查点时间（UTC）：' + escape(detail_summary.get('updated_at', '未记录'))
                       + '。目录新增条目在缺少逐篇赛道和决定证据时保持 unknown，不纳入主会主题模型；导航栏的 Main Track 字样不是单篇赛道证据。</p>'
                       + '<details><summary>逐届实时目录与批量名单对账</summary>' + directory_table + '</details></div>')
    else:
        detail_html = ('<div class="panel detail-panel"><h3>详情补采与目录对账</h3>'
                       + '<p class="empty">尚未记录详情补采状态，不能宣称补采完成。</p>'
                       + '<details><summary>逐届实时目录与批量名单对账</summary>' + directory_table + '</details></div>')
    official_rows = []
    for row in official:
        official_rows.append([escape(f"{row.get('venue', '')} {row.get('year', '')}"),
                              number(row.get('raw_submissions')), number(row.get('valid_submissions')),
                              number(row.get('reported_submissions')),
                              number(row.get('reviewed')), number(row.get('accepted')) if row.get('accepted') is not None else escape(row.get('accepted_display', '—')),
                              official_percent(row),
                              escape(row.get('denominator_definition', '未公开')),
                              escape(row.get('source_level', '')), escape(row.get('source_date', '')),
                              link('来源', row.get('source_url', '')), escape(row.get('notes', ''))])
    official_table = table(['届次', '原始投稿', '有效投稿', '未细分口径的投稿', '进入评审', '录用', '官方接收率', '分母定义', '证据等级', '来源日期', '来源', '备注'], official_rows)
    recon_rows = [[escape(f"{r.get('venue')} {r.get('year')}"), escape(r.get('source_id', '')),
                   number(r.get('official_accepted')), number(r.get('observed_main_accepted')),
                   number(r.get('difference_observed_minus_official')), percent(r.get('coverage_ratio')),
                   escape(r.get('status', '')), link('证据', r.get('source_url', ''))] for r in reconciliation]
    recon_table = table(['届次', '来源版本', '登记录用', '实采明确主会', '实采−登记', '实采/登记', '对账状态', '证据'], recon_rows)
    score_rows = [[escape(r.get('venue', '')), number(r.get('year')), escape(r.get('topic_id', '')),
                   escape(f"{r.get('scale_min')}—{r.get('scale_max')}"), escape(r.get('score_stage', '')),
                   number(r.get('papers_with_reviews')), number(r.get('mean_paper_rating'))] for r in scores]
    score_table = table(['会议', '年份', '主题', '量表', '评分阶段', '有评分论文', '论文等权平均分'], score_rows)
    decision_rows = [[escape(f"{r.get('venue')} {r.get('year')}"), number(r.get('total_public_papers')),
                      number(r.get('accepted')), number(r.get('rejected')), number(r.get('withdrawn')),
                      number(r.get('desk_rejected')), number(r.get('under_review')), number(r.get('unknown')),
                      escape(r.get('reason', '无独立完整决定队列证明'))] for r in decisions]
    decision_table = table(['届次', '公开论文样本', '已录用', '拒稿', '撤稿', '直接拒稿', '审稿中', '未知', '队列限制'], decision_rows)

    topic_cards = []
    for t in topics:
        tid = str(t.get('topic_id'))
        keys = t.get('keywords', [])
        if isinstance(keys, str):
            keys = [keys]
        keywords = ' · '.join(str(x) for x in keys[:10])
        label = t.get('label_zh') or t.get('name') or ' / '.join(str(x) for x in keys[:3]) or f'主题 {tid}'
        reps = t.get('representatives', t.get('representative_papers', []))
        rep_html = ''.join('<li>' + link(r.get('title', r.get('paper_id', '')), r.get('source_url', r.get('url', '')))
                           + '<small>' + escape(r.get('paper_id', '')) + '</small></li>'
                           for r in reps if isinstance(r, dict))
        topic_cards.append('<details class="topic-card"><summary><span class="topic-no">T' + escape(tid)
                           + '</span><strong>' + escape(label) + '</strong><b>' + number(t.get('size'))
                           + ' 篇</b></summary><p class="keywords">' + escape(keywords) + '</p><ol>'
                           + rep_html + '</ol><p class="caption">标签由模型关键词生成，尚待人工命名与语义复核。</p></details>')
    topic_html = ''.join(topic_cards) or '<p class="empty">模型主题尚未生成。</p>'
    latest_changes = sorted(changes, key=lambda r: (-int(numeric(r.get('to_year'), 0)), -float(numeric(r.get('delta_pp'), 0))))
    displayed_changes = latest_changes[:24]
    change_rows = []
    for row in displayed_changes:
        t = topic_map.get(str(row.get('topic_id')), {})
        keys = t.get('keywords', [])
        label = ' / '.join(map(str, keys[:3])) if isinstance(keys, list) else str(keys)
        delta = numeric(row.get('delta_pp'))
        change_rows.append([escape(row.get('venue', '')), escape(f"{row.get('from_year')} → {row.get('to_year')}"),
                            escape('T' + str(row.get('topic_id')) + ' ' + label),
                            number(row.get('from_count')) + ' / ' + number(row.get('from_denominator')),
                            number(row.get('to_count')) + ' / ' + number(row.get('to_denominator')),
                            percent(row.get('from_share_percent'), 'percent'), percent(row.get('to_share_percent'), 'percent'),
                            '<span class="' + ('positive' if delta is not None and delta > 0 else 'negative') + '">'
                            + (f'{delta:+.2f} pp' if delta is not None else '—') + '</span>'])
    changes_table = table(['会议', '年份', '主题（自动标签）', '前期主题/全部主会', '后期主题/全部主会', '前期占比', '后期占比', '百分点变化'], change_rows)
    exclusions = analysis_manifest.get('heatmap_exclusions', [])
    exclusions_html = ''.join('<li>' + escape(f"{r.get('year', '')}：{r.get('reason', r)}") + '</li>' if isinstance(r, dict)
                              else '<li>' + escape(r) + '</li>' for r in exclusions)
    if not exclusions_html:
        exclusions_html = '<li>以完整分析清单中的共同年份筛选状态为准；门槛通过也不构成完整性证明。</li>'
    review_reason = analysis_manifest.get('score_unavailable_reason') or analysis_manifest.get('scores_reason')
    if not review_reason:
        review_reason = '未取得可核验的合法正式评审与量表；保持空表，零条评审不代表零分。' if not scores else '仅在同会议、年份、量表和评分阶段内汇总。'
    acceptance_reason = analysis_manifest.get('conditional_acceptance_reason') or '缺少事先独立证明完整的决定队列，以及对每篇被决定论文的完整主题归属；不计算主题条件接收率。'

    ideas = []
    seen = set()
    for row in latest_changes:
        tid = str(row.get('topic_id'))
        if tid in seen or numeric(row.get('delta_pp'), 0) <= 0 or tid not in topic_map:
            continue
        seen.add(tid)
        t = topic_map[tid]
        keys = t.get('keywords', [])
        label = ' / '.join(map(str, keys[:3])) if isinstance(keys, list) else str(keys)
        reps = t.get('representatives', t.get('representative_papers', []))
        evidence_links = '; '.join(link(r.get('title', ''), r.get('source_url', '')) for r in reps[:2] if isinstance(r, dict))
        ideas.append('<article class="idea"><span class="eyebrow">待验证假设 · T' + escape(tid) + '</span><h3>'
                     + escape(label) + '</h3><p>在 ' + escape(f"{row.get('venue')} {row.get('from_year')}→{row.get('to_year')}")
                     + ' 的已观察主会成果中，占比变化为 ' + escape(f"{numeric(row.get('delta_pp'), 0):+.2f}")
                     + ' 个百分点。可复核的起点是：这些代表论文是否共享尚未解决的任务、数据或评测限制？</p><p class="caption">证据：'
                     + evidence_links + '</p><p class="caption">验证动作：阅读原文；区分任务、方法、模态与瓶颈；检索当前相关工作及征稿范围；再由研究者判断新颖性与可行性。</p></article>')
        if len(ideas) == 3:
            break
    ideas_html = ''.join(ideas) or '<p class="empty">缺少可比较的增长记录；暂不生成选题假设。</p>'
    model_info = []
    for name in ['lsa', 'onnx']:
        m = read_json(output / 'models' / name / 'manifest.json', {})
        model_info.append({'backend': name, 'manifest': m, 'present': bool(m)})
    model_json_html = ''.join('<details><summary>' + escape(m['backend']) + ' 运行参数与指纹</summary><pre>'
                              + escape(json.dumps(m['manifest'], ensure_ascii=False, indent=2)) + '</pre></details>' for m in model_info)
    comparison_html = '<pre>' + escape(json.dumps(comparison, ensure_ascii=False, indent=2)) + '</pre>' if comparison else '<p class="empty">尚未找到实际运行的两模型对照结果。</p>'
    validation_time = next((validation.get(key) for key in ['generated_at', 'validated_at', 'checked_at', 'finished_at']
                            if validation.get(key)), '尚未记录')
    audit_html = ('<p class="caption">本报告读取的验证记录时间（UTC）：' + escape(validation_time)
                  + '。完整验证记录见最终数据包中的 validation.json。</p><pre>'
                  + escape(json.dumps(validation or {'status': 'pending', 'note': '最终结构验证尚未记录；网络完整性须另行核查。'}, ensure_ascii=False, indent=2)) + '</pre>')
    quality_html = '<pre>' + escape(json.dumps(quality, ensure_ascii=False, indent=2)) + '</pre>'
    counts = Counter(p.get('track', 'unknown') for p in papers)
    track_caption = '；'.join(str(k) + ' ' + str(v) for k, v in sorted(counts.items()))
    export_rows = ''.join('<li><button class="export" data-export="' + str(i) + '">' + escape(e['name'])
                          + '</button><span>' + f"{e['size_bytes'] / 1024 / 1024:.2f} MB" + '</span></li>' for i, e in enumerate(exports))
    frontend = {'papers': sample_rows, 'topics': [{'topic_id': t.get('topic_id'), 'keywords': t.get('keywords', []), 'size': t.get('size', 0)} for t in topics],
                'heatmap': heatmap, 'trends': trends, 'total_papers': len(papers), 'model_backend': backend,
                'venues': config.get('venues', []), 'years': config.get('years', [])}
    body = TEMPLATE
    replacements = {
        '@@TIME@@': escape(utcnow()), '@@BACKEND@@': escape(backend), '@@TOTAL@@': number(len(papers)),
        '@@MAIN@@': number(len(main)), '@@ELIGIBLE@@': number(len(eligible)), '@@MISSING@@': number(missing),
        '@@ASSIGNED@@': number(len(assignments)), '@@REVIEWS@@': number(len(reviews)), '@@TOPICS@@': number(len(topics)),
        '@@SAMPLE@@': number(len(sample)), '@@COVERAGE@@': coverage_table, '@@OFFICIAL@@': official_table,
        '@@DETAILS@@': detail_html,
        '@@RECON@@': recon_table, '@@CHANGES@@': changes_table, '@@EXCLUSIONS@@': exclusions_html,
        '@@TOPICCARDS@@': topic_html, '@@SCORES@@': score_table, '@@REVIEWREASON@@': escape(review_reason),
        '@@ACCEPTANCEREASON@@': escape(acceptance_reason), '@@DECISIONS@@': decision_table,
        '@@IDEAS@@': ideas_html, '@@MODELS@@': model_json_html, '@@COMPARISON@@': comparison_html,
        '@@AUDIT@@': audit_html, '@@QUALITY@@': quality_html, '@@TRACKS@@': escape(track_caption),
        '@@EXPORTS@@': export_rows, '@@DATA@@': script_json(frontend), '@@EXPORTDATA@@': script_json(exports)}
    # One pass avoids accidental interpretation of replacement tokens in source text.
    import re
    body = re.sub(r'@@[A-Z]+@@', lambda match: replacements.get(match.group(0), match.group(0)), body)
    target = output / 'report.html'
    atomic_write(target, body)
    return {'status': 'completed', 'path': str(target), 'backend': backend, 'total_papers': len(papers),
            'observed_main_accepted': len(main), 'model_eligible': len(eligible), 'assigned_papers': len(assignments),
            'browser_sample_rows': len(sample), 'embedded_exports': len(exports), 'size_bytes': target.stat().st_size,
            'sha256': hashlib.sha256(target.read_bytes()).hexdigest()}


TEMPLATE = r'''<!doctype html>
<html lang="zh-CN">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data: blob:; connect-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'">
<title>AI 研究趋势 · 三会九届证据报告</title>
<style>
:root{--ink:#173337;--muted:#667a7c;--paper:#f3f2ed;--card:#fff;--line:#dde4df;--teal:#14786e;--mint:#e5f1e9;--orange:#d87937;--red:#a85442;--shadow:0 10px 35px #17333708}
*{box-sizing:border-box}html{scroll-behavior:smooth;scroll-padding-top:78px}body{margin:0;background:var(--paper);color:var(--ink);font:15px/1.75 system-ui,-apple-system,"Segoe UI","Microsoft YaHei",sans-serif}a{color:var(--teal);text-decoration:none}a:hover{text-decoration:underline}button,input,select{font:inherit}button{cursor:pointer}nav{position:sticky;top:0;background:#f9faf6f2;backdrop-filter:blur(10px);z-index:5;border-bottom:1px solid var(--line)}.nav-inner{max-width:1360px;margin:auto;display:flex;align-items:center;justify-content:space-between;padding:14px 30px;gap:20px}.brand{font-weight:800;letter-spacing:.08em;font-size:13px}.nav-links{display:flex;gap:22px;font-size:13px;flex-wrap:wrap}.nav-links a{color:var(--muted)}main{max-width:1360px;margin:auto;padding:0 30px 70px}.hero{padding:64px 0 38px;display:grid;grid-template-columns:1.6fr 1fr;gap:60px}.eyebrow{font:700 11px/1.6 ui-monospace,monospace;letter-spacing:.14em;color:var(--teal);text-transform:uppercase}h1{font-size:clamp(30px,4.5vw,58px);letter-spacing:-.04em;line-height:1.18;margin:18px 0 22px;font-weight:800}h1 em{font-style:normal;color:var(--teal)}.lead{max-width:690px;color:var(--muted);font-size:16px}.hero-note{border-top:3px solid var(--ink);padding:18px 0;align-self:end}.hero-note p{margin:8px 0;font-size:13px;color:var(--muted)}.hero-note strong{color:var(--ink)}.scope{font-size:20px;font-weight:750}.metrics{display:grid;grid-template-columns:repeat(4,1fr);gap:16px;margin-bottom:36px}.metric{background:var(--card);border:1px solid var(--line);padding:22px 24px;border-radius:10px;box-shadow:var(--shadow)}.metric .value{font:700 35px/1.2 ui-monospace,monospace;letter-spacing:-.04em}.metric .label{margin:7px 0 3px;font-weight:650}.metric small,.caption{font-size:12px;color:var(--muted);line-height:1.7}.metric.accent{background:var(--teal);color:#fff}.metric.accent small{color:#d5ebe2}.notice{border-left:3px solid var(--orange);background:#fff6e9;padding:16px 20px;font-size:13px;margin:20px 0}.section{padding-top:36px;margin-top:25px;border-top:1px solid #d4ded7}.section-head{display:flex;gap:25px;align-items:flex-end;justify-content:space-between;margin-bottom:18px}.section-head h2{font-size:27px;letter-spacing:-.025em;margin:5px 0 0}.section-head p{max-width:670px;color:var(--muted);font-size:13px;margin:0}.section-num{font:600 11px/1.5 ui-monospace,monospace;color:var(--teal);letter-spacing:.1em}.panel{background:var(--card);padding:25px;border:1px solid var(--line);border-radius:10px;box-shadow:var(--shadow);margin:18px 0}.panel h3{font-size:17px;margin:0 0 12px}.table-wrap{overflow:auto;max-height:610px;border:1px solid var(--line);border-radius:7px;background:#fff}table{border-collapse:collapse;width:100%;font-size:12px;line-height:1.55}th{text-align:left;background:#edf2ed;position:sticky;top:0;z-index:1;font-weight:650;color:var(--ink);white-space:nowrap}td,th{padding:11px 13px;border-bottom:1px solid #e9eeea;vertical-align:top}td{max-width:520px;min-width:60px}td:first-child{font-weight:650;white-space:nowrap}tbody tr:hover{background:#f7f9f5}.badge{padding:3px 7px;border-radius:4px;font:600 10px/1.6 ui-monospace,monospace;background:var(--mint);color:var(--teal);white-space:nowrap}.positive{color:var(--teal);font-weight:700}.negative{color:var(--red);font-weight:700}details{margin:12px 0}summary{cursor:pointer;font-size:13px;font-weight:650;padding:8px 0}pre{font-size:11px;line-height:1.65;white-space:pre-wrap;overflow-wrap:anywhere;background:#f4f6f1;padding:16px;border-radius:5px;max-height:450px;overflow:auto}ul{padding-left:20px}.toolbar{display:flex;gap:12px;flex-wrap:wrap;margin:14px 0}.toolbar input,.toolbar select{border:1px solid #cdd9d2;border-radius:5px;background:white;padding:9px 12px;color:var(--ink);font-size:13px}.toolbar input{flex:1;min-width:250px}.small-button{border:1px solid #cdd9d2;background:#fff;color:var(--ink);padding:7px 13px;border-radius:5px;font-size:12px}.small-button:disabled{opacity:.4;cursor:default}.empty{padding:18px;color:var(--muted);background:#f6f7f2;border-radius:6px;font-size:13px}.topic-grid{display:grid;grid-template-columns:1fr 1fr;gap:12px;align-items:start}.topic-card{background:white;border:1px solid var(--line);border-radius:8px;padding:4px 18px;margin:0}.topic-card summary{display:flex;gap:10px;align-items:center;list-style:none;min-height:58px}.topic-card summary strong{font-size:13px;line-height:1.4;font-weight:650;flex:1}.topic-card summary b{font:600 11px/1.4 ui-monospace,monospace;white-space:nowrap;color:var(--muted)}.topic-no{font:600 10px/1.5 ui-monospace,monospace;background:var(--mint);padding:4px 7px;border-radius:4px}.topic-card ol{padding-left:20px;font-size:12px}.topic-card li{padding:7px 0}.topic-card small{display:block;font:10px/1.5 ui-monospace,monospace;color:var(--muted);overflow-wrap:anywhere}.keywords{color:var(--muted);font-size:12px;border-top:1px solid var(--line);padding-top:10px}.idea-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:18px}.idea{padding:24px;background:#e9eee3;border-radius:8px}.idea h3{font-size:18px;line-height:1.45}.idea p{font-size:13px}.exports{padding:0;list-style:none;display:grid;grid-template-columns:1fr 1fr;gap:8px}.exports li{display:flex;justify-content:space-between;align-items:center;gap:14px;padding:8px 12px;border:1px solid var(--line);border-radius:4px}.exports span{font:10px ui-monospace,monospace;color:var(--muted);white-space:nowrap}.export{border:0;background:none;padding:0;text-align:left;color:var(--teal);font:11px/1.7 ui-monospace,monospace;overflow-wrap:anywhere}.export:hover{text-decoration:underline}.paper-title{min-width:300px}.paper-authors{font-size:11px;color:var(--muted);margin-top:5px}.abstract{white-space:pre-wrap;font-size:12px;color:var(--muted);max-width:950px}.heat-table th,.heat-table td{min-width:110px}.heat-table th:first-child{min-width:250px}.heat-table td{font:600 12px/1.5 ui-monospace,monospace}.heat-key{display:flex;gap:8px;align-items:center;font-size:11px;color:var(--muted)}.heat-key i{display:block;width:100px;height:8px;border-radius:4px;background:linear-gradient(90deg,#f5f8f2,#12766c)}.pager{display:flex;gap:12px;justify-content:flex-end;align-items:center;font-size:12px;color:var(--muted);margin-top:12px}footer{margin-top:45px;border-top:1px solid var(--line);padding:22px 0;font-size:11px;color:var(--muted)}.sr-only{position:absolute;width:1px;height:1px;margin:-1px;overflow:hidden;clip:rect(0,0,0,0)}@media(max-width:850px){.hero{grid-template-columns:1fr;gap:12px;padding-top:35px}.metrics{grid-template-columns:1fr 1fr}.section-head{display:block}.section-head p{margin-top:12px}.topic-grid,.idea-grid,.exports{grid-template-columns:1fr}.nav-links{gap:10px}.nav-inner,main{padding-left:18px;padding-right:18px}.panel{padding:17px}}@media print{nav,.toolbar,.exports,.pager{display:none}.section{break-before:auto}.panel{box-shadow:none}.topic-card{break-inside:avoid}.table-wrap{max-height:none;overflow:visible}body{background:white}.hero{padding-top:10px}}
.detail-panel{border-top:3px solid var(--orange)}.detail-title{display:flex;gap:15px;align-items:center;justify-content:space-between}.detail-title h3{margin:0}.detail-metrics{display:grid;grid-template-columns:repeat(6,1fr);gap:12px;margin:20px 0}.detail-metrics div{border-right:1px solid var(--line);padding-right:12px}.detail-metrics strong{display:block;font:700 26px/1.3 ui-monospace,monospace}.detail-metrics span{display:block;font-size:11px;color:var(--muted);margin-top:6px}@media(max-width:850px){.detail-metrics{grid-template-columns:repeat(3,1fr)}}
</style></head>
<body><nav aria-label="报告导航"><div class="nav-inner"><a class="brand" href="#top">AI RESEARCH / EVIDENCE ATLAS</a><div class="nav-links"><a href="#coverage">数据覆盖</a><a href="#topics">主题空间</a><a href="#changes">年度变化</a><a href="#papers">论文检索</a><a href="#audit">审计与下载</a></div></div></nav>
<main id="top"><header class="hero"><div><span class="eyebrow">ICLR / ICML / NEURIPS · 2024–2026</span><h1>从公开论文，<br>观察 <em>AI 研究趋势</em>。</h1><p class="lead">九个会议届次，共享主题空间，逐条可追溯。研究对象是已观察的录用成果；官网规模统计与公开评审队列分别核验。</p></div><aside class="hero-note"><div class="scope">3 个会议 · 3 年 · 9 个届次</div><p>报告后端：<strong>@@BACKEND@@</strong> · 自动主题：<strong>@@TOPICS@@</strong></p><p>生成时间（UTC）：@@TIME@@</p><p>数据与模型结论只反映本次快照。所有缺失、受阻和未证明完整的范围均保留，不按零值处理。</p></aside></header>
<div class="metrics"><div class="metric"><div class="value">@@TOTAL@@</div><div class="label">清洗后去重论文记录</div><small>包含全部已观察赛道及决定状态</small></div><div class="metric"><div class="value">@@MAIN@@</div><div class="label">明确主会录用成果</div><small>热度占比使用这一观察分母</small></div><div class="metric accent"><div class="value">@@ASSIGNED@@</div><div class="label">本后端实际主题归属</div><small>合格主会摘要 @@ELIGIBLE@@ 篇</small></div><div class="metric"><div class="value">@@MISSING@@</div><div class="label">主会待补标题或摘要</div><small>公开正式评审输入 @@REVIEWS@@ 条</small></div></div>
<div class="notice"><strong>解读边界：</strong>已接收成果存在发表时滞和选择偏差。主题增长只提供阅读与检索线索；不能证明新颖性、因果关系或投稿优势。没有独立完整决定队列，不发布分主题录用率。</div>

<section class="section" id="coverage"><div class="section-head"><div><span class="section-num">01 / SOURCE COVERAGE</span><h2>先确认看到了什么</h2></div><p>逐届并排展示官网状态、真实采集数量、主会摘要覆盖与官方登记规模。登记数与实采数相同也不证明投稿队列完整。</p></div>
@@DETAILS@@@@COVERAGE@@<p class="caption">¹ 登记列采用该届标记 preferred 的来源；所有版本均在下方并列保留。比例可大于 100%，此时应检查来源日期、赛道和去重口径。赛道分布：@@TRACKS@@。</p>
<details><summary>官方规模统计：原分母、证据等级、时间与冲突版本</summary>@@OFFICIAL@@</details><details><summary>全部来源与实采名单差值</summary>@@RECON@@</details></section>

<section class="section" id="topics"><div class="section-head"><div><span class="section-num">02 / SHARED TOPIC SPACE</span><h2>同一空间里的研究主题</h2></div><p>全部合格主会的标题与摘要共同拟合；年份、会议、评分和决定不作为向量特征。主题数字只在本后端内有意义。</p></div>
<div class="panel"><h3>共同年份的三会热度</h3><div class="toolbar"><label for="heat-year">比较年份</label><select id="heat-year"></select><label for="heat-limit">主题数量</label><select id="heat-limit"><option value="20">规模最大的 20 个主题</option><option value="50">全部主题</option></select></div><div class="heat-key">较低 <i></i> 较高 · 单元格为该届全部已观察主会录用中的占比</div><div id="heatmap" aria-live="polite"></div><p class="caption">某届实采明确主会不足登记来源的 90% 时，该年不进入三会热度矩阵。门槛用于排除明显缺口，通过门槛不是完整性认证。没有归属的主会论文仍在分母中。</p><details><summary>被排除年份及理由</summary><ul>@@EXCLUSIONS@@</ul></details></div>
<div class="topic-grid">@@TOPICCARDS@@</div></section>

<section class="section" id="changes"><div class="section-head"><div><span class="section-num">03 / CHANGE &amp; UNCERTAINTY</span><h2>变化有分母，也有边界</h2></div><p>按最新可比较年份、占比变化排序，展示最多 24 条。百分点由同会议两个已观察年份计算；未采到的年份不补零。</p></div>@@CHANGES@@
<div class="panel"><h3>公开评审与条件录用率</h3><p class="caption">@@REVIEWREASON@@</p>@@SCORES@@<p class="notice">@@ACCEPTANCEREASON@@</p><details><summary>公开决定样本状态：未知、撤稿与拒稿分别保留</summary>@@DECISIONS@@</details></div>
<h3>供人工复核的选题起点</h3><p class="caption">以下内容由增长表与代表论文生成，只是待验证的研究假设。自动讲述没有替代当前相关工作检索及人审。</p><div class="idea-grid">@@IDEAS@@</div></section>

<section class="section" id="papers"><div class="section-head"><div><span class="section-num">04 / PAPER EXPLORER</span><h2>回到具体论文</h2></div><p>浏览器载入按会议、年份、赛道分层的 @@SAMPLE@@ 条记录，全部清洗记录共 @@TOTAL@@ 条。此处搜索范围为浏览样本；全量 CSV/JSONL 随报告内嵌下载。</p></div>
<div class="panel"><div class="toolbar"><label class="sr-only" for="paper-query">检索标题、摘要和作者</label><input id="paper-query" placeholder="检索标题、摘要或作者…" type="search"><label class="sr-only" for="paper-venue">会议</label><select id="paper-venue"><option value="">全部会议</option></select><label class="sr-only" for="paper-year">年份</label><select id="paper-year"><option value="">全部年份</option></select><label class="sr-only" for="paper-track">赛道</label><select id="paper-track"><option value="">全部赛道</option></select></div><p id="paper-count" class="caption" aria-live="polite"></p><div class="table-wrap"><table><thead><tr><th>届次 / 赛道</th><th>论文与摘要</th><th>主题</th></tr></thead><tbody id="paper-body"></tbody></table></div><div class="pager"><button id="prev" class="small-button">上一页</button><span id="page-label"></span><button id="next" class="small-button">下一页</button></div></div></section>

<section class="section" id="audit"><div class="section-head"><div><span class="section-num">05 / REPRODUCIBILITY</span><h2>让结论可以复核</h2></div><p>LSA 与 MiniLM 在同一论文 ID 交集上比较 ARI/AMI。一致性不是主题质量或正确率；50 个主题只是可调的分析粒度。</p></div><div class="panel"><h3>两模型对照与运行配置</h3>@@COMPARISON@@@@MODELS@@<p class="caption">LSA：词/短语 TF-IDF → TruncatedSVD → L2 → MiniBatchKMeans。语义版：固定 revision 的 MiniLM 量化 ONNX → attention-mask 池化 → 长文分块加权 → L2 → KMeans。以实际运行清单为准。</p></div>
<div class="panel"><h3>质量门槛与验证证据</h3><p class="caption">离线结构测试、哈希和 ID 一致性不等于网络覆盖完整性证明。采集受阻的评审分析仍未完成。</p><details><summary>报告读取的结构验证快照</summary>@@AUDIT@@</details><details><summary>数据质量、摘要覆盖与隔离状态</summary>@@QUALITY@@</details></div>
<div class="panel"><h3>离线下载全量数据与统计文件</h3><p class="caption">文件以 gzip 压缩、Base64 编码嵌入本报告，点击后还原原始字节下载，页面无需联网。现代浏览器使用内置解压；若浏览器不支持，则下载 .gz 文件。原始网页快照和完整可运行源码另见最终数据包、源码包。</p><ul class="exports">@@EXPORTS@@</ul><p id="download-status" class="caption" aria-live="polite"></p></div></section>
<footer>独立实现，问题意识参考 AI-Paper-Trends。采集只使用公开来源，不绕过验证。原始快照、输入哈希、来源统计和各阶段状态请结合完整发行文件阅读。</footer></main>
<script type="application/json" id="report-data">@@DATA@@</script><script type="application/json" id="exports-data">@@EXPORTDATA@@</script>
<script>
'use strict';
const DATA=JSON.parse(document.getElementById('report-data').textContent);
const EXPORTS=JSON.parse(document.getElementById('exports-data').textContent);
const el=(tag,text,cls)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=String(text);if(cls)n.className=cls;return n;};
const anchor=(text,url)=>{let valid=false;try{const u=new URL(url);valid=(u.protocol==='https:'||u.protocol==='http:')&&!u.username&&!u.password;}catch(e){}const n=el(valid?'a':'span',text);if(valid){n.href=url;n.target='_blank';n.rel='noopener noreferrer';}return n;};
const topicLabel=id=>{const t=DATA.topics.find(x=>String(x.topic_id)===String(id));return t?'T'+id+' '+(Array.isArray(t.keywords)?t.keywords.slice(0,3).join(' / '):String(t.keywords||'')):'T'+id;};
const addOptions=(id,values)=>{const s=document.getElementById(id);values.forEach(v=>{const o=el('option',v);o.value=String(v);s.append(o);});};
const heatYear=document.getElementById('heat-year');
addOptions('heat-year',[...new Set(DATA.heatmap.map(r=>String(r.year)))].sort());
if(heatYear.options.length)heatYear.value=heatYear.options[heatYear.options.length-1].value;
function renderHeat(){
 const container=document.getElementById('heatmap');container.replaceChildren();
 const year=heatYear.value;const rows=DATA.heatmap.filter(r=>String(r.year)===year);
 if(!rows.length){container.append(el('p','没有通过共同年份覆盖门槛的数据；未将缺失年份绘为零。','empty'));return;}
 const venues=DATA.venues.filter(v=>rows.some(r=>r.venue===v));
 const limit=Number(document.getElementById('heat-limit').value);const topics=DATA.topics.slice(0,limit);
 const max=Math.max(...rows.map(r=>Number(r.share_percent)||0),1);
 const wrapper=el('div',undefined,'table-wrap');const tab=el('table',undefined,'heat-table');const head=el('thead');const tr=el('tr');tr.append(el('th','主题（自动标签）'));venues.forEach(v=>tr.append(el('th',v+' '+year)));head.append(tr);tab.append(head);const body=el('tbody');
 topics.forEach(t=>{const row=el('tr');row.append(el('th',topicLabel(t.topic_id)));venues.forEach(v=>{const source=rows.find(r=>String(r.topic_id)===String(t.topic_id)&&r.venue===v);const td=el('td');if(source){const share=Number(source.share_percent);td.textContent=share.toFixed(2)+'%';const alpha=share/max;td.style.backgroundColor='rgba(20,120,110,'+(0.05+alpha*0.85).toFixed(3)+')';td.style.color=alpha>.58?'#fff':'#173337';td.title=String(source.paper_count)+' / '+String(source.denominator);}else td.textContent='—';row.append(td);});body.append(row);});tab.append(body);wrapper.append(tab);container.append(wrapper);
}
heatYear.addEventListener('change',renderHeat);document.getElementById('heat-limit').addEventListener('change',renderHeat);renderHeat();
addOptions('paper-venue',[...new Set(DATA.papers.map(p=>p.venue))].sort());addOptions('paper-year',[...new Set(DATA.papers.map(p=>String(p.year)))].sort());addOptions('paper-track',[...new Set(DATA.papers.map(p=>p.track))].sort());
let page=0;const pageSize=50;let filtered=DATA.papers;
function filterPapers(){const query=document.getElementById('paper-query').value.toLocaleLowerCase().trim();const venue=document.getElementById('paper-venue').value,year=document.getElementById('paper-year').value,track=document.getElementById('paper-track').value;filtered=DATA.papers.filter(p=>(!venue||p.venue===venue)&&(!year||String(p.year)===year)&&(!track||p.track===track)&&(!query||(p.title+' '+p.abstract+' '+p.authors.join(' ')).toLocaleLowerCase().includes(query)));page=0;renderPapers();}
function renderPapers(){const body=document.getElementById('paper-body');body.replaceChildren();const count=filtered.length;const pages=Math.max(1,Math.ceil(count/pageSize));page=Math.min(Math.max(page,0),pages-1);filtered.slice(page*pageSize,(page+1)*pageSize).forEach(p=>{const tr=el('tr');const group=el('td',p.venue+' '+p.year);group.append(el('div',p.track+' / '+p.decision,'caption'));const text=el('td',undefined,'paper-title');text.append(anchor(p.title,p.source_url));text.append(el('div',p.authors.join('; '),'paper-authors'));const details=el('details');details.append(el('summary','摘要与论文 ID'));details.append(el('p',p.abstract||'未取得摘要','abstract'));details.append(el('small',p.paper_id,'caption'));text.append(details);tr.append(group,text,el('td',p.topic_id===null||p.topic_id===undefined?'未归属':topicLabel(p.topic_id)));body.append(tr);});document.getElementById('paper-count').textContent='浏览样本内匹配 '+count.toLocaleString()+' / '+DATA.papers.length.toLocaleString()+' 条；完整数据 '+DATA.total_papers.toLocaleString()+' 条。';document.getElementById('page-label').textContent=(page+1)+' / '+pages;document.getElementById('prev').disabled=page===0;document.getElementById('next').disabled=page>=pages-1;}
['paper-venue','paper-year','paper-track'].forEach(id=>document.getElementById(id).addEventListener('change',filterPapers));let queryTimer;document.getElementById('paper-query').addEventListener('input',()=>{clearTimeout(queryTimer);queryTimer=setTimeout(filterPapers,150);});document.getElementById('prev').addEventListener('click',()=>{page--;renderPapers();});document.getElementById('next').addEventListener('click',()=>{page++;renderPapers();});renderPapers();
async function downloadFile(i){const f=EXPORTS[i],status=document.getElementById('download-status');status.textContent='正在还原 '+f.name+'…';try{const raw=atob(f.data),bytes=new Uint8Array(raw.length);for(let j=0;j<raw.length;j++)bytes[j]=raw.charCodeAt(j);let blob=new Blob([bytes],{type:'application/gzip'}),name=f.name.split('/').pop();if(typeof DecompressionStream==='function'){const stream=blob.stream().pipeThrough(new DecompressionStream('gzip'));blob=await new Response(stream).blob();if(blob.size!==f.size_bytes)throw new Error('文件大小校验失败');if(window.crypto&&crypto.subtle){const hash=await crypto.subtle.digest('SHA-256',await blob.arrayBuffer());const hex=Array.from(new Uint8Array(hash),b=>b.toString(16).padStart(2,'0')).join('');if(hex!==f.sha256)throw new Error('SHA256 校验失败');}}else name+='.gz';const url=URL.createObjectURL(blob);const a=el('a');a.href=url;a.download=name;document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),60000);status.textContent='已准备下载 '+name+' · 原始 SHA256 '+f.sha256;}catch(e){status.textContent='下载失败：'+e.message;}}
document.querySelectorAll('[data-export]').forEach(button=>button.addEventListener('click',()=>downloadFile(Number(button.dataset.export))));
</script></body></html>'''
