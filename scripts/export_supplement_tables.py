#!/usr/bin/env python3
"""把补充轮交付的结果表与 4 张图落到仓库，并尽可能用仓库数据复算核对。

摘要长度表不在此导出：它已按统一口径（空白分词）由 build_supplement_analysis.py 重新生成，
与交付表的正则口径不同，避免两处写同一文件。

输入：项目数据分析补充结果.xlsx（默认取 Downloads 下的交付件，可用 --xlsx 指定）
输出：
  data/supplement/tables/*.csv      8 组结果表（原样导出，数值不改写）
  reports/figures/*.png             4 张图
  data/supplement/manifest.json     源文件哈希、各表行列数与 SHA256
  data/supplement/verification.json 逐表复算结果（不一致项逐条列出）

用法：
  python scripts/export_supplement_tables.py
  python scripts/export_supplement_tables.py --verify-only
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
import shutil
import statistics
import sys
import zipfile
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_XLSX = Path.home() / "Downloads" / "项目数据分析补充结果.xlsx"
TABLE_DIR = ROOT / "data" / "supplement" / "tables"
FIG_DIR = ROOT / "reports" / "figures"

SHEETS = [
    ("数据规模", "sample_scale.csv"),
    ("字段完整性", "field_completeness.csv"),
    ("共同年份变化", "topic_change_common_years.csv"),
    ("会议主题差异", "topic_venue_difference.csv"),
    ("主题年度明细", "topic_year_detail.csv"),
    ("评分覆盖", "score_coverage.csv"),
    ("ICLR公开投稿", "iclr_public_submission_rates.csv"),
]
FIGURES = [
    ("xl/media/image.png", "fig1_venue_year_sample.png"),
    ("xl/media/image3.png", "fig3_topic_share_change_2024_2025.png"),
    ("xl/media/image4.png", "fig4_topic_venue_difference_2025.png"),
]
VENUES = ("ICLR", "ICML", "NeurIPS")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_sheet(path: Path, name: str) -> tuple[list[str], list[list]]:
    """返回表头与数据行；表头固定在第 4 行（前三行是标题、口径说明、空行）。"""
    import openpyxl

    wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    ws = wb[name]
    rows = [list(r) for r in ws.iter_rows(values_only=True)]
    wb.close()
    header = [str(c).strip() if c is not None else "" for c in rows[3]]
    body = []
    for r in rows[4:]:
        vals = ["" if c is None else c for c in r]
        if not any(str(v).strip() for v in vals):
            continue
        body.append(vals)
    return header, body


def fmt(v) -> str:
    if isinstance(v, float):
        return repr(v)
    return "" if v is None else str(v)


def write_csv(path: Path, header: list[str], body: list[list]) -> dict:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(header)
    for r in body:
        w.writerow([fmt(v) for v in r])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(buf.getvalue().encode("utf-8-sig"))
    return {"file": path.relative_to(ROOT).as_posix(), "rows": len(body), "columns": len(header),
            "sha256": sha256(path), "bytes": path.stat().st_size}


def load_papers() -> list[dict]:
    with open(ROOT / "papers.csv", encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def load_assignments() -> dict[str, int]:
    with open(ROOT / "data" / "model" / "assignments.csv", encoding="utf-8-sig", newline="") as fh:
        return {r["paper_id"]: int(r["topic_id"]) for r in csv.DictReader(fh)}


def words(s: str) -> int:
    """仓库侧口径：空白分词。交付表使用另一套正则口径，见 verification.json 的说明。"""
    return len(s.split())


def pct(values: list[int], q: float) -> float:
    vals = sorted(values)
    if not vals:
        return float("nan")
    k = (len(vals) - 1) * q
    lo = int(k)
    hi = min(lo + 1, len(vals) - 1)
    return vals[lo] + (vals[hi] - vals[lo]) * (k - lo)


def build_expected() -> dict:
    papers = load_papers()
    assign = load_assignments()
    main = [p for p in papers if p["track"] == "main" and p["decision"] == "accepted"]
    modeled = [p for p in main if p["paper_id"] in assign]

    exp: dict[str, dict] = {}
    by_vy_all = Counter((p["venue"], p["year"]) for p in papers)
    by_vy_main = Counter((p["venue"], p["year"]) for p in main)

    # 数据规模：参考录用数取 analysis/reconciliation.csv 的首选来源
    recon = list(csv.DictReader(open(ROOT / "data" / "analysis" / "reconciliation.csv", encoding="utf-8-sig", newline="")))
    official: dict[str, int] = {}
    preferred: dict[str, int] = {}
    for r in recon:
        key = r["venue"] + r["year"]
        if not str(r["official_accepted"] or "").strip():
            continue
        val = int(float(r["official_accepted"]))
        official[key] = max(official.get(key, 0), val)
        if r["preferred"] == "True":
            preferred[key] = val
    official.update(preferred)
    exp["数据规模"] = {
        (r[0], r[1]): {"规范化记录": by_vy_all[(r[0], r[1])], "主会分析样本": by_vy_main[(r[0], r[1])],
                       "参考录用数": official.get(r[0] + r[1])}
        for r in [(v, y) for v in VENUES for y in ("2024", "2025", "2026")]
    }

    # 字段完整性
    fields = {"标题": "title", "摘要": "abstract", "作者": "authors", "作者关键词": "keywords", "OpenReview标识": "openreview_id"}
    exp["字段完整性"] = {}
    for scope, sample in (("全部规范化记录", papers), ("主题分析样本", modeled)):
        for label, key in fields.items():
            missing = sum(1 for p in sample if not p[key].strip() or p[key].strip() in ("[]", '""'))
            exp["字段完整性"][(scope, label)] = {"记录数": len(sample), "缺失数": missing}

    # 摘要长度
    exp["摘要长度"] = {}
    for (v, y), group in _group(modeled, lambda p: (p["venue"], p["year"])).items():
        counts = [words(p["abstract"]) for p in group]
        exp["摘要长度"][(v, y)] = {"样本数": len(counts), "均值": statistics.fmean(counts), "中位数": statistics.median(counts),
                                  "下四分位": pct(counts, 0.25), "上四分位": pct(counts, 0.75), "P95": pct(counts, 0.95)}

    # 主题年度明细
    topic_counts = Counter((p["venue"], p["year"], int(assign[p["paper_id"]])) for p in modeled)
    exp["主题年度明细"] = {k: {"论文数": n, "主会样本数": by_vy_main[(k[0], k[1])]} for k, n in topic_counts.items()}

    # 共同年份变化（三会合并 2024 vs 2025）
    t24 = Counter(assign[p["paper_id"]] for p in modeled if p["year"] == "2024")
    t25 = Counter(assign[p["paper_id"]] for p in modeled if p["year"] == "2025")
    n24 = sum(1 for p in modeled if p["year"] == "2024")
    n25 = sum(1 for p in modeled if p["year"] == "2025")
    exp["共同年份变化"] = {t: {"论文数2024": t24.get(t, 0), "论文数2025": t25.get(t, 0), "总样本2024": n24,
                               "总样本2025": n25,
                               "占比变化百分点": (t25.get(t, 0) / n25 - t24.get(t, 0) / n24) * 100}
                           for t in set(t24) | set(t25)}

    # 会议主题差异（2025 三会）
    exp["会议主题差异"] = {}
    per_venue_2025 = {v: Counter(assign[p["paper_id"]] for p in modeled if p["year"] == "2025" and p["venue"] == v) for v in VENUES}
    totals_2025 = {v: sum(c.values()) for v, c in per_venue_2025.items()}
    for t in set().union(*[set(c) for c in per_venue_2025.values()]):
        row = {f"{v}篇数": per_venue_2025[v].get(t, 0) for v in VENUES}
        shares = {v: (per_venue_2025[v].get(t, 0) / totals_2025[v] if totals_2025[v] else 0.0) for v in VENUES}
        row["最高占比会议"] = max(shares, key=shares.get)
        exp["会议主题差异"][t] = row

    return exp


def _group(items, key):
    out = defaultdict(list)
    for x in items:
        out[key(x)].append(x)
    return out


def key_of(name: str, row: list):
    if name in ("数据规模", "字段完整性", "摘要长度"):
        return (str(row[0]).strip(), str(row[1]).strip())
    if name == "主题年度明细":
        return (str(row[0]).strip(), str(row[1]).strip(), int(float(row[2])))
    if name in ("共同年份变化", "会议主题差异"):
        return int(float(row[0]))
    return str(row[0]).strip()


def verify_table(name: str, body: list[list], expected: dict) -> dict:
    """按关键列逐格比对；返回不一致计数与样例。"""
    tol = 1e-9
    cols = _header_index(name)
    issues = []
    checked = 0
    for row in body:
        key = key_of(name, row)
        exp = expected.get(key)
        if exp is None:
            issues.append({"key": str(key), "issue": "复算表里没有这一行"})
            continue
        for col, want in exp.items():
            if col not in cols or want is None:
                continue
            idx = cols[col]
            got = row[idx]
            checked += 1
            if isinstance(want, str):
                if str(got).strip() != want:
                    issues.append({"key": str(key), "column": col, "table": got, "recomputed": want})
            else:
                try:
                    gv = float(got)
                except (TypeError, ValueError):
                    issues.append({"key": str(key), "column": col, "table": got, "recomputed": want})
                    continue
                if abs(gv - float(want)) > tol:
                    issues.append({"key": str(key), "column": col, "table": gv, "recomputed": want,
                                   "delta": gv - float(want)})
    return {"cells_checked": checked, "mismatches": len(issues), "examples": issues[:15],
            "status": "matched" if not issues else "mismatched"}


def _header_index(name: str) -> dict[str, int]:
    return {
        "数据规模": {"规范化记录": 2, "主会分析样本": 3, "参考录用数": 4},
        "字段完整性": {"记录数": 2, "缺失数": 3},
        "摘要长度": {"样本数": 2, "均值": 3, "中位数": 4, "下四分位": 5, "上四分位": 6, "P95": 7},
        "主题年度明细": {"论文数": 4, "主会样本数": 5},
        "共同年份变化": {"论文数2024": 2, "论文数2025": 3, "总样本2024": 4, "总样本2025": 5, "占比变化百分点": 8},
        "会议主题差异": {"ICLR篇数": 2, "ICML篇数": 4, "NeurIPS篇数": 6, "最高占比会议": 8},
    }.get(name, {})


def verify_score_coverage(body: list[list]) -> dict:
    summary = list(csv.DictReader(open(ROOT / "data" / "scores" / "score_counts_by_venue_year.csv",
                                       encoding="utf-8-sig", newline="")))
    idx = {r["venue"] + r["year"]: r for r in summary}
    issues = []
    for row in body:
        key = f"{row[0]}{row[1]}"
        r = idx.get(key)
        if not r:
            issues.append({"key": key, "issue": "无对应届次"})
            continue
        pairs = [("主会样本数", "model_papers", 2), ("评分表样本数合计", "scored_papers_ledger", 3),
                 ("未计入评分数", "papers_without_scores", 4)]
        for label, col, pos in pairs:
            if int(row[pos]) != int(r[col]):
                issues.append({"key": key, "column": label, "table": row[pos], "recomputed": r[col]})
        if row[6] and r["scale_min"]:
            want = f"{r['scale_min']}至{r['scale_max']}"
            if str(row[6]).strip() != want:
                issues.append({"key": key, "column": "量表", "table": row[6], "recomputed": want})
    return {"cells_checked": len(body) * 4, "mismatches": len(issues), "examples": issues[:15],
            "status": "matched" if not issues else "mismatched"}


def verify_iclr_public(body: list[list]) -> dict:
    zpath = ROOT / "iclr_topic_rates_results.zip"
    if not zpath.exists():
        return {"status": "skipped", "reason": "缺少 iclr_topic_rates_results.zip"}
    with zipfile.ZipFile(zpath) as zf:
        rows = list(csv.DictReader(io.StringIO(zf.read("results/iclr_topic_metrics_150.csv").decode("utf-8-sig"))))
    idx = {(r["year"], r["topic_id"]): r for r in rows}
    cols = {3: ("public_topic_submissions", "公开投稿数"), 5: ("current_accepted", "录用数"),
            6: ("current_rejected", "拒稿数"), 7: ("current_withdrawn", "撤稿数"),
            8: ("current_desk_rejected", "直接拒稿数"), 11: ("mean_accepted_paper_rating", "录用均分")}
    issues = []
    checked = 0
    for row in body:
        r = idx.get((str(row[0]), str(row[1])))
        if not r:
            issues.append({"key": (row[0], row[1]), "issue": "ICLR 指标表无此行"})
            continue
        for pos, (src, label) in cols.items():
            checked += 1
            if abs(float(row[pos]) - float(r[src])) > 1e-9:
                issues.append({"key": (row[0], row[1]), "column": label, "table": row[pos], "recomputed": r[src]})
    return {"cells_checked": checked, "mismatches": len(issues), "examples": issues[:10],
            "status": "matched" if not issues else "mismatched"}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--xlsx", default=str(DEFAULT_XLSX))
    ap.add_argument("--verify-only", action="store_true")
    args = ap.parse_args(argv)
    xlsx = Path(args.xlsx)
    if not xlsx.exists():
        print(f"找不到交付文件：{xlsx}", file=sys.stderr)
        return 2

    tables, filenames = [], {}
    for sheet, fname in SHEETS:
        header, body = read_sheet(xlsx, sheet)
        filenames[sheet] = (header, body)
        if not args.verify_only:
            tables.append(write_csv(TABLE_DIR / fname, header, body))
    if not args.verify_only:
        for src, dst in FIGURES:
            with zipfile.ZipFile(xlsx) as zf, zf.open(src) as fh:
                FIG_DIR.mkdir(parents=True, exist_ok=True)
                with open(FIG_DIR / dst, "wb") as out:
                    shutil.copyfileobj(fh, out)

    expected = build_expected()
    verification = {}
    for sheet, _ in SHEETS:
        _, body = filenames[sheet]
        if sheet == "评分覆盖":
            verification[sheet] = verify_score_coverage(body)
        elif sheet == "ICLR公开投稿":
            verification[sheet] = verify_iclr_public(body)
        elif sheet == "字段完整性":
            verification[sheet] = verify_table(sheet, body, expected[sheet])
        elif sheet in expected:
            verification[sheet] = verify_table(sheet, body, expected[sheet])
        else:
            verification[sheet] = {"status": "skipped"}

    result = {
        "exported_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": {"path": str(xlsx), "sha256": sha256(xlsx), "bytes": xlsx.stat().st_size},
        "tables": tables,
        "figures": [{"file": (FIG_DIR / dst).relative_to(ROOT).as_posix(), "bytes": (FIG_DIR / dst).stat().st_size,
                      "sha256": sha256(FIG_DIR / dst)} for _, dst in FIGURES] if not args.verify_only else [],
        "verification": verification,
    }
    out = ROOT / "data" / "supplement"
    out.mkdir(parents=True, exist_ok=True)
    if not args.verify_only:
        (out / "manifest.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (out / "verification.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    for sheet, v in verification.items():
        print(f"{sheet:10s} {v.get('status', ''):28s} 不一致 {v.get('mismatches', 0)}")
    blocking = sum(v.get("mismatches", 0) for v in verification.values()
                   if v.get("status") not in ("matched", "definition_difference", "skipped"))
    return 0 if blocking == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
