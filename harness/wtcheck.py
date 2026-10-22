#!/usr/bin/env python3
"""Evidence checks: page-map coverage, crawl completeness, states, findings."""
from __future__ import annotations

import json
import re
from pathlib import Path

from wtlib import read_events

def read_ui_map(run):
    """Parse ui-map.md: rows with a U-id, their covered task ids and notes."""
    path = run / "ui-map.md"
    if not path.exists():
        return None
    controls = []
    header = None
    screen = "（未命名界面）"
    text = path.read_text(encoding="utf-8", errors="replace")
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)  # ignore template examples
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("## "):
            screen = line[3:].strip()
            header = None
            continue
        if not line.startswith("|"):
            header = None if not line else header
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if header is None:
            if any(c.upper() == "ID" for c in cells):
                header = {c: i for i, c in enumerate(cells)}
            continue
        if all(set(c) <= set("-: ") for c in cells):
            continue  # separator row
        uid = cells[header.get("ID", 0)] if cells else ""
        if not re.fullmatch(r"U\d+", uid):
            continue
        cover_idx = header.get("覆盖任务")
        note_idx = header.get("备注")
        state_idx = header.get("状态")
        region_idx = header.get("区域")
        type_idx = header.get("类型")
        covers = cells[cover_idx] if cover_idx is not None and cover_idx < len(cells) else ""
        note = cells[note_idx] if note_idx is not None and note_idx < len(cells) else ""
        state = cells[state_idx] if state_idx is not None and state_idx < len(cells) else ""
        region = cells[region_idx] if region_idx is not None and region_idx < len(cells) else ""
        kind = cells[type_idx] if type_idx is not None and type_idx < len(cells) else ""
        task_ids = re.findall(r"T\d+", covers)
        controls.append({
            "id": uid, "screen": screen, "covers": task_ids,
            "note": note.strip(), "state": state, "region": region.strip(), "type": kind.strip(),
        })
    return controls




def read_nav_edges(run):
    """Rows of the '## 导航' table as {'from', 'control', 'to'} dicts."""
    path = run / "ui-map.md"
    if not path.exists():
        return []
    text = re.sub(r"<!--.*?-->", "", path.read_text(encoding="utf-8", errors="replace"), flags=re.S)
    in_nav, header = False, None
    edges = []
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("## "):
            in_nav = line[3:].strip().startswith("导航")
            header = None
            continue
        if not in_nav or not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if header is None:
            header = {c: i for i, c in enumerate(cells)}
            continue
        if all(set(c) <= set("-: ") for c in cells):
            continue
        idx = {k: header.get(k) for k in ("从", "控件", "到")}
        vals = {k: (cells[i] if i is not None and i < len(cells) else "") for k, i in idx.items()}
        if not vals["从"] and not vals["到"]:
            continue
        edges.append({"from": vals["从"], "control": vals["控件"], "to": vals["到"]})
    return edges


ENTRY_REGIONS = ("左侧栏", "导航栏", "底部栏")
MENU_TYPES = ("menu", "menubar", "下拉", "菜单")
NO_NEW_SCREEN = ("不产生新屏", "不新开屏", "同屏", "切换本屏", "留在本屏", "就地", "不测")




def crawl_issues(run, cov):
    """Reasons to believe the product was not actually crawled through.

    `coverage` alone only proves every *listed* control has a home; a lazy run
    can list five controls from one screen and pass. These checks look at the
    crawl itself: one first-visit screenshot per screen, one task per screen,
    and a nav edge for every screen after the first.
    """
    issues = []
    shots = sorted(p.name for p in (run / "screens").glob("*.png")) if (run / "screens").is_dir() else []
    edges = read_nav_edges(run)

    for name, items in cov["screens"].items():
        sid = re.match(r"\s*(S\d+)", name)
        sid = sid.group(1) if sid else None
        if not sid:
            issues.append(f"section {name!r} has no S-number (write '## S2 名称')")
            continue
        if not any(s.startswith(sid) for s in shots):
            issues.append(f"{sid} has no first-visit screenshot (screens/{sid}-*.png)")
        if not any(c["covers"] for c in items):
            issues.append(f"{name}: no task covers this screen")

    if cov["screen_count"] > 1:
        need = cov["screen_count"] - 1
        if len(edges) < need:
            issues.append(f"navigation table has {len(edges)} edge(s), need at least {need} for {cov['screen_count']} screens")

    known = set(cov["screens"])
    for e in edges:
        if e["to"] and e["to"] not in known:
            issues.append(f"nav edge points at {e['to']!r}, which has no section in ui-map.md")

    # first-level entries are the ones reachable from the entry screen only;
    # later screens re-render the same rail and would double-count it
    for c in cov["controls"]:
        if not re.match(r"S1\b", c["screen"]):
            continue
        is_entry = c["region"] in ENTRY_REGIONS or (
            c["region"] in ("顶部栏", "顶栏") and c["type"].lower() in MENU_TYPES
        )
        if not is_entry:
            continue
        if any(e["control"] == c["id"] for e in edges):
            continue
        if any(word in c["note"] for word in NO_NEW_SCREEN):
            continue
        issues.append(
            f"first-level entry {c['id']} ({c['region']} {c['type']}) has no screen behind it and no reason"
        )
    return issues




def read_state_matrix(run):
    """Rows of the '## 状态矩阵' table: {'screen','state','how','reached','note'}."""
    path = run / "ui-map.md"
    if not path.exists():
        return None
    text = re.sub(r"<!--.*?-->", "", path.read_text(encoding="utf-8", errors="replace"), flags=re.S)
    in_block, header, rows = False, None, []
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("## "):
            in_block = line[3:].strip().startswith("状态")
            header = None
            continue
        if not in_block or not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if header is None:
            header = {c: i for i, c in enumerate(cells)}
            continue
        if all(set(c) <= set("-: ") for c in cells):
            continue

        def cell(key):
            i = header.get(key)
            return cells[i] if i is not None and i < len(cells) else ""

        if not cell("屏幕"):
            continue
        rows.append({
            "screen": cell("屏幕"), "state": cell("状态"),
            "how": cell("怎么触发"), "reached": cell("本轮到没到"),
            "note": cell("覆盖任务或原因"),
        })
    return rows




def state_issues(run, cov):
    rows = read_state_matrix(run)
    if rows is None:
        return ["no state matrix — a crawl only covers screens at rest, states need their own ledger"]
    issues = []
    if not rows:
        issues.append("state matrix has no rows")
    by_screen = {}
    for r in rows:
        sid = re.match(r"\s*(S\d+)", r["screen"])
        if sid:
            by_screen.setdefault(sid.group(1), []).append(r)
    for name in cov["screens"]:
        sid = re.match(r"\s*(S\d+)", name)
        if sid and sid.group(1) not in by_screen:
            issues.append(f"{sid.group(1)} has no state rows")
    for r in rows:
        if "没到" in r["reached"] and not r["note"].strip():
            issues.append(f"state '{r['state']}' on {r['screen']} is marked 没到 without a reason")
    return issues




def ui_coverage(run):
    """(total, covered, skipped-with-reason, uncovered, dangling task refs)."""
    controls = read_ui_map(run)
    if controls is None:
        return None
    plan = run / "task-plan.md"
    known = set(re.findall(r"T\d+", plan.read_text(encoding="utf-8", errors="replace"))) if plan.exists() else set()
    covered = [c for c in controls if c["covers"]]
    skipped = [c for c in controls if not c["covers"] and c["note"]]
    uncovered = [c for c in controls if not c["covers"] and not c["note"]]
    dangling = sorted({t for c in controls for t in c["covers"] if known and t not in known})
    screens = {}
    for c in controls:
        screens.setdefault(c["screen"], []).append(c)
    return {
        "controls": controls,
        "total": len(controls),
        "covered": len(covered),
        "skipped": len(skipped),
        "uncovered": uncovered,
        "dangling": dangling,
        "tasks_known": len(known),
        "screens": screens,
        "screen_count": len(screens),
    }




def cmd_coverage(a):
    run = Path(a.run_dir).expanduser().resolve()
    cov = ui_coverage(run)
    if cov is None:
        print(f"no {run / 'ui-map.md'} — build the page map first (METHOD Step 1)")
        return 1 if getattr(a, "strict", False) else 0
    print(f"coverage {run}")
    print(f"  screens    {cov['screen_count']}")
    print(f"  controls   {cov['total']}")
    print(f"  covered    {cov['covered']}")
    print(f"  skipped    {cov['skipped']}  (has a reason in 备注)")
    print(f"  uncovered  {len(cov['uncovered'])}")
    for name, items in cov["screens"].items():
        mine = sum(1 for c in items if c["covers"])
        print(f"  - {name}: {len(items)} controls, {mine} covered")
    if cov["dangling"]:
        print(f"  unknown task ids: {', '.join(cov['dangling'])}")
    for c in cov["uncovered"]:
        print(f"  - {c['id']} has no task and no reason")

    issues = crawl_issues(run, cov) + state_issues(run, cov)
    if issues:
        print("\ncrawl looks incomplete:")
        for i in issues:
            print(f"  ! {i}")
    if getattr(a, "strict", False) and (cov["uncovered"] or cov["dangling"] or issues):
        return 1
    return 0




def count_planned_tasks(plan_path):
    """Task rows that carry a result — template examples have none."""
    if not plan_path.exists():
        return 0, 0
    header = None
    total, filled = 0, 0
    for raw in plan_path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line.startswith("|"):
            header = None if not line else header
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if header is None:
            if any(c.upper() == "ID" for c in cells):
                header = {c: i for i, c in enumerate(cells)}
            continue
        if all(set(c) <= set("-: ") for c in cells):
            continue
        idx = header.get("ID")
        if idx is None or idx >= len(cells) or not re.fullmatch(r"T\d+", cells[idx]):
            continue
        total += 1
        res_idx = header.get("结果")
        if res_idx is not None and res_idx < len(cells):
            if re.match(r"(Pass|Fail|Not tested)", cells[res_idx], re.I):
                filled += 1
    return total, filled




def finding_issue_list(text):
    """Findings must state 归因 (product/script/env) and 复现 count.

    Reports title findings either as `### 4.1 · S2 · ...` or `#### W-01 ...`,
    so count finding-like headings and compare with the two fields.
    """
    titles = re.findall(r"^#{3,4}\s+(.+)$", text, flags=re.M)
    findings = [t for t in titles if re.search(r"·\s*S[1-4]\b|^\s*W-\d+", t)]
    n = len(findings)
    if not n:
        return []
    missing = []
    got_attr = len(re.findall(r"\*\*归因\*\*", text))
    got_repro = len(re.findall(r"\*\*复现\*\*", text))
    if got_attr < n:
        missing.append(f"{n - got_attr} of {n} findings lack 归因")
    if got_repro < n:
        missing.append(f"{n - got_repro} of {n} findings lack 复现")
    return missing




def cmd_audit(a):
    run = Path(a.run_dir).expanduser().resolve()
    events = read_events(run)
    checks = []

    report = run / "report.md"
    report_ok = report.exists() and report.stat().st_size > 0
    checks.append(("report.md", "PASS" if report_ok else "FAIL", str(report)))

    text = report.read_text(encoding="utf-8", errors="replace") if report_ok else ""
    refs = re.findall(r"(?:shots|screens)/[^\s)`\"']+\.(?:png|jpg|jpeg)", text)
    missing_refs = [r for r in refs if not (run / r).exists()]
    checks.append((
        "report image refs",
        "PASS" if refs and not missing_refs else ("FAIL" if missing_refs else "WARN"),
        f"{len(refs)} refs, {len(missing_refs)} missing",
    ))

    SHOT_ACTIONS = {"shot", "cdp:shot", "shot-window"}
    CLICK_ACTIONS = {"click", "cdp:click", "cdp:clicktext", "cdp:clickel", "cdp:clickxy"}

    shot_events = [e for e in events if e.get("action") in SHOT_ACTIONS and e.get("result") != "error"]
    # clicks and other actions can carry a screenshot too (`click` captures by
    # default); those are evidence as well and must point at real files
    carried = [
        e for e in events
        if str(e.get("screenshot") or "").strip() and e.get("result") != "error"
    ]
    bad_shots = []
    for e in carried:
        p = Path(str(e["screenshot"]))
        if not p.is_absolute():
            candidates = [run / p, run.parent / p, Path.cwd() / p]
            p = next((c for c in candidates if c.exists()), p)
        if not p.exists():
            bad_shots.append(str(p))
    unattributed = sum(1 for e in shot_events if not str(e.get("screenshot") or "").strip())
    screens_dir = run / "screens"
    crawl_shots = sorted(screens_dir.glob("*.png")) if screens_dir.is_dir() else []
    if not shot_events and not carried and not crawl_shots:
        shot_status = "FAIL"
    elif bad_shots:
        shot_status = "FAIL"
    elif unattributed:
        shot_status = "WARN"
    else:
        shot_status = "PASS"
    checks.append((
        "shot files",
        shot_status,
        f"{len(shot_events)} shots, {len(carried)} screenshots, "
        f"{len(crawl_shots)} crawl screens, {len(bad_shots)} missing, {unattributed} without a path",
    ))

    errors = [e for e in events if e.get("result") == "error"]
    checks.append((
        "error events",
        "PASS" if not errors else "WARN",
        f"{len(errors)} (last: {errors[-1].get('action') if errors else '-'})",
    ))

    def evidence_ok(ev):
        raw = str(ev.get("screenshot") or "").strip()
        if not raw:
            return False
        p = Path(raw)
        if not p.is_absolute():
            p = next((c for c in (run / p, run.parent / p, Path.cwd() / p) if c.exists()), p)
        return p.exists()

    gaps = 0
    for i, e in enumerate(events):
        if e.get("action") in CLICK_ACTIONS:
            # `wt.py click` / `cdp.py --capture` now shoot at click time, so a
            # click carrying a real screenshot is already paired.
            if evidence_ok(e):
                continue
            if any(x.get("action") in SHOT_ACTIONS or evidence_ok(x) for x in events[i + 1:i + 6]):
                continue
            gaps += 1
    checks.append((
        "click -> shot",
        "PASS" if gaps == 0 else "WARN",
        f"{gaps} clicks without a later shot",
    ))

    harness = run / "harness.json"
    checks.append(("harness.json", "PASS" if harness.exists() else "WARN", str(harness)))

    plan = run / "task-plan.md"
    if plan.exists():
        total_tasks, filled = count_planned_tasks(plan)
        checks.append((
            "task count",
            "PASS" if 8 <= filled <= 15 else "WARN",
            f"{filled} tasks with a result, {total_tasks} rows (METHOD Step 3 wants 8-15)",
        ))

    cov = ui_coverage(run)
    if cov is None:
        checks.append(("ui coverage", "WARN", f"no {run.name}/ui-map.md (METHOD Step 1)"))
    elif not cov["total"]:
        checks.append(("ui coverage", "WARN", "ui-map.md has no control rows yet"))
    elif cov["uncovered"]:
        checks.append((
            "ui coverage",
            "WARN",
            f"{cov['screen_count']} screens, {cov['total']} controls, "
            f"{len(cov['uncovered'])} without a task or reason",
        ))
    else:
        issues = crawl_issues(run, cov) + state_issues(run, cov)
        checks.append((
            "ui coverage",
            "PASS" if not issues else "WARN",
            f"{cov['screen_count']} screens, {cov['total']} controls, "
            f"{cov['covered']} covered, {cov['skipped']} skipped with reason"
            + (f"; crawl: {issues[0]}" if issues else ""),
        ))

    if report_ok:
        missing_fields = finding_issue_list(text)
        checks.append((
            "finding attribution",
            "PASS" if not missing_fields else "WARN",
            "every finding states 归因/复现"
            if not missing_fields
            else f"{len(missing_fields)} missing: {missing_fields[0]}",
        ))

    print(f"audit {run}")
    print(f"{'check':<24} {'status':<6} detail")
    fails = warns = 0
    for name, status, detail in checks:
        print(f"{name:<24} {status:<6} {detail}")
        fails += status == "FAIL"
        warns += status == "WARN"

    if events:
        print("\nlast events:")
        for e in events[-5:]:
            print(f"  {e.get('ts','')} {e.get('action',''):<8} {e.get('result',''):<5} {e.get('target','')}")

    if fails or (getattr(a, "strict", False) and warns):
        return 1
    return 0


