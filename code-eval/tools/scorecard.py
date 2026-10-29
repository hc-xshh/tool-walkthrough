"""把 results/*.json 汇成记分卡（markdown）。

用法：python tools/scorecard.py --run runs/2026-10-22-code-eval [--out 记分卡.md]

schema 2（2026-10 起）多了三样东西，旧结果缺字段时显示 —：
- 完成度 score：requirements 里满足的条数 / 总条数（全过才算 pass，但 7/8 能看见）
- 可复现 deliverable：把改动提交后 clone 到干净目录，隐藏验收是否仍然全过
- timeout / blocked：没测成，不是失败
"""

import argparse
import json
import statistics
from pathlib import Path

VERDICT_MARK = {
    "pass": "✅",
    "failed": "❌",
    "visible_tests_failed": "❌",
    "scope_violation": "⚠",
    "timeout": "⌛",
    "blocked": "⛔",
}


def load(run_dir):
    rows = []
    for path in sorted((run_dir / "results").glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        if "task" in data and "verdict" in data:
            rows.append(data)
    return rows


def fmt(value, digits=0):
    if value is None:
        return "—"
    return f"{value:.{digits}f}"


def level_of(row):
    level = row.get("level")
    return f"L{level}" if level is not None else "?"


def req_cell(row):
    reqs = row.get("requirements") or []
    if reqs:
        return f"{sum(1 for r in reqs if r.get('met'))}/{len(reqs)}"
    score = row.get("score")
    return f"{score:.0%}" if isinstance(score, (int, float)) else "—"


def build(rows):
    tasks = sorted(
        {r["task"] for r in rows},
        key=lambda t: (next((r.get("level") or 99) for r in rows if r["task"] == t), t),
    )
    max_rep = max((r["rep"] for r in rows), default=3)
    lines = ["# 能力记分卡", ""]
    lines.append("| 任务 | 档 | " + " | ".join(f"r{i}" for i in range(1, max_rep + 1))
                 + " | 通过 | 完成度 | 可复现 |")
    lines.append("|---|---|" + "---|" * max_rep + "---|---|---|")
    for task in tasks:
        reps = {r["rep"]: r for r in rows if r["task"] == task}
        cells = []
        for i in range(1, max_rep + 1):
            r = reps.get(i)
            cells.append("—" if not r else VERDICT_MARK.get(r["verdict"], "?"))
        passed = sum(1 for r in reps.values() if r["verdict"] == "pass")
        scores = [r["score"] for r in reps.values() if isinstance(r.get("score"), (int, float))]
        deliv = [r.get("deliverable") or {} for r in reps.values()]
        deliv_ok = sum(1 for d in deliv if d.get("ok"))
        deliv_tested = sum(1 for d in deliv if d.get("status") == "ok")
        score_cell = f"{statistics.mean(scores):.0%}" if scores else "—"
        deliv_cell = f"{deliv_ok}/{deliv_tested}" if deliv_tested else "—"
        first = reps[next(iter(reps))]
        lines.append(
            f"| {task} | {level_of(first)} | " + " | ".join(cells)
            + f" | {passed}/{len(reps)} | {score_cell} | {deliv_cell} |"
        )

    lines += ["", "## 明细", ""]
    lines.append("| 任务 | 次数 | 判定 | 需求 | 隐藏验收 | 可见测试 | 耗时(s) | 授权 | 轮次 | 可用 | 改动行 |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|---|")
    for r in sorted(rows, key=lambda x: (x.get("level") or 99, x["task"], x["rep"])):
        acc = r.get("accept") or {}
        vis = r.get("visible") or {}
        ch = r.get("changes") or {}
        quality = r.get("quality") or {}
        usable = "✅" if quality.get("usable") else "—"
        lines.append(
            f"| {r['task']} | {r['rep']} | {r['verdict']} | {req_cell(r)} | "
            f"{acc.get('passed', '—')}/{acc.get('total', '—')} | "
            f"{'ok' if vis.get('rc') == 0 else ('—' if not vis else 'rc=' + str(vis.get('rc')))} | "
            f"{fmt(r.get('duration_s'), 1)} | {r.get('interventions', 0)} | "
            f"{r.get('rounds') or 1} | {usable} | "
            f"+{ch.get('lines_added', 0)}/−{ch.get('lines_removed', 0)} |"
        )

    lines += ["", "## 口径", "",
              "- **通过** = 隐藏验收全过 + 可见测试全过 + 没碰 `forbidden` 路径。",
              "- **完成度** = 任务书条目满足数 / 总条数；全过才算通过，部分完成只影响这一列。",
              "- **可复现** = 改动提交后 clone 到干净目录，隐藏验收仍然全过。",
              "- **⌛ timeout / ⛔ blocked** = 没测成，不计入能力结论。",
              "- 隐藏验收不在 agent 上下文里；判分在 fixture 的干净副本上跑。",
              "- n=1 只能当个案；「3 次全过」才是可引用的说法。"]
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    rows = load(Path(a.run))
    if not rows:
        raise SystemExit("no results yet")
    text = build(rows)
    out = Path(a.out) if a.out else Path(a.run) / "scorecard.md"
    out.write_text(text, encoding="utf-8")
    print(text)
    print(f"-> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
