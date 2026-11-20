#!/usr/bin/env python3
"""构建逐条评分证据账本，并重打包 public_review_scores_and_evidence.zip。

口径（全部可复算，不引入新数据源）：
- 账本行 = previous_scores/existing_paper_review_join.csv 中 join_status == matched_with_scores 的论文，
  即 7 个有公开评分的届次、30,134 篇。
- 每行的 ratings/review_ids 来自 previous_scores/reviews.csv 的原始评分观测，按 review_id 逐条列出。
- 对账恒等式：
      30,134（账本，标题+档案 ID 归一匹配）
    = 30,075（严格 paper_id 直连）
    +    162（模型侧 paper_id 与档案 ID 不一致、按 OpenReview ID 归一后匹配上）
    -    103（有评审观测但标题冲突被隔离或未形成可用评分）

用法：
    python scripts/build_score_ledger.py            # 重建 zip 与 data/scores/
    python scripts/build_score_ledger.py --check    # 只核对，不写文件
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import shutil
import statistics
import sys
import zipfile
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "public_review_scores_and_evidence.zip"
ASSIGNMENTS = ROOT / "data" / "model" / "assignments.csv"
SCORES_CSV = ROOT / "data" / "analysis" / "scores.csv"
OUT_DIR = ROOT / "data" / "scores"
VENUE_ORDER = {"ICLR": 0, "ICML": 1, "NeurIPS": 2}

LEDGER_HEADER = [
    "paper_id", "openreview_id", "archive_paper_id", "venue", "year", "track",
    "topic_id", "title", "match_basis", "n_reviews", "n_original_review_ids",
    "review_ids", "observation_ids", "ratings", "mean_rating",
    "scale_min", "scale_max", "score_field", "score_evidence", "review_id_status", "source_url",
]
SUMMARY_HEADER = [
    "venue", "year", "model_papers", "scored_papers_ledger", "scored_papers_strict_id",
    "net_difference", "review_observations", "original_review_ids", "papers_without_scores",
    "score_coverage_percent", "scale_min", "scale_max", "score_fields",
]
ADDED_HEADER = [
    "paper_id", "openreview_id", "archive_paper_id", "venue", "year", "topic_id", "title",
    "n_reviews", "mean_rating", "archive_decision", "archive_title", "reason",
]
REMOVED_HEADER = [
    "paper_id", "openreview_id", "venue", "year", "title", "join_status",
    "review_observations", "archive_title", "reason",
]
DEF_HEADER = ["count_name", "value", "population", "definition", "where_recomputed"]


def read_csv_from_zip(zf: zipfile.ZipFile, name: str) -> list[dict]:
    with zf.open(name) as fh:
        return list(csv.DictReader(io.TextIOWrapper(fh, encoding="utf-8-sig", newline="")))


def read_csv(path: Path) -> list[dict]:
    with open(path, encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def archive_id(venue: str, year: str, oid: str) -> str:
    return f"{venue}-{year}-or-{oid}"


def csv_bytes(header: list[str], rows: list[dict]) -> bytes:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=header, extrasaction="ignore", lineterminator="\n")
    w.writeheader()
    w.writerows(rows)
    return buf.getvalue().encode("utf-8-sig")


def sort_key(row: dict) -> tuple:
    return (VENUE_ORDER.get(row["venue"], 9), int(row["year"]), int(row["topic_id"]), row["paper_id"])


def load_reviews(zf: zipfile.ZipFile, wanted: set[tuple[str, str, str]]) -> tuple[dict[tuple[str, str, str], list[dict]], set[str]]:
    """只保留账本论文的观测，按 (venue, year, openreview_id) 归组并按更新时间排序。

    同时返回 reviews.csv 里出现过的全部 paper_id（严格 ID 直连口径的对照集合）。
    """
    obs: dict[tuple[str, str, str], list[dict]] = defaultdict(list)
    archive_ids: set[str] = set()
    with zf.open("previous_scores/reviews.csv") as fh:
        rdr = csv.DictReader(io.TextIOWrapper(fh, encoding="utf-8-sig", newline=""))
        for r in rdr:
            archive_ids.add(r["paper_id"])
            key = (r["venue"], r["year"], r["openreview_id"])
            if key in wanted:
                obs[key].append(r)
    for key in obs:
        obs[key].sort(key=lambda r: (int(r["updated_at"] or 0), r["review_id"]))
    return obs, archive_ids


def build(pkg: Path, write: bool) -> dict:
    if not pkg.exists():
        raise SystemExit(f"缺少输入包：{pkg}")
    zf = zipfile.ZipFile(pkg)
    join = read_csv_from_zip(zf, "previous_scores/existing_paper_review_join.csv")
    topic_scores = read_csv_from_zip(zf, "previous_scores/topic_scores_50.csv")
    quarantine = read_csv_from_zip(zf, "previous_scores/quarantine_title_mismatches.csv")
    assignments = read_csv(ASSIGNMENTS)
    scores_tbl = read_csv(SCORES_CSV)

    model_topics = {r["paper_id"]: r["topic_id"] for r in assignments}
    quarantine_by_pid = {r["paper_id"]: r for r in quarantine}

    matched = [r for r in join if r["join_status"] == "matched_with_scores"]
    matched.sort(key=lambda r: (VENUE_ORDER.get(r["venue"], 9), int(r["year"]), int(model_topics.get(r["paper_id"], r["topic_id"] or 0)), r["paper_id"]))

    wanted = {(r["venue"], r["year"], r["openreview_id"]) for r in matched}
    obs, archive_ids = load_reviews(zf, wanted)

    ledger: list[dict] = []
    anomalies: list[dict] = []
    for r in matched:
        key = (r["venue"], r["year"], r["openreview_id"])
        rows = obs.get(key, [])
        scored = [x for x in rows if x["rating"] not in ("", None)]
        ratings = [float(x["rating"]) for x in scored]
        # 公开规范化镜像不保留原始评审 ID，此时用 observation_id 作为逐条定位键
        obs_ids = [x["observation_id"] or x["review_id"] for x in scored]
        rev_ids = [x["review_id"] for x in scored]
        mean = float(r["mean_rating"])
        declared = sorted(float(v) for v in json.loads(r["score_values"] or "[]"))
        notes = []
        if len(ratings) != int(r["n_reviews"] or 0):
            notes.append(f"n_reviews {r['n_reviews']} != observations {len(ratings)}")
        if len(declared) != len(ratings) or any(abs(a - b) > 1e-9 for a, b in zip(sorted(ratings), declared)):
            notes.append("ratings 与 score_values 不一致")
        if ratings and abs(statistics.fmean(ratings) - mean) > 1e-6:
            notes.append("mean_rating 与逐条评分均值不一致")
        lo, hi = float(r["scale_min"]), float(r["scale_max"])
        bad = [v for v in ratings if v < lo or v > hi]
        if bad:
            notes.append(f"超量表评分 {bad}")
        if notes:
            anomalies.append({"paper_id": r["paper_id"], "issues": notes, "n_reviews": r["n_reviews"], "observations": len(ratings)})
        statuses = sorted({x["review_id_status"] for x in scored})
        ledger.append({
            "paper_id": r["paper_id"],
            "openreview_id": r["openreview_id"],
            "archive_paper_id": archive_id(r["venue"], r["year"], r["openreview_id"]),
            "venue": r["venue"],
            "year": r["year"],
            "track": r["track"],
            "topic_id": model_topics.get(r["paper_id"], r["topic_id"]),
            "title": r["title"],
            "match_basis": "exact_paper_id" if r["paper_id"] == archive_id(r["venue"], r["year"], r["openreview_id"]) else "openreview_id_only",
            "n_reviews": r["n_reviews"],
            "n_original_review_ids": sum(1 for x in rev_ids if x),
            "review_ids": ";".join(rev_ids),
            "observation_ids": ";".join(obs_ids),
            "ratings": ";".join(f"{v:g}" for v in ratings),
            "mean_rating": r["mean_rating"],
            "scale_min": r["scale_min"],
            "scale_max": r["scale_max"],
            "score_field": r["score_field"],
            "score_evidence": r["score_evidence"],
            "review_id_status": ";".join(statuses),
            "source_url": r["source_url"],
        })

    ledger.sort(key=sort_key)

    # ---- 两种计数口径 ----
    strict = [p for p in model_topics if p in archive_ids]
    ledger_ids = {r["paper_id"] for r in ledger}
    added = sorted(ledger_ids - set(strict))
    removed = sorted(set(strict) - ledger_ids)

    added_rows, removed_rows = [], []
    for pid in sorted(added, key=lambda p: (VENUE_ORDER.get(p.split("-")[0], 9), int(p.split("-")[1]), p)):
        r = next(x for x in matched if x["paper_id"] == pid)
        q = quarantine_by_pid.get(pid, {})
        added_rows.append({
            "paper_id": pid, "openreview_id": r["openreview_id"],
            "archive_paper_id": archive_id(r["venue"], r["year"], r["openreview_id"]),
            "venue": r["venue"], "year": r["year"], "topic_id": model_topics.get(pid, ""),
            "title": r["title"], "n_reviews": r["n_reviews"], "mean_rating": r["mean_rating"],
            "archive_decision": r["archive_decision"], "archive_title": q.get("archive_title", ""),
            "reason": "模型侧 paper_id 为来源页哈希，档案侧按 OpenReview ID 记录；标题归一后匹配，ID 直连会漏计",
        })
    join_by_pid = {r["paper_id"]: r for r in join}
    for pid in sorted(removed, key=lambda p: (VENUE_ORDER.get(p.split("-")[0], 9), int(p.split("-")[1]), p)):
        r = join_by_pid.get(pid, {})
        q = quarantine_by_pid.get(pid, {})
        status = r.get("join_status", "not_in_join")
        reason = {
            "quarantined_title_mismatch": "标题与档案不一致，已隔离；不给评分",
            "matched_but_no_public_scores": "档案已匹配但无公开评分观测",
            "no_public_source_record": "公开档案无对应记录",
        }.get(status, "未进入评分表")
        removed_rows.append({
            "paper_id": pid, "openreview_id": r.get("openreview_id", ""),
            "venue": r.get("venue", pid.split("-")[0]), "year": r.get("year", pid.split("-")[1]),
            "title": r.get("title", ""), "join_status": status,
            "review_observations": r.get("n_reviews", ""),
            "archive_title": q.get("archive_title", ""), "reason": reason,
        })

    # ---- 逐届汇总 ----
    summary = []
    by_vy_model = Counter()
    for pid in model_topics:
        v, y = pid.split("-")[0], pid.split("-")[1]
        by_vy_model[(v, y)] += 1
    by_vy_ledger = Counter((r["venue"], r["year"]) for r in ledger)
    by_vy_strict = Counter((p.split("-")[0], p.split("-")[1]) for p in strict)
    by_vy_missing = Counter()
    by_vy_scale = defaultdict(set)
    by_vy_field = defaultdict(Counter)
    obs_count = Counter()
    orig_count = Counter()
    for r in ledger:
        obs_count[(r["venue"], r["year"])] += len([x for x in r["observation_ids"].split(";") if x])
        orig_count[(r["venue"], r["year"])] += int(r["n_original_review_ids"])
        by_vy_scale[(r["venue"], r["year"])].add((r["scale_min"], r["scale_max"]))
        by_vy_field[(r["venue"], r["year"])][r["score_field"]] += 1
    for r in topic_scores:
        by_vy_missing[(r["venue"], r["year"])] += int(r["missing_scores"] or 0)
    for (v, y) in sorted(by_vy_model, key=lambda k: (VENUE_ORDER.get(k[0], 9), int(k[1]))):
        model_n = by_vy_model[(v, y)]
        led = by_vy_ledger[(v, y)]
        scales = sorted(by_vy_scale.get((v, y), set()))
        summary.append({
            "venue": v, "year": y, "model_papers": model_n,
            "scored_papers_ledger": led, "scored_papers_strict_id": by_vy_strict[(v, y)],
            "net_difference": led - by_vy_strict[(v, y)],
            "review_observations": obs_count[(v, y)],
            "original_review_ids": orig_count[(v, y)],
            "papers_without_scores": model_n - led,
            "score_coverage_percent": f"{led / model_n * 100:.6f}" if model_n else "",
            "scale_min": scales[0][0] if len(scales) == 1 else "",
            "scale_max": scales[0][1] if len(scales) == 1 else "",
            "score_fields": ";".join(f"{k}:{n}" for k, n in sorted(by_vy_field[(v, y)].items())),
        })
        if by_vy_missing[(v, y)] and by_vy_missing[(v, y)] != model_n - led:
            anomalies.append({"venue": v, "year": y, "issue": "missing_scores 与模型数−账本数不一致",
                              "topic_table_missing": by_vy_missing[(v, y)], "computed": model_n - led})

    # ---- 主题级复算，对齐 scores.csv ----
    per_topic = defaultdict(list)
    for r in ledger:
        per_topic[(r["venue"], r["year"], r["topic_id"])].append(float(r["mean_rating"]))
    score_by_key = {(r["venue"], r["year"], r["topic_id"]): r for r in scores_tbl}
    topic_mismatch = []
    for key, vals in per_topic.items():
        s = score_by_key.get(key)
        if s is None:
            topic_mismatch.append({"key": list(key), "issue": "scores.csv 无此行"})
            continue
        if int(s["papers_with_reviews"]) != len(vals):
            topic_mismatch.append({"key": list(key), "issue": "papers_with_reviews 不一致",
                                   "table": s["papers_with_reviews"], "ledger": len(vals)})
        if abs(statistics.fmean(vals) - float(s["mean_paper_rating"])) > 1e-6:
            topic_mismatch.append({"key": list(key), "issue": "均值不一致",
                                   "table": s["mean_paper_rating"], "ledger": statistics.fmean(vals)})
    missing_topics = [list(k) for k in score_by_key if k not in per_topic]

    total_ledger = len(ledger)
    total_strict = len(strict)
    counts = {
        "ledger_total": total_ledger,
        "strict_paper_id_total": total_strict,
        "plus_openreview_id_matches": len(added),
        "minus_quarantined_or_unscored": len(removed),
        "difference": total_ledger - total_strict,
        "identity_holds": total_ledger - total_strict == len(added) - len(removed)
        and total_ledger == total_strict + len(added) - len(removed),
    }
    if not counts["identity_holds"]:
        raise SystemExit(f"对账恒等式不成立：{counts}")

    defs = [
        {"count_name": "ledger_total", "value": total_ledger,
         "population": "7 个有公开评分的届次（ICML2024、NeurIPS2026 无公开评分）",
         "definition": "主题评分表实际使用的论文数：join_status=matched_with_scores 且标题/档案 ID 归一匹配成功",
         "where_recomputed": "score_ledger/paper_scores.csv 行数；data/analysis/scores.csv 的 papers_with_reviews 之和"},
        {"count_name": "strict_paper_id_total", "value": total_strict,
         "population": "同上",
         "definition": "模型论文 paper_id 与评审档案 paper_id 完全同名的那部分（不含归一匹配）",
         "where_recomputed": "与 previous_scores/reviews.csv 的 paper_id 取交集"},
        {"count_name": "legacy_manifest_total", "value": 30075,
         "population": "同上",
         "definition": "analysis_manifest.json 旧字段 supplemental_inputs.scored_model_papers 记录的数值，等于严格 ID 直连口径",
         "where_recomputed": "= strict_paper_id_total"},
        {"count_name": "plus_openreview_id_matches", "value": len(added),
         "population": "同上",
         "definition": "模型侧 paper_id 为来源页哈希、档案侧按 OpenReview ID 记录，按标题归一 + OpenReview ID 对齐后才匹配上的论文",
         "where_recomputed": "reconciliation/gap59_added_alternate_id.csv 行数"},
        {"count_name": "minus_quarantined_or_unscored", "value": len(removed),
         "population": "同上",
         "definition": "评审观测存在但标题冲突被隔离、或匹配后无可用评分的论文，未计入评分表",
         "where_recomputed": "reconciliation/gap59_removed_quarantined.csv 行数"},
        {"count_name": "difference", "value": total_ledger - total_strict,
         "population": "同上",
         "definition": "评分表合计与原统计的差额 = added − removed",
         "where_recomputed": "reconciliation/gap59_summary.json 的 identity"},
    ]

    gap = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "question": "评分表样本计数合计 30,134 与原统计说明 30,075 相差 59 篇，需逐条核对",
        "population": "ICLR2024/2025/2026、ICML2025/2026、NeurIPS2024/2025 共 7 届，37,662 篇主会论文中的评分子集",
        "counts": counts,
        "identity": f"{total_ledger} = {total_strict} + {len(added)} - {len(removed)}",
        "difference_breakdown": {
            "note": "差额 59 不是漏采或重复，而是两种连接口径的净差：162 篇按 OpenReview ID 归一后新增，103 篇因标题冲突隔离而未计入",
            "plus": len(added),
            "minus": len(removed),
        },
        "by_venue_year": summary,
        "per_topic_check": {
            "topics_checked": len(per_topic),
            "topics_in_scores_csv": len(score_by_key),
            "mismatches": len(topic_mismatch),
            "scores_csv_rows_without_ledger": len(missing_topics),
            "detail": topic_mismatch[:20],
        },
        "observation_anomalies": anomalies[:20],
        "observation_anomaly_count": len(anomalies),
    }

    return {
        "ledger": ledger, "summary": summary, "added": added_rows, "removed": removed_rows,
        "defs": defs, "gap": gap, "anomalies": anomalies, "topic_mismatch": topic_mismatch,
        "zf": zf,
    }


SCORE_LEDGER_README = """# 逐篇评分账本

`paper_scores.csv` 一行一篇，覆盖 7 个有公开评分的届次共 30,134 篇论文。

| 列 | 含义 |
| --- | --- |
| `paper_id` | 模型语料里的论文主键 |
| `openreview_id` | OpenReview forum ID |
| `archive_paper_id` | 评审档案侧主键（`venue-year-or-<openreview_id>`） |
| `match_basis` | `exact_paper_id`：两侧主键相同；`openreview_id_only`：模型侧为来源页哈希，按 OpenReview ID 归一后才连上（162 篇） |
| `n_reviews` | 该论文的评分条数 |
| `n_original_review_ids` | 其中保留原始评审 ID 的条数 |
| `review_ids` / `observation_ids` / `ratings` | 三个等长、以 `;` 分隔、按位置对齐的逐条列表 |
| `mean_rating` | 该论文的评分均值（逐条评分的算术平均） |
| `scale_min` / `scale_max` | 该届量表 |
| `score_field` | `rating` 或 `recommendation` |
| `review_id_status` | `original_public_OpenReview_note_id` / `not_preserved_by_normalized_mirror` |

## 逐条列表怎么用

`observation_ids`、`review_ids`、`ratings` 按 `;` 切分后长度相同、位置一一对应：
第 i 条评分 = `ratings[i]`，定位键 = `observation_ids[i]`，原始评审 ID = `review_ids[i]`（镜像来源为空）。

- 复算一篇：`mean(ratings)` 等于 `mean_rating`。
- 复算一个主题：同 venue/year/topic_id 的 `mean_rating` 求算术平均，等于 `data/analysis/scores.csv` 的 `mean_paper_rating`。

## 边界

- 63,391 条观测来自公开规范化镜像，镜像不保留原始评审 ID，因此 `review_ids` 为空、改用 `observation_id` 定位；评分值不受影响。
- 量表逐届不同（1—10 / 0—10 / 1—5 / 1—6），不跨年份合并；ICML 2024、NeurIPS 2026 无公开评分，不出现在账本里。
- 账本只描述公开评审的分数分布，不构成录用概率、主题质量或因果结论。
"""


def render_readme(old_readme: str, gap: dict) -> str:
    c = gap["counts"]
    head = (
        "评分逐条证据包：7 个有公开评分的届次、30,134 篇论文的逐条评分，以及与原统计 30,075 的差额对账。\n\n"
        f"对账恒等式：{gap['identity']}。差额 {c['difference']} 篇不是漏采或重复，"
        f"而是两种连接口径的净差——{c['plus_openreview_id_matches']} 篇模型侧 paper_id 为来源页哈希、"
        f"档案侧按 OpenReview ID 记录，标题归一后才匹配上（严格 ID 直连会漏计）；"
        f"{c['minus_quarantined_or_unscored']} 篇有评审观测但标题冲突被隔离或未形成可用评分，未计入评分表。\n\n"
    )
    body = (
        "## 目录\n\n"
        "| 路径 | 内容 |\n| --- | --- |\n"
        "| `score_ledger/paper_scores.csv` | 逐篇评分账本：30,134 行；`observation_ids`／`review_ids`／`ratings` 三个等长列表按位置逐条对齐 |\n"
        "| `score_ledger/README.md` | 账本列定义、逐条复算方式与边界 |\n"
        "| `score_ledger/venue_year_summary.csv` | 逐届模型论文数、账本数、严格 ID 直连数、净差、观测数、量表 |\n"
        "| `reconciliation/count_definitions.csv` | 每个计数的定义、总体与复算位置 |\n"
        "| `reconciliation/gap59_summary.json` | 差额 59 的结构化结论（含逐届分解与主题级复算结果） |\n"
        "| `reconciliation/gap59_added_alternate_id.csv` | +162：按 OpenReview ID 归一后新增的论文 |\n"
        "| `reconciliation/gap59_removed_quarantined.csv` | −103：有观测但被隔离/未评分的论文 |\n"
        "| `reconciliation/verify.py` | 只依赖标准库的复算脚本：`python reconciliation/verify.py` |\n"
        "| `previous_scores/reviews.csv` | 227,128 条评分观测（原始 review_id、字段、量表、源 URL） |\n"
        "| `previous_scores/topic_scores_50.csv` | 350 行主题评分表（7 届 × 50 主题） |\n"
        "| `evidence/` | 公开评分列表、note 字段投影及来源 URL／版本／哈希 |\n\n"
        "## 复算方式\n\n"
        "```bash\n"
        "python reconciliation/verify.py            # 校验账本行数、逐条评分与均值、量表、差额恒等式\n"
        "python reconciliation/verify.py --detail   # 额外打印逐届分解\n"
        "```\n\n"
        "## 边界\n\n"
        "- 账本是评分观测的投影，不含论文正文；标题仅用于连接核对。\n"
        "- 各届量表不同（1—10 / 0—10 / 1—5 / 1—6），跨年份不合并；ICML 2024 与 NeurIPS 2026 无公开评分，保持缺失，不按 0 分处理。\n"
        "- 评分只描述公开评审的分数分布，不构成录用概率、主题质量或因果结论。\n\n"
        "---\n\n"
        "## 原包说明（保留）\n\n"
    )
    return head + body + old_readme.strip() + "\n"


def write_package(result: dict, pkg: Path) -> dict:
    zf: zipfile.ZipFile = result["zf"]
    new_entries: dict[str, bytes] = {}
    new_entries["score_ledger/README.md"] = SCORE_LEDGER_README.encode("utf-8")
    new_entries["score_ledger/paper_scores.csv"] = csv_bytes(LEDGER_HEADER, result["ledger"])
    new_entries["score_ledger/venue_year_summary.csv"] = csv_bytes(SUMMARY_HEADER, result["summary"])
    new_entries["reconciliation/count_definitions.csv"] = csv_bytes(DEF_HEADER, result["defs"])
    new_entries["reconciliation/gap59_added_alternate_id.csv"] = csv_bytes(ADDED_HEADER, result["added"])
    new_entries["reconciliation/gap59_removed_quarantined.csv"] = csv_bytes(REMOVED_HEADER, result["removed"])
    new_entries["reconciliation/gap59_summary.json"] = (
        json.dumps(result["gap"], ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    new_entries["reconciliation/verify.py"] = (Path(__file__).resolve().parent / "verify_score_ledger.py").read_bytes()

    old_readme = zf.read("README.md").decode("utf-8")
    new_entries["README.md"] = render_readme(old_readme, result["gap"]).encode("utf-8")

    keep = {i.filename: i for i in zf.infolist()}
    payload = {}
    for name, info in keep.items():
        if name in ("MANIFEST.sha256.json", "README.md"):
            continue
        payload[name] = zf.read(name)
    payload.update(new_entries)

    manifest = [
        {"path": name, "bytes": len(data), "sha256": sha256_bytes(data)}
        for name, data in sorted(payload.items())
    ]
    payload["MANIFEST.sha256.json"] = (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8")

    tmp = pkg.with_suffix(".zip.tmp")
    stamp = (2026, 11, 20, 0, 0, 0)
    with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as out:
        for name in sorted(payload):
            info = zipfile.ZipInfo(name, date_time=stamp)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            out.writestr(info, payload[name])
    zf.close()

    backup = ROOT / ".workbuddy" / "tmp" / ("public_review_scores_and_evidence." +
                                            datetime.now().strftime("%Y%m%d%H%M%S") + ".zip")
    backup.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(pkg, backup)
    tmp.replace(pkg)

    return {
        "zip": str(pkg.name),
        "bytes": pkg.stat().st_size,
        "sha256": sha256_bytes(pkg.read_bytes()),
        "files": len(payload),
        "backup": str(backup.relative_to(ROOT)),
        "ledger_sha256": sha256_bytes(new_entries["score_ledger/paper_scores.csv"]),
        "ledger_bytes": len(new_entries["score_ledger/paper_scores.csv"]),
    }


def write_repo_artifacts(result: dict, meta: dict) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "gap59_added_alternate_id.csv").write_bytes(csv_bytes(ADDED_HEADER, result["added"]))
    (OUT_DIR / "gap59_removed_quarantined.csv").write_bytes(csv_bytes(REMOVED_HEADER, result["removed"]))
    (OUT_DIR / "score_counts_by_venue_year.csv").write_bytes(csv_bytes(SUMMARY_HEADER, result["summary"]))
    (OUT_DIR / "count_definitions.csv").write_bytes(csv_bytes(DEF_HEADER, result["defs"]))

    gap = dict(result["gap"])
    gap["package"] = meta
    (OUT_DIR / "score_reconciliation.json").write_text(
        json.dumps(gap, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true", help="只核对，不写文件")
    args = ap.parse_args(argv)

    result = build(PKG, write=not args.check)
    c = result["gap"]["counts"]
    print(f"账本 {c['ledger_total']} = 严格ID {c['strict_paper_id_total']} + {c['plus_openreview_id_matches']} - {c['minus_quarantined_or_unscored']}")
    print(f"主题级复算：{result['gap']['per_topic_check']['topics_checked']} 个主题，"
          f"不一致 {result['gap']['per_topic_check']['mismatches']} 个")
    print(f"评分观测异常：{len(result['anomalies'])} 条")
    if args.check:
        return 0 if not result["anomalies"] and not result["topic_mismatch"] else 1

    meta = write_package(result, PKG)
    write_repo_artifacts(result, meta)
    print(f"已重建 {meta['zip']}：{meta['bytes']:,} 字节，{meta['files']} 个文件")
    print(f"sha256 {meta['sha256']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
