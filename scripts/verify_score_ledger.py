#!/usr/bin/env python3
"""复算评分账本与差额对账，只依赖 Python 标准库。

两种运行方式：
1. 包内（解压后）：`python reconciliation/verify.py`
2. 仓库内：`python scripts/verify_score_ledger.py`（自动找根目录的 zip；本脚本会被复制进包里）

校验内容：
- 账本行数、每行 review_ids 与 n_reviews 一致
- 每行 ratings 的均值等于 mean_rating，且不超出该届量表
- 逐届账本数与 venue_year_summary.csv 一致
- 差额恒等式：账本 = 严格 ID 直连 + 新增 − 移除
- 给出 --repo 时，逐主题复算并与 data/analysis/scores.csv 对齐
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import statistics
import sys
import zipfile
from collections import Counter, defaultdict
from pathlib import Path

FAILS: list[str] = []
CHECKS: list[str] = []


def ok(msg: str) -> None:
    CHECKS.append(f"PASS  {msg}")


def fail(msg: str) -> None:
    FAILS.append(msg)
    CHECKS.append(f"FAIL  {msg}")


def rows_from_bytes(data: bytes) -> list[dict]:
    return list(csv.DictReader(io.StringIO(data.decode("utf-8-sig"))))


class Package:
    def __init__(self, root: Path | None, zpath: Path | None):
        self.root = root
        self.zf = zipfile.ZipFile(zpath) if zpath else None

    def read(self, name: str) -> bytes:
        if self.zf is not None:
            return self.zf.read(name)
        return (self.root / name).read_bytes()

    def has(self, name: str) -> bool:
        if self.zf is not None:
            try:
                self.zf.getinfo(name)
                return True
            except KeyError:
                return False
        return (self.root / name).exists()

    def close(self) -> None:
        if self.zf is not None:
            self.zf.close()


def verify(pkg: Package, repo: Path | None, detail: bool) -> int:
    ledger = rows_from_bytes(pkg.read("score_ledger/paper_scores.csv"))
    summary = rows_from_bytes(pkg.read("score_ledger/venue_year_summary.csv"))
    added = rows_from_bytes(pkg.read("reconciliation/gap59_added_alternate_id.csv"))
    removed = rows_from_bytes(pkg.read("reconciliation/gap59_removed_quarantined.csv"))
    gap = json.loads(pkg.read("reconciliation/gap59_summary.json").decode("utf-8"))

    ok(f"账本可读：{len(ledger):,} 行")

    # 1) 行内一致性
    bad_links = bad_mean = bad_scale = bad_alignment = 0
    per_vy = Counter()
    per_topic = defaultdict(list)
    for r in ledger:
        ids = [x for x in r["observation_ids"].split(";") if x]
        rev = r["review_ids"].split(";")
        vals = [float(x) for x in r["ratings"].split(";") if x]
        if len(ids) != int(r["n_reviews"]) or len(vals) != len(ids):
            bad_links += 1
        if len(rev) != len(ids) and rev != [""]:
            bad_alignment += 1
        if sum(1 for x in rev if x) != int(r["n_original_review_ids"]):
            bad_alignment += 1
        if vals and abs(statistics.fmean(vals) - float(r["mean_rating"])) > 1e-6:
            bad_mean += 1
        lo, hi = float(r["scale_min"]), float(r["scale_max"])
        if any(v < lo or v > hi for v in vals):
            bad_scale += 1
        per_vy[(r["venue"], r["year"])] += 1
        per_topic[(r["venue"], r["year"], r["topic_id"])].append(float(r["mean_rating"]))
    if bad_links:
        fail(f"observation_ids/n_reviews 不一致的行：{bad_links}")
    else:
        ok("每行 observation_ids 数量 = n_reviews")
    if bad_alignment:
        fail(f"review_ids 位置对齐或原始 ID 计数不一致的行：{bad_alignment}")
    else:
        ok("review_ids 与 observation_ids 位置对齐，n_original_review_ids 计数一致")
    if bad_mean:
        fail(f"逐条评分均值与 mean_rating 不一致的行：{bad_mean}")
    else:
        ok("每行逐条评分均值 = mean_rating")
    if bad_scale:
        fail(f"评分超出该届量表的行：{bad_scale}")
    else:
        ok("所有评分落在该届量表内")

    # 2) 逐届一致
    mismatch = 0
    for s in summary:
        key = (s["venue"], s["year"])
        if per_vy.get(key, 0) != int(s["scored_papers_ledger"]):
            mismatch += 1
            fail(f"{key} 账本数与汇总表不一致：{per_vy.get(key, 0)} vs {s['scored_papers_ledger']}")
    if not mismatch:
        ok(f"逐届账本数与 venue_year_summary.csv 一致（{len(summary)} 个届次）")

    # 3) 差额恒等式
    c = gap["counts"]
    total = len(ledger)
    strict = c["strict_paper_id_total"]
    if total != c["ledger_total"]:
        fail(f"账本行数 {total} != 汇总 {c['ledger_total']}")
    if total - strict != int(c["difference"]):
        fail(f"账本 − 严格 ID = {total - strict} != 记录差额 {c['difference']}")
    if len(added) != int(c["plus_openreview_id_matches"]):
        fail(f"新增清单 {len(added)} != {c['plus_openreview_id_matches']}")
    if len(removed) != int(c["minus_quarantined_or_unscored"]):
        fail(f"移除清单 {len(removed)} != {c['minus_quarantined_or_unscored']}")
    if total == strict + len(added) - len(removed):
        ok(f"差额恒等式成立：{total:,} = {strict:,} + {len(added)} − {len(removed)}（净差 {total - strict}）")
    else:
        fail(f"差额恒等式不成立：{total} != {strict} + {len(added)} - {len(removed)}")

    # 4) 明细清单与账本一致
    ledger_ids = {r["paper_id"] for r in ledger}
    if not {r["paper_id"] for r in added} <= ledger_ids:
        fail("新增清单存在账本中不存在的 paper_id")
    else:
        ok("新增清单 100% 落在账本内")
    if not (set(r["paper_id"] for r in removed) & ledger_ids):
        ok("移除清单与账本无交集")
    else:
        fail("移除清单与账本存在交集")

    # 5) 逐主题复算（需要仓库的分析表）
    if repo is not None:
        scores_csv = repo / "data" / "analysis" / "scores.csv"
        if scores_csv.exists():
            table = list(csv.DictReader(open(scores_csv, encoding="utf-8-sig", newline="")))
            keyed = {(r["venue"], r["year"], r["topic_id"]): r for r in table}
            bad = 0
            for key, vals in per_topic.items():
                s = keyed.get(key)
                if s is None or int(s["papers_with_reviews"]) != len(vals) or \
                        abs(statistics.fmean(vals) - float(s["mean_paper_rating"])) > 1e-6:
                    bad += 1
            if bad:
                fail(f"与 data/analysis/scores.csv 不一致的主题行：{bad}")
            else:
                ok(f"逐主题复算与 data/analysis/scores.csv 一致（{len(per_topic)} 行，均值与计数逐行相等）")
            extra = [k for k in keyed if k not in per_topic]
            if extra:
                fail(f"scores.csv 有 {len(extra)} 行在账本中找不到")
        else:
            print("提示：未找到 data/analysis/scores.csv，跳过逐主题复算")

    if detail:
        print("\n逐届分解：")
        print(f"{'届次':<14}{'模型论文':>9}{'账本':>8}{'严格ID':>8}{'净差':>6}{'无评分':>8}")
        for s in summary:
            print(f"{s['venue'] + ' ' + s['year']:<14}{s['model_papers']:>9}{s['scored_papers_ledger']:>8}"
                  f"{s['scored_papers_strict_id']:>8}{s['net_difference']:>6}{s['papers_without_scores']:>8}")

    print("\n".join(CHECKS))
    print(f"\n结论：{'全部通过' if not FAILS else str(len(FAILS)) + ' 项未通过'}")
    return 0 if not FAILS else 1


def main(argv: list[str] | None = None) -> int:
    here = Path(__file__).resolve()
    default_repo = here.parents[1] if here.parent.name == "scripts" else None
    ap = argparse.ArgumentParser(description="复算评分账本与差额对账")
    ap.add_argument("--repo", default=str(default_repo) if default_repo else None,
                    help="仓库根目录（含 data/analysis/scores.csv）；包内运行时可不填")
    ap.add_argument("--package", help="zip 路径；不填则按运行位置自动判断")
    ap.add_argument("--detail", action="store_true", help="打印逐届分解")
    args = ap.parse_args(argv)

    pkg_path = Path(args.package) if args.package else None
    if pkg_path is None:
        if here.parent.name == "scripts":
            pkg_path = here.parents[1] / "public_review_scores_and_evidence.zip"
        elif (here.parent.parent / "score_ledger" / "paper_scores.csv").exists():
            pkg_path = None  # 包内解压状态
        else:
            pkg_path = here.parents[1] / "public_review_scores_and_evidence.zip"

    if pkg_path is not None and not pkg_path.exists():
        print(f"找不到证据包：{pkg_path}", file=sys.stderr)
        return 2

    pkg = Package(None, pkg_path) if pkg_path else Package(here.parent.parent, None)
    try:
        return verify(pkg, Path(args.repo) if args.repo else None, args.detail)
    finally:
        pkg.close()


if __name__ == "__main__":
    sys.exit(main())
