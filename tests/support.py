"""Helpers for the check tests: build throwaway runs and call the checks.

Run with either:

    python -m unittest discover -s tests -v
    python -m pytest tests -q
"""
from __future__ import annotations

import base64
import contextlib
import io
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "harness"))

import wtcheck  # noqa: E402

# 1x1 transparent PNG; screenshots only need to exist, never to look like much
TINY_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)

PLAN_HEADER = (
    "## 任务\n\n"
    "| ID | 用户目标 | 起始状态 | 任务脚本 | 成功标准 | 覆盖控件 | 结果 | 证据 | 备注 |\n"
    "|---|---|---|---|---|---|---|---|---|\n"
)


def plan(tasks=8, results=("Pass",)):
    """A task plan with `tasks` rows, cycling through `results`."""
    rows = []
    for i in range(1, tasks + 1):
        res = results[(i - 1) % len(results)]
        rows.append(f"| T{i} | 目标{i} | 工作台 | 脚本{i} | 标准{i} | U0{i} | {res} |  |  |")
    return "# 任务计划\n\n" + PLAN_HEADER + "\n".join(rows) + "\n"


def report(findings=1, refs=("screens/S1-工作台.png",), with_fields=True,
           with_confidence=True, with_summary=True):
    """A report with `findings` finding blocks and image refs."""
    out = ["# 报告\n"]
    if with_summary:
        out.append("## 1. 问题总览\n")
        out.append("| 严重度 | 条数 | 已复核 | 单次 | 推断 |")
        out.append("|---|---|---|---|---|")
        out.append("| S2 | 1 | 1 | 0 | 0 |\n")
    out.append("## 4. 问题清单\n")
    for i, ref in enumerate(refs[:findings] if findings else [], start=1):
        out.append(f"### 4.{i} · S2 · 第 {i} 条发现\n")
        out.append("用户看到了一段行为描述。\n")
        out.append(f"![图注]({ref})\n")
        if with_fields:
            line = "**归因**：产品 · **复现**：2 次以上"
            if with_confidence:
                line += " · **置信度**：已复核"
            out.append(line + "\n")
            out.append("**最小复现**：1. 打开工作台 → 2. 点输入框 → 3. 发送后卡住\n")
        out.append(f"**证据**：`{ref}` · **复核**：待人工复核\n")
    return "\n".join(out)


def ui_map(
    *,
    screens=(("S1", "工作台"), ("S2", "插件市场")),
    controls=None,
    states=None,
    nav=None,
    include_states=True,
    include_nav=True,
):
    """Build a ui-map.md body.

    controls: {screen_id: [(uid, region, label, type, task, note)]}
    states:   [(screen, state, how, reached, note)]; None means the default set
    nav:      [(from, control, to)]; None means the default single edge
    """
    if controls is None:
        controls = {
            "S1": [
                ("U01", "左侧栏", "插件市场", "按钮", "T1", ""),
                ("U02", "左侧栏", "项目", "按钮", "T7", "展开/收起项目分组，不产生新屏"),
            ],
            "S2": [("U03", "主区", "搜索插件", "输入框", "T2", "")],
        }
    if states is None:
        states = [
            ("S1", "默认", "打开", "到了", "T1"),
            ("S1", "空态", "清空数据", "到了", "T1"),
            ("S1", "加载中", "发一条消息", "到了", "T1"),
            ("S2", "默认", "打开", "到了", "T2"),
        ]
    if nav is None:
        nav = [("S1", "U01", "S2 插件市场")]

    parts = ["# 页面地图\n"]
    for sid, name in screens:
        parts.append(f"\n## {sid} {name}\n")
        parts.append("| ID | 区域 | 控件 | 类型 | 状态 | 覆盖任务 | 备注 |")
        parts.append("|---|---|---|---|---|---|---|")
        for row in controls.get(sid, []):
            cells = list(row)
            if len(cells) == 6:  # (uid, region, label, type, task, note)
                cells.insert(4, "可见")
            parts.append("| " + " | ".join(cells) + " |")
    if include_states:
        parts.append("\n## 状态矩阵\n")
        parts.append("| 屏幕 | 状态 | 怎么触发 | 本轮到没到 | 覆盖任务或原因 |")
        parts.append("|---|---|---|---|---|")
        for row in states:
            parts.append("| " + " | ".join(row) + " |")
    if include_nav:
        parts.append("\n## 导航\n")
        parts.append("| 从 | 控件 | 到 | 返回方式 | 备注 |")
        parts.append("|---|---|---|---|---|")
        for src, ctrl, dst in nav:
            parts.append(f"| {src} | {ctrl} | {dst} |  | |")
    return "\n".join(parts) + "\n"


def make_run(
    path,
    *,
    map_text=None,
    plan_text=None,
    report_text=None,
    screenshots=(),
    harness=True,
    events=None,
):
    """Materialise a run directory. `screenshots` are file names under screens/."""
    path = pathlib.Path(path)
    (path / "screens").mkdir(parents=True, exist_ok=True)
    (path / "shots").mkdir(parents=True, exist_ok=True)
    (path / "logs").mkdir(parents=True, exist_ok=True)
    (path / "ui-map.md").write_text(map_text if map_text is not None else ui_map(), encoding="utf-8")
    (path / "task-plan.md").write_text(plan_text if plan_text is not None else plan(), encoding="utf-8")
    (path / "report.md").write_text(report_text if report_text is not None else report(), encoding="utf-8")
    if harness:
        (path / "harness.json").write_text(
            '{"profile": "windows", "created": "2026-10-22T00:00:00+08:00"}\n', encoding="utf-8"
        )
    if events:
        (path / "events.jsonl").write_text(
            "\n".join(events) + "\n", encoding="utf-8"
        )
    for name in screenshots:
        (path / "screens" / name).write_bytes(TINY_PNG)
    return path


def coverage_issues(run):
    """Both crawl and state issues, the way `wt.py coverage` reports them."""
    cov = wtcheck.ui_coverage(pathlib.Path(run))
    assert cov is not None, "ui_coverage returned None"
    return wtcheck.crawl_issues(pathlib.Path(run), cov) + wtcheck.state_issues(pathlib.Path(run), cov)


def coverage_output(run, strict=False):
    """Run cmd_coverage, returning (exit code, stdout)."""
    import argparse

    buf = io.StringIO()
    args = argparse.Namespace(run_dir=str(run), strict=strict)
    with contextlib.redirect_stdout(buf):
        code = wtcheck.cmd_coverage(args) or 0
    return code, buf.getvalue()


def audit_output(run, strict=False):
    """Run cmd_audit, returning (exit code, stdout)."""
    import argparse

    buf = io.StringIO()
    args = argparse.Namespace(run_dir=str(run), strict=strict)
    with contextlib.redirect_stdout(buf):
        code = wtcheck.cmd_audit(args) or 0
    return code, buf.getvalue()


def check_line(output, name):
    """The status word ('PASS' / 'WARN' / 'FAIL') of a named audit check."""
    for line in output.splitlines():
        if line.startswith(name + " ") or line.startswith(name + "\t"):
            rest = line[len(name):].split()
            return rest[0] if rest else ""
    return ""
