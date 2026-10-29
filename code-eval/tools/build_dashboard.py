#!/usr/bin/env python3
"""Build a read-only evaluation console from tasks/ and runs/.

The console is a static site: no server-side code, no database, no write access
to the runs. The only generated file is data.js; the HTML/CSS/JS templates live
in code-eval/dashboard/ and are copied next to it.

  python3 code-eval/tools/build_dashboard.py
  python3 code-eval/tools/build_dashboard.py --runs runs --out runs/dashboard
  cd runs/dashboard && python3 -m http.server 8787
"""
from __future__ import annotations

import argparse
import json
import shutil
import statistics
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
EVAL = HERE.parent
ROOT = EVAL.parent
TEMPLATES = EVAL / "dashboard"

# Keep the page small: the result JSON is the source of truth; this is just the
# visible slice. Full stdout/stderr can be megabytes and is not needed to triage.
MAX_PATCH = 16000


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def usage_from_trace(path: Path):
    trace = path.with_name(path.stem + ".trace.jsonl")
    if not trace.exists():
        return None
    total = {"input_tokens": 0, "output_tokens": 0}
    for line in trace.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            record = json.loads(line)
        except ValueError:
            continue
        stdout = record.get("stdout") or ""
        for inner in stdout.splitlines():
            if not inner.strip().startswith("{"):
                continue
            try:
                event = json.loads(inner)
            except ValueError:
                continue
            if event.get("type") != "turn.completed":
                continue
            usage = event.get("usage") or {}
            total["input_tokens"] += int(usage.get("input_tokens") or 0)
            total["output_tokens"] += int(usage.get("output_tokens") or 0)
    if not (total["input_tokens"] or total["output_tokens"]):
        return None
    total["total_tokens"] = total["input_tokens"] + total["output_tokens"]
    return total


def compact_result(result, max_patch):
    patch = result.get("patch") or ""
    usage = result.get("usage") or {}
    visible = result.get("visible") or {}
    accept = result.get("accept") or {}
    return {
        "task": result.get("task"),
        "title": result.get("title"),
        "level": result.get("level"),
        "rep": result.get("rep", 1),
        "tool": result.get("tool"),
        "started": result.get("started"),
        "duration_s": result.get("duration_s"),
        "interventions": result.get("interventions", 0),
        "run_status": result.get("run_status"),
        "rounds": result.get("rounds", 1),
        "rounds_to_pass": result.get("rounds_to_pass"),
        "verdict": result.get("verdict"),
        "reason": result.get("reason"),
        "score": result.get("score"),
        "requirements": result.get("requirements") or [],
        "accept": {
            "passed": accept.get("passed"),
            "total": accept.get("total"),
            "rc": accept.get("rc"),
            "seconds": accept.get("seconds"),
            "failures": accept.get("failures") or [],
            "tests": accept.get("tests") or [],
        },
        "visible": {
            "rc": visible.get("rc"),
            "seconds": visible.get("seconds"),
        },
        "changes": result.get("changes") or {},
        "scope": result.get("scope") or {},
        "quality": result.get("quality") or {},
        "deliverable": result.get("deliverable") or {},
        "claims": result.get("claims") or {},
        "usage": usage or None,
        "workdir_name": Path(result.get("workdir") or "").name,
        "patch": patch[:max_patch],
        "patch_truncated": len(patch) > max_patch,
    }


def load_tasks(tasks_dir: Path):
    tasks = []
    for path in sorted(tasks_dir.glob("*.json")):
        spec = read_json(path)
        prompt = ""
        if spec.get("prompt"):
            prompt_path = EVAL / spec["prompt"]
            if prompt_path.exists():
                prompt = prompt_path.read_text(encoding="utf-8", errors="replace")
                prompt = prompt.replace("{workdir}", "（运行时自动替换）")
                prompt = prompt.replace("项目路径：", "工作目录：")
        tasks.append({
            "id": spec["id"],
            "level": spec.get("level"),
            "title": spec.get("title", spec["id"]),
            "category": spec.get("category", "uncategorized"),
            "complexity": spec.get("complexity", "unknown"),
            "tags": spec.get("tags") or [],
            "prompt": prompt,
            "requirements": [
                {"id": r.get("id"), "text": r.get("text"), "tests": r.get("tests") or []}
                for r in (spec.get("requirements") or [])
            ],
            "timebox_s": spec.get("timebox_s"),
            "allowed": spec.get("allowed") or [],
            "forbidden": spec.get("forbidden") or [],
        })
    tasks.sort(key=lambda t: (t.get("level") or 0, t["id"]))
    return tasks


def load_runs(runs_dir: Path, max_patch):
    runs = []
    for run_dir in sorted(runs_dir.iterdir()):
        results_dir = run_dir / "results"
        if not results_dir.is_dir():
            continue
        by_rep = {}
        for path in sorted(results_dir.glob("*.json")):
            try:
                result = read_json(path)
            except (OSError, ValueError):
                continue
            if not result.get("task") or not result.get("verdict"):
                continue
            result.setdefault("usage", usage_from_trace(path))
            key = (result["task"], result.get("rep", 1))
            # A rerun rewrites the same rep; keep the newest file only.
            if key not in by_rep or path.stat().st_mtime >= by_rep[key][0]:
                by_rep[key] = (path.stat().st_mtime, result)
        if not by_rep:
            continue

        results = [compact_result(r, max_patch) for _, r in by_rep.values()]
        results.sort(key=lambda r: (r.get("level") or 0, r["task"], r.get("rep") or 1))
        tools = sorted({r["tool"] for r in results if r.get("tool")})
        dates = sorted(r.get("started") or "" for r in results if r.get("started"))
        runs.append({
            "id": run_dir.name,
            "tool": tools[0] if len(tools) == 1 else (", ".join(tools) if tools else "unknown"),
            "date": dates[0][:10] if dates else run_dir.name[:10],
            "results": results,
        })
    runs.sort(key=lambda r: (r.get("date") or "", r["id"]), reverse=True)
    return runs


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--runs", default=str(ROOT / "runs"))
    ap.add_argument("--tasks", default=str(EVAL / "tasks"))
    ap.add_argument("--out", default=str(ROOT / "runs" / "dashboard"))
    ap.add_argument("--max-patch", type=int, default=MAX_PATCH)
    a = ap.parse_args()

    runs_dir = Path(a.runs).expanduser().resolve()
    tasks_dir = Path(a.tasks).expanduser().resolve()
    out = Path(a.out).expanduser().resolve()
    if not runs_dir.is_dir():
        raise SystemExit(f"runs directory not found: {runs_dir}")
    if not tasks_dir.is_dir():
        raise SystemExit(f"tasks directory not found: {tasks_dir}")
    if not TEMPLATES.is_dir():
        raise SystemExit(f"dashboard templates not found: {TEMPLATES}")

    tasks = load_tasks(tasks_dir)
    runs = load_runs(runs_dir, a.max_patch)
    payload = {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "task_count": len(tasks),
        "run_count": len(runs),
        "result_count": sum(len(r["results"]) for r in runs),
        "tasks": tasks,
        "runs": runs,
    }

    out.mkdir(parents=True, exist_ok=True)
    for name in ("index.html", "styles.css", "app.js"):
        src = TEMPLATES / name
        if not src.exists():
            raise SystemExit(f"missing template: {src}")
        shutil.copy2(src, out / name)
    (out / "data.js").write_text(
        "window.__EVAL_DATA__ = " + json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + ";\n",
        encoding="utf-8",
    )

    durations = [r["duration_s"] for run in runs for r in run["results"]
                 if isinstance(r.get("duration_s"), (int, float))]
    print(f"built {out}")
    print(f"  tasks={len(tasks)} runs={len(runs)} results={payload['result_count']}")
    if durations:
        print(f"  duration median={statistics.median(durations):.1f}s")
    print(f"  static:  cd {out} && python3 -m http.server 8787")
    print("  control: python3 code-eval/tools/serve_dashboard.py")


if __name__ == "__main__":
    main()
