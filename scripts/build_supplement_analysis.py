#!/usr/bin/env python3
"""补充轮的两张结果图与三张表：统一摘要口径、稳健性检验、评分分布。

产出：
  data/supplement/tables/abstract_length.csv          统一为空白分词口径（覆盖交付口径）
  data/supplement/tables/topic_change_stability.csv   去掉模型标记的低相似度论文后的占比变化
  data/supplement/tables/topic_score_distribution.csv ICLR 2025 六个重点主题的评分分布
  reports/figures/fig2_abstract_length_distribution.png
  reports/figures/fig5_score_distribution_iclr2025.png
  data/supplement/analysis.json                       上列结果的机器可读汇总

图用内联 SVG 生成，再用本机 Edge 无头模式栅格化为 PNG（无第三方绘图库依赖）。
"""
from __future__ import annotations

import csv
import json
import subprocess
import sys
import zipfile
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ZIP = ROOT / "public_review_scores_and_evidence.zip"
TABLE_DIR = ROOT / "data" / "supplement" / "tables"
FIG_DIR = ROOT / "reports" / "figures"
TMP = ROOT / ".workbuddy" / "tmp" / "figs"
EDGE = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")
VENUES = ("ICLR", "ICML", "NeurIPS")
COLORS = {"ICLR": "#2f6f9f", "ICML": "#b3701e", "NeurIPS": "#4a7c59"}
HIGHLIGHT = ("41", "20", "15")
FOCUS = ["35", "20", "1", "21", "41", "15"]


def quantile(values: list[float], q: float) -> float:
    v = sorted(values)
    if not v:
        return float("nan")
    k = (len(v) - 1) * q
    lo = int(k)
    hi = min(lo + 1, len(v) - 1)
    return v[lo] + (v[hi] - v[lo]) * (k - lo)


def mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else float("nan")


def sd(values: list[float]) -> float:
    if len(values) < 2:
        return float("nan")
    m = mean(values)
    return (sum((x - m) ** 2 for x in values) / (len(values) - 1)) ** 0.5


def spearman(xs: list[float], ys: list[float]) -> float:
    def ranks(v):
        order = sorted(range(len(v)), key=lambda i: v[i])
        r = [0.0] * len(v)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and v[order[j + 1]] == v[order[i]]:
                j += 1
            avg = (i + j) / 2 + 1
            for k in range(i, j + 1):
                r[order[k]] = avg
            i = j + 1
        return r

    rx, ry = ranks(xs), ranks(ys)
    mx, my = mean(rx), mean(ry)
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    den = (sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry)) ** 0.5
    return num / den if den else float("nan")


def load_papers() -> dict[str, dict]:
    with open(ROOT / "papers.csv", encoding="utf-8-sig", newline="") as fh:
        return {r["paper_id"]: r for r in csv.DictReader(fh)}


def load_assignments() -> dict[str, dict]:
    with open(ROOT / "data" / "model" / "assignments.csv", encoding="utf-8-sig", newline="") as fh:
        return {r["paper_id"]: r for r in csv.DictReader(fh)}


def load_names() -> dict[str, str]:
    with open(ROOT / "data" / "model" / "topic_review.csv", encoding="utf-8-sig", newline="") as fh:
        return {r["topic_id"]: r["human_name"] for r in csv.DictReader(fh)}


def load_ledger() -> list[dict]:
    with zipfile.ZipFile(ZIP) as zf, zf.open("score_ledger/paper_scores.csv") as fh:
        import io
        return list(csv.DictReader(io.TextIOWrapper(fh, encoding="utf-8-sig", newline="")))


# ---------------------------------------------------------------- 分析


def abstract_stats(papers: dict[str, dict]) -> list[dict]:
    grouped = defaultdict(list)
    for p in papers.values():
        if p["track"] != "main" or p["decision"] != "accepted" or not p["abstract"].strip():
            continue
        grouped[(p["venue"], p["year"])].append(len(p["abstract"].split()))
    rows = []
    for venue in VENUES:
        for year in ("2024", "2025", "2026"):
            v = grouped.get((venue, year), [])
            if not v:
                continue
            rows.append({"venue": venue, "year": year, "n": len(v), "mean": mean(v),
                         "median": quantile(v, 0.5), "q1": quantile(v, 0.25),
                         "q3": quantile(v, 0.75), "p95": quantile(v, 0.95)})
    overall = [x for v in grouped.values() for x in v]
    rows.append({"venue": "全部", "year": "三届合并", "n": len(overall), "mean": mean(overall),
                 "median": quantile(overall, 0.5), "q1": quantile(overall, 0.25),
                 "q3": quantile(overall, 0.75), "p95": quantile(overall, 0.95)})
    return rows


def stability(papers: dict[str, dict], assign: dict[str, dict], names: dict[str, str]) -> list[dict]:
    def counts(keep):
        c = {"2024": Counter(), "2025": Counter()}
        n = {"2024": 0, "2025": 0}
        for pid, a in assign.items():
            year = papers[pid]["year"]
            if year not in n or not keep(a):
                continue
            n[year] += 1
            c[year][a["topic_id"]] += 1
        return c, n

    full_c, full_n = counts(lambda a: True)
    rob_c, rob_n = counts(lambda a: a["outlier"] == "False")

    def delta(c, n, t):
        return (c["2025"][t] / n["2025"] - c["2024"][t] / n["2024"]) * 100

    topics = set(full_c["2024"]) | set(full_c["2025"])
    ranked = sorted(topics, key=lambda t: -delta(full_c, full_n, t))
    rank_full = {t: i + 1 for i, t in enumerate(ranked)}
    ranked_rob = sorted(topics, key=lambda t: -delta(rob_c, rob_n, t))
    rank_rob = {t: i + 1 for i, t in enumerate(ranked_rob)}

    rows = []
    for t in ranked:
        rows.append({"topic_id": t, "topic": names.get(t, t),
                     "rank_full": rank_full[t], "rank_no_outlier": rank_rob[t],
                     "n_2024_full": full_c["2024"][t], "n_2025_full": full_c["2025"][t],
                     "change_full": delta(full_c, full_n, t),
                     "n_2024_no_outlier": rob_c["2024"][t], "n_2025_no_outlier": rob_c["2025"][t],
                     "change_no_outlier": delta(rob_c, rob_n, t)})
    return rows


def score_distribution(ledger: list[dict], assign: dict[str, dict], names: dict[str, str],
                       venue="ICLR", year="2025") -> tuple[list[dict], dict]:
    per_topic = defaultdict(list)
    for r in ledger:
        if r["venue"] != venue or r["year"] != year:
            continue
        per_topic[r["topic_id"]].append(float(r["mean_rating"]))
    total = sum(len(v) for v in per_topic.values())
    rows = []
    for t, vals in per_topic.items():
        rows.append({"topic_id": t, "topic": names.get(t, t), "n": len(vals),
                     "share_percent": len(vals) / total * 100 if total else 0,
                     "mean": mean(vals), "sd": sd(vals), "q1": quantile(vals, 0.25),
                     "median": quantile(vals, 0.5), "q3": quantile(vals, 0.75),
                     "p10": quantile(vals, 0.1), "p90": quantile(vals, 0.9)})
    rows.sort(key=lambda r: -r["n"])
    meta = {
        "venue": venue, "year": year, "papers": total, "topics": len(rows),
        "mean_rating_all": mean([float(r["mean_rating"]) for r in ledger
                                 if r["venue"] == venue and r["year"] == year]),
        "sd_rating_all": sd([float(r["mean_rating"]) for r in ledger
                             if r["venue"] == venue and r["year"] == year]),
        "spearman_share_vs_mean": spearman([r["share_percent"] for r in rows], [r["mean"] for r in rows]),
        "focus": sorted([r for r in rows if r["topic_id"] in FOCUS],
                        key=lambda r: FOCUS.index(r["topic_id"])),
    }
    return rows, meta


# ---------------------------------------------------------------- SVG


def svg_text(x, y, s, size=12, fill="#333", anchor="start", weight="400", family="Microsoft YaHei, Segoe UI, sans-serif"):
    return (f'<text x="{x:.1f}" y="{y:.1f}" font-family="{family}" font-size="{size}" '
            f'fill="{fill}" text-anchor="{anchor}" font-weight="{weight}">{s}</text>')


def fig_abstract(rows: list[dict]) -> str:
    W, H = 900, 420
    left, right, top, bottom = 62, 150, 64, 66
    ymin, ymax = 120, 300
    plot_w = W - left - right
    plot_h = H - top - bottom

    def y(v):
        return top + plot_h - (v - ymin) / (ymax - ymin) * plot_h

    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">',
             f'<rect width="{W}" height="{H}" fill="#ffffff"/>']
    parts.append(svg_text(left - 46, 28, "摘要英文词数（统一口径：空白分词）", 15, "#1a1a1a", weight="600"))
    parts.append(svg_text(left - 46, 48, "9 届 37,662 篇主会论文；竖条为四分位区间，横线为中位数，圆点为均值", 11, "#666"))

    for gv in range(ymin, ymax + 1, 20):
        parts.append(f'<line x1="{left}" y1="{y(gv):.1f}" x2="{left + plot_w}" y2="{y(gv):.1f}" '
                     f'stroke="#eef0f2" stroke-width="1"/>')
        parts.append(svg_text(left - 10, y(gv) + 4, str(gv), 11, "#888", anchor="end"))
    parts.append(f'<line x1="{left}" y1="{y(ymin):.1f}" x2="{left + plot_w}" y2="{y(ymin):.1f}" stroke="#c9ced4"/>')

    overall = rows[-1]
    parts.append(f'<line x1="{left}" y1="{y(overall["median"]):.1f}" x2="{left + plot_w}" '
                 f'y2="{y(overall["median"]):.1f}" stroke="#c0392b" stroke-width="1.2" stroke-dasharray="5 4"/>')
    parts.append(svg_text(left + plot_w + 8, y(overall["median"]) + 4,
                          f'全体中位数 {overall["median"]:.0f} 词', 11, "#c0392b"))

    bands = [(r, i) for i, r in enumerate(rows[:-1])]
    step = plot_w / len(bands)
    for r, i in bands:
        cx = left + step * (i + 0.5)
        color = COLORS[r["venue"]]
        bw = 30
        parts.append(f'<rect x="{cx - bw / 2:.1f}" y="{y(r["q3"]):.1f}" width="{bw}" '
                     f'height="{max(2.0, y(r["q1"]) - y(r["q3"])):.1f}" fill="{color}" fill-opacity="0.18" '
                     f'stroke="{color}" stroke-width="1"/>')
        parts.append(f'<line x1="{cx - bw / 2:.1f}" y1="{y(r["median"]):.1f}" x2="{cx + bw / 2:.1f}" '
                     f'y2="{y(r["median"]):.1f}" stroke="{color}" stroke-width="2.4"/>')
        parts.append(f'<circle cx="{cx:.1f}" cy="{y(r["mean"]):.1f}" r="3.6" fill="#ffffff" '
                     f'stroke="{color}" stroke-width="1.6"/>')
        parts.append(svg_text(cx, top + plot_h + 18, r["venue"], 11, "#444", anchor="middle"))
        parts.append(svg_text(cx, top + plot_h + 34, r["year"], 11, "#777", anchor="middle"))
        parts.append(svg_text(cx, y(r["median"]) - 8, f'{r["median"]:.0f}', 10, color, anchor="middle"))

    for i, v in enumerate(VENUES):
        lx = left + 6 + i * 96
        parts.append(f'<rect x="{lx}" y="{H - 24}" width="10" height="10" fill="{COLORS[v]}" fill-opacity="0.25" '
                     f'stroke="{COLORS[v]}"/>')
        parts.append(svg_text(lx + 16, H - 15, v, 11, "#555"))
    parts.append(svg_text(left + 330, H - 15, "单位：词；分母为各届主会录用且有摘要的论文", 11, "#888"))
    parts.append("</svg>")
    return "".join(parts)


def fig_scores(focus: list[dict], rows: list[dict], meta: dict) -> str:
    W, H = 1120, 470
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">',
             f'<rect width="{W}" height="{H}" fill="#ffffff"/>']
    parts.append(svg_text(24, 28, f"{meta['venue']} {meta['year']}：重点主题的评分分布与主题份额", 15, "#1a1a1a", weight="600"))
    parts.append(svg_text(24, 48, f"{meta['papers']:,} 篇有公开评分的录用论文，量表 1–10；点为论文级均分", 11, "#666"))

    # 左：水平箱线
    L, R, T, B = 24, 540, 78, 60
    x0, x1 = L + 190, R - 14
    lo = min(r["p10"] for r in focus) - 0.25
    hi = max(r["p90"] for r in focus) + 0.25
    def x(v):
        return x0 + (v - lo) / (hi - lo) * (x1 - x0)
    rows_y = [T + 24 + i * 46 for i in range(len(focus))]
    parts.append(svg_text(L, T - 8, "A 论文级均分的分布（箱=四分位，须=P10–P90）", 12, "#333", weight="600"))
    for gv in [lo + (hi - lo) * i / 5 for i in range(6)]:
        parts.append(f'<line x1="{x(gv):.1f}" y1="{T + 10}" x2="{x(gv):.1f}" y2="{rows_y[-1] + 26:.1f}" '
                     f'stroke="#eef0f2"/>')
        parts.append(svg_text(x(gv), rows_y[-1] + 44, f"{gv:.1f}", 11, "#888", anchor="middle"))
    for r, cy in zip(focus, rows_y):
        color = COLORS["ICLR"]
        parts.append(svg_text(x0 - 12, cy + 4, r["topic"][:14], 11.5, "#333", anchor="end"))
        parts.append(svg_text(x0 - 12, cy + 18, f'n={r["n"]}，占比 {r["share_percent"]:.1f}%', 10, "#888", anchor="end"))
        parts.append(f'<line x1="{x(r["p10"]):.1f}" y1="{cy:.1f}" x2="{x(r["p90"]):.1f}" y2="{cy:.1f}" '
                     f'stroke="{color}" stroke-width="1.2" stroke-opacity="0.55"/>')
        parts.append(f'<rect x="{x(r["q1"]):.1f}" y="{cy - 9:.1f}" width="{max(2.0, x(r["q3"]) - x(r["q1"])):.1f}" '
                     f'height="18" fill="{color}" fill-opacity="0.18" stroke="{color}" stroke-width="1"/>')
        parts.append(f'<line x1="{x(r["median"]):.1f}" y1="{cy - 9:.1f}" x2="{x(r["median"]):.1f}" '
                     f'y2="{cy + 9:.1f}" stroke="{color}" stroke-width="2.4"/>')
        parts.append(f'<circle cx="{x(r["mean"]):.1f}" cy="{cy:.1f}" r="3.2" fill="#ffffff" stroke="{color}" stroke-width="1.6"/>')

    # 右：散点 份额 vs 均值
    L2, R2, T2, B2 = 656, W - 20, T + 10, H - 92
    sx0, sx1 = L2 + 42, R2 - 74
    sy0, sy1 = T2 + 16, B2
    xs = [r["share_percent"] for r in rows]
    ys = [r["mean"] for r in rows]
    xmax = max(xs) * 1.06
    ymin, ymax = min(ys) - 0.15, max(ys) + 0.15

    def px(v):
        return sx0 + v / xmax * (sx1 - sx0)

    def py(v):
        return sy1 - (v - ymin) / (ymax - ymin) * (sy1 - sy0)

    parts.append(svg_text(L2, T - 8, "B 主题份额与平均评分（50 个主题）", 12, "#333", weight="600"))
    for i in range(5):
        gv = ymin + (ymax - ymin) * i / 4
        parts.append(f'<line x1="{sx0}" y1="{py(gv):.1f}" x2="{sx1}" y2="{py(gv):.1f}" stroke="#eef0f2"/>')
        parts.append(svg_text(sx0 - 8, py(gv) + 4, f"{gv:.1f}", 10.5, "#888", anchor="end"))
    for i in range(5):
        gv = xmax * i / 4
        parts.append(f'<line x1="{px(gv):.1f}" y1="{sy0}" x2="{px(gv):.1f}" y2="{sy1}" stroke="#f4f5f7"/>')
        parts.append(f'<line x1="{px(gv):.1f}" y1="{sy1}" x2="{px(gv):.1f}" y2="{sy1 + 4}" stroke="#c9ced4"/>')
        parts.append(svg_text(px(gv), sy1 + 16, f"{gv:.0f}", 11, "#555", anchor="middle"))
    parts.append(f'<line x1="{sx0}" y1="{sy1}" x2="{sx1}" y2="{sy1}" stroke="#c9ced4"/>')
    parts.append(f'<line x1="{sx0}" y1="{sy0}" x2="{sx0}" y2="{sy1}" stroke="#c9ced4"/>')
    parts.append(svg_text((sx0 + sx1) / 2, sy1 + 38, "该主题占本届评分子集的比例（%）", 11, "#666", anchor="middle"))
    cy_mid = (sy0 + sy1) / 2
    parts.append(f'<text x="{L2 - 18}" y="{cy_mid:.1f}" transform="rotate(-90 {L2 - 18} {cy_mid:.1f})" '
                 f'font-family="Microsoft YaHei, Segoe UI, sans-serif" font-size="11" fill="#666" '
                 f'text-anchor="middle">平均评分</text>')
    rmax = max(r["n"] for r in rows)
    for r in rows:
        hot = r["topic_id"] in HIGHLIGHT
        rad = 2.6 + (r["n"] / rmax) ** 0.5 * 5.6
        color = "#c0392b" if hot else "#2f6f9f"
        parts.append(f'<circle cx="{px(r["share_percent"]):.1f}" cy="{py(r["mean"]):.1f}" r="{rad:.1f}" '
                     f'fill="{color}" fill-opacity="{0.55 if hot else 0.28}" stroke="{color}" stroke-width="1"/>')
    # 重点主题改用图内注记，避免三条标签互相压住
    hot_rows = [r for r in rows if r["topic_id"] in HIGHLIGHT]
    hot_rows.sort(key=lambda r: r["share_percent"])
    box_x, box_y = sx0 + 8, sy0 + 8
    parts.append(f'<rect x="{box_x}" y="{box_y}" width="196" height="{18 * len(hot_rows) + 10}" '
                 f'fill="#ffffff" fill-opacity="0.92" stroke="#e3e6ea"/>')
    for i, r in enumerate(hot_rows):
        ly = box_y + 18 + i * 18
        parts.append(f'<circle cx="{box_x + 10}" cy="{ly - 4}" r="3.2" fill="#c0392b" fill-opacity="0.55" stroke="#c0392b"/>')
        parts.append(svg_text(box_x + 20, ly, f'{r["topic"]} {r["share_percent"]:.1f}%，均分 {r["mean"]:.2f}',
                              10, "#8c2f22"))
    rho = meta["spearman_share_vs_mean"]
    parts.append(svg_text(sx1 - 6, sy0 + 14, f'Spearman ρ = {rho:+.2f}', 10.5, "#666", anchor="end"))
    parts.append(svg_text(L2, H - 10, "红点＝2024→2025 增长前三；点径按论文数开方缩放", 10.5, "#888"))
    parts.append("</svg>")
    return "".join(parts)


HTML = """<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<style>html,body{{margin:0;padding:0;background:#fff;}}</style></head>
<body>{svg}</body></html>"""


def render(svg: str, name: str, size: tuple[int, int]) -> Path | None:
    TMP.mkdir(parents=True, exist_ok=True)
    html_path = TMP / f"{name}.html"
    html_path.write_text(HTML.format(svg=svg), encoding="utf-8")
    png = FIG_DIR / f"{name}.png"
    if not EDGE.exists():
        print(f"未找到 Edge，跳过栅格化：{name}")
        return None
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    cmd = [str(EDGE), "--headless=new", "--disable-gpu", "--no-first-run", "--no-sandbox",
           f"--user-data-dir={TMP / 'edgeprof'}", "--hide-scrollbars",
           f"--window-size={size[0]},{size[1]}", "--force-device-scale-factor=2",
           "--virtual-time-budget=3000", f"--screenshot={png}", html_path.as_uri()]
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=120,
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if not png.exists():
        print(f"截图失败：{name} {out.stderr[-300:]}")
        return None
    return png


def write_table(path: Path, header: list[str], rows: list[dict], keys: list[str]) -> dict:
    lines = [",".join(header)]
    for r in rows:
        cells = []
        for k in keys:
            v = r[k]
            cells.append(f"{v:.4f}" if isinstance(v, float) else str(v))
        lines.append(",".join(cells))
    path.write_bytes(("\n".join(lines) + "\n").encode("utf-8-sig"))
    return {"file": path.relative_to(ROOT).as_posix(), "rows": len(rows)}


def main() -> int:
    papers = load_papers()
    assign = load_assignments()
    names = load_names()
    ledger = load_ledger()

    abs_rows = abstract_stats(papers)
    stab_rows = stability(papers, assign, names)
    score_rows, meta = score_distribution(ledger, assign, names)

    TABLE_DIR.mkdir(parents=True, exist_ok=True)
    written = []
    written.append(write_table(TABLE_DIR / "abstract_length.csv",
                               ["会议", "年份", "样本数", "摘要词数均值", "摘要词数中位数",
                                "摘要词数下四分位", "摘要词数上四分位", "摘要词数P95"],
                               abs_rows, ["venue", "year", "n", "mean", "median", "q1", "q3", "p95"]))
    written.append(write_table(TABLE_DIR / "topic_change_stability.csv",
                               ["排名_全部", "排名_去低相似", "主题编号", "主题", "2024篇数", "2025篇数",
                                "占比变化_全部", "2024篇数_去低相似", "2025篇数_去低相似", "占比变化_去低相似"],
                               sorted(stab_rows, key=lambda r: r["rank_full"]),
                               ["rank_full", "rank_no_outlier", "topic_id", "topic", "n_2024_full", "n_2025_full",
                                "change_full", "n_2024_no_outlier", "n_2025_no_outlier", "change_no_outlier"]))
    written.append(write_table(TABLE_DIR / "topic_score_distribution.csv",
                               ["主题编号", "主题", "论文数", "占比", "均分", "标准差", "P10", "Q1", "中位数", "Q3", "P90"],
                               score_rows,
                               ["topic_id", "topic", "n", "share_percent", "mean", "sd", "p10", "q1", "median", "q3", "p90"]))

    figs = []
    p2 = render(fig_abstract(abs_rows), "fig2_abstract_length_distribution", (900, 420))
    if p2:
        figs.append({"file": p2.relative_to(ROOT).as_posix(), "bytes": p2.stat().st_size})
    p5 = render(fig_scores(meta["focus"], score_rows, meta), "fig5_score_distribution_iclr2025", (1120, 470))
    if p5:
        figs.append({"file": p5.relative_to(ROOT).as_posix(), "bytes": p5.stat().st_size})

    top3 = [r for r in stab_rows if r["rank_full"] <= 3]
    result = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "abstract_length": {
            "method": "英文词数 = 摘要按空白切分后的 token 数（len(text.split())）",
            "note": "取代交付表的正则口径：ICLR2024 均值由 187.21 降至 185.21；全体中位数 177（原图 179）",
            "overall": abs_rows[-1],
            "by_venue_year": abs_rows[:-1],
        },
        "stability": {
            "filter": "去掉模型标记 outlier=True 的 1,884 篇（相似度最低的 5%），分母同步缩小",
            "n_2024_full": 8830, "n_2025_full": 12253,
            "top3": [{"topic": r["topic"], "change_full": round(r["change_full"], 4),
                      "change_no_outlier": round(r["change_no_outlier"], 4),
                      "rank_full": r["rank_full"], "rank_no_outlier": r["rank_no_outlier"]} for r in top3],
            "top3_order_unchanged": [r["topic_id"] for r in sorted(top3, key=lambda r: r["rank_full"])]
                                   == [r["topic_id"] for r in sorted(top3, key=lambda r: r["rank_no_outlier"])],
        },
        "score_distribution": {
            "venue": meta["venue"], "year": meta["year"], "papers": meta["papers"],
            "mean_rating_all": round(meta["mean_rating_all"], 4),
            "sd_rating_all": round(meta["sd_rating_all"], 4),
            "spearman_share_vs_mean": round(meta["spearman_share_vs_mean"], 4),
            "focus": [{"topic": r["topic"], "n": r["n"], "share_percent": round(r["share_percent"], 2),
                       "mean": round(r["mean"], 4), "sd": round(r["sd"], 4),
                       "iqr": round(r["q3"] - r["q1"], 4)} for r in meta["focus"]],
        },
        "tables": written,
        "figures": figs,
    }
    (ROOT / "data" / "supplement" / "analysis.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"摘要：全体中位数 {abs_rows[-1]['median']:.0f}，均值 {abs_rows[-1]['mean']:.2f}（n={abs_rows[-1]['n']}）")
    print("稳健性前三：" + "；".join(
        f"{r['topic']} {r['change_full']:+.2f}→{r['change_no_outlier']:+.2f}" for r in top3))
    print(f"评分：{meta['venue']}{meta['year']} {meta['papers']} 篇，Spearman ρ={meta['spearman_share_vs_mean']:+.3f}")
    for f in figs:
        print("图：", f["file"], f["bytes"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
