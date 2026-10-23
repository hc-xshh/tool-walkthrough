"""把 results/*.json 汇成记分卡（markdown）。

用法：python tools/scorecard.py --run runs/2026-10-22-code-eval [--out 记分卡.md]
"""

import argparse
import json
from pathlib import Path

LEVEL = {
    "L1-split-bill": "L1",
    "L2-todo-due": "L2",
    "L3-sales-pipeline": "L3",
    "L4-monthly-ledger": "L4",
    "L4b-ledger-ambiguous": "L4 含糊",
    "L5-notes-sync": "L5",
    "L6-notes-soft-delete": "L6",
}


def load(run_dir):
    rows = []
    for path in sorted((run_dir / "results").glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        if "task" in data:
            rows.append(data)
    return rows


def fmt(value, digits=0):
    if value is None:
        return "—"
    return f"{value:.{digits}f}"


def build(rows):
    tasks = sorted({r["task"] for r in rows}, key=lambda t: LEVEL.get(t, t))
    lines = ["# 能力记分卡", ""]
    lines.append("| 任务 | 档 | " + " | ".join(f"r{i}" for i in range(1, 4)) + " | 通过 |")
    lines.append("|---|---|---|---|---|---|")
    for task in tasks:
        reps = {r["rep"]: r for r in rows if r["task"] == task}
        cells = []
        for i in range(1, 4):
            r = reps.get(i)
            cells.append("—" if not r else ("✅" if r["verdict"] == "pass" else "❌"))
        passed = sum(1 for r in reps.values() if r["verdict"] == "pass")
        lines.append(
            f"| {task} | {LEVEL.get(task, '?')} | " + " | ".join(cells)
            + f" | {passed}/{len(reps)} |"
        )

    lines += ["", "## 明细", ""]
    lines.append("| 任务 | 次数 | 判定 | 隐藏验收 | 可见测试 | 耗时(s) | 授权 | 改动行 |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for r in sorted(rows, key=lambda x: (LEVEL.get(x["task"], ""), x["rep"])):
        acc = r.get("accept") or {}
        vis = r.get("visible") or {}
        ch = r.get("changes") or {}
        lines.append(
            f"| {r['task']} | {r['rep']} | {r['verdict']} | "
            f"{acc.get('passed', '—')}/{acc.get('total', '—')} | "
            f"{'ok' if vis.get('rc') == 0 else ('rc=' + str(vis.get('rc')))} | "
            f"{fmt(r.get('duration_s'), 1)} | {r.get('interventions', 0)} | "
            f"+{ch.get('lines_added', 0)}/−{ch.get('lines_removed', 0)} |"
        )

    lines += ["", "## 口径", "",
              "- **通过** = 隐藏验收全过 + 可见测试全过 + 没碰 `forbidden` 路径。",
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
