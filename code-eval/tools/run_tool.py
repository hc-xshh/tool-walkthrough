"""通用套件跑批：把任务 × 次数交给指定的 driver，失败不中断，最后打表。

  python code-eval/tools/run_tool.py --driver drive_codex.py \
      --tasks L1-split-bill,L2-todo-due --reps 3 \
      --run runs/2026-10-26-codex-code-eval --force

driver 需接受 --task/--workdir/--rep/--out/--prepare/--force/--timebox。
"""

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
EVAL = HERE.parent


def normalize_argv(argv):
    """Let `--driver-arg --skip-workspace` work: argparse treats a value that
    starts with a dash as another option, so rewrite it to the = form."""
    out = []
    i = 0
    while i < len(argv):
        if argv[i] == "--driver-arg" and i + 1 < len(argv) and argv[i + 1].startswith("-"):
            out.append(f"--driver-arg={argv[i + 1]}")
            i += 2
        else:
            out.append(argv[i])
            i += 1
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--driver", default=None, help="drive_*.py 文件名或路径")
    ap.add_argument("--tasks", default=None,
                    help="逗号分隔的任务 id；与下面的筛选条件二选一")
    ap.add_argument("--category", default=None,
                    help="按 category 选，逗号分隔（cli/data/domain/files/refactor/service/library/performance/async/web）")
    ap.add_argument("--tag", default=None,
                    help="按 tag 选，逗号分隔（如 concurrency,http）")
    ap.add_argument("--complexity", default=None,
                    help="basic / intermediate / advanced，逗号分隔")
    ap.add_argument("--min-level", type=int, default=None)
    ap.add_argument("--max-level", type=int, default=None)
    ap.add_argument("--pick", type=int, default=None,
                    help="筛选后按 level 从高到低只取前 N 个；用于只跑一个复杂任务")
    ap.add_argument("--all", action="store_true", help="显式跑全部任务（不写就是必须选）")
    ap.add_argument("--list", dest="list_tasks", action="store_true",
                    help="只列出匹配任务，不启动 driver")
    ap.add_argument("--reps", type=int, default=3)
    ap.add_argument("--run", default=None,
                    help="run 目录；--list 时可省略")
    ap.add_argument("--preflight", default=None,
                    help="preflight.json from preflight.py; blocked => do not run")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--only-missing", action="store_true")
    ap.add_argument("--timebox-extra", type=int, default=180)
    ap.add_argument("--review", action="store_true",
                    help="每次尝试后跑 review.py（Alibaba Open Code Review）")
    ap.add_argument("--driver-arg", action="append", default=[],
                    choices=["--skip-workspace"],
                    help="透传给 driver 的白名单参数（目前只有 --skip-workspace）");
    a = ap.parse_args(normalize_argv(sys.argv[1:]))

    if a.preflight:
        pf = Path(a.preflight).expanduser().resolve()
        if not pf.exists():
            print(f"WARN: preflight file not found: {pf}; continuing without quota check")
        else:
            data = json.loads(pf.read_text(encoding="utf-8-sig"))
            status = data.get("status", "unknown")
            print(f"preflight {data.get('tool')}: {status} — {data.get('reason') or ''}")
            if status == "blocked":
                print("BLOCKED: fix the account/quota/window issue before running; "
                      "a blocked run is 'not tested', not 'failed'")
                raise SystemExit(2)

    run_dir = None
    all_specs = {}
    for path in sorted((EVAL / "tasks").glob("*.json")):
        spec = json.loads(path.read_text(encoding="utf-8"))
        all_specs[spec["id"]] = spec

    def csv(value):
        return {x.strip() for x in (value or "").split(",") if x.strip()}

    if a.tasks:
        tasks = [t.strip() for t in a.tasks.split(",") if t.strip()]
        unknown = [t for t in tasks if t not in all_specs]
        if unknown:
            raise SystemExit(f"unknown task(s): {', '.join(unknown)}; use --list to see ids")
    else:
        filters = (a.category, a.tag, a.complexity, a.min_level, a.max_level)
        if not any(x is not None for x in filters) and not a.all and not a.list_tasks:
            raise SystemExit(
                "choose tasks explicitly: --tasks <id> or --category/--tag/--complexity/"
                "--min-level/--max-level, or --all. Use --list to inspect."
            )
        tasks = []
        for tid, spec in all_specs.items():
            if a.category and spec.get("category") not in csv(a.category):
                continue
            if a.tag and not (set(spec.get("tags") or []) & csv(a.tag)):
                continue
            if a.complexity and spec.get("complexity") not in csv(a.complexity):
                continue
            level = spec.get("level", 0)
            if a.min_level is not None and level < a.min_level:
                continue
            if a.max_level is not None and level > a.max_level:
                continue
            tasks.append(tid)

    if not a.tasks:
        tasks.sort(key=lambda t: (all_specs[t].get("level", 0), t))
    if a.pick is not None:
        if a.pick < 1:
            raise SystemExit("--pick must be >= 1")
        # "只跑一个复杂的" -> take the highest levels in the filtered set.
        tasks = sorted(tasks, key=lambda t: (-all_specs[t].get("level", 0), t))[:a.pick]

    if not tasks:
        raise SystemExit("no task matched the filters")

    print(f"selected {len(tasks)}/{len(all_specs)}: " + ", ".join(
        f"{t} (L{all_specs[t].get('level')}, {all_specs[t].get('category')}/"
        f"{all_specs[t].get('complexity')})" for t in tasks), flush=True)
    if a.list_tasks:
        for t in tasks:
            spec = all_specs[t]
            print(f"{t:<24} L{spec.get('level'):<2} {spec.get('category'):<12} "
                  f"{spec.get('complexity'):<12} {','.join(spec.get('tags') or [])}  {spec.get('title','')}")
        return 0

    if not a.run:
        ap.error("--run is required unless --list")
    if not a.driver:
        ap.error("--driver is required unless --list")
    run_dir = Path(a.run).resolve()
    (run_dir / "results").mkdir(parents=True, exist_ok=True)
    (run_dir / "logs").mkdir(parents=True, exist_ok=True)

    driver = Path(a.driver)
    if not driver.is_absolute():
        cand = HERE / a.driver
        driver = cand if cand.exists() else Path(a.driver)
    summary = []

    for task in tasks:
        spec = json.loads((EVAL / "tasks" / f"{task}.json").read_text(encoding="utf-8"))
        for rep in range(1, a.reps + 1):
            out = run_dir / "results" / f"{task}-r{rep}.json"
            if out.exists() and not a.force:
                print(f"skip {task} r{rep} (exists)", flush=True)
                continue
            workdir = run_dir / "work" / f"{task}-r{rep}"
            cmd = [
                sys.executable, str(driver),
                "--task", task, "--workdir", str(workdir), "--rep", str(rep),
                "--out", str(out), "--prepare", "--force",
                "--timebox", str(spec.get("timebox_s", 900)),
            ]
            if spec.get("idle_s"):
                cmd += ["--idle", str(spec["idle_s"])]
            if spec.get("max_rounds"):
                cmd += ["--max-rounds", str(spec["max_rounds"])]
            cmd += a.driver_arg
            print(f"=== {task} r{rep} start ===", flush=True)
            started = time.time()
            try:
                p = subprocess.run(cmd, capture_output=True, text=True,
                                   encoding="utf-8", errors="replace",
                                   timeout=spec.get("timebox_s", 900) + a.timebox_extra)
                stdout, stderr, rc = p.stdout, p.stderr, p.returncode
            except subprocess.TimeoutExpired as e:
                stdout = (e.stdout or "") if isinstance(e.stdout, str) else ""
                stderr = (e.stderr or "") if isinstance(e.stderr, str) else ""
                rc = 124
            print(stdout.strip()[-1500:], flush=True)
            if rc != 0:
                print(stderr.strip()[-1500:], flush=True)
            took = round(time.time() - started, 1)
            verdict = "error"
            if out.exists():
                try:
                    verdict = json.loads(out.read_text(encoding="utf-8"))["verdict"]
                except Exception:
                    pass
            summary.append((task, rep, verdict, took, rc))
            print(f"=== {task} r{rep} -> {verdict} ({took}s, rc={rc}) ===", flush=True)
            if a.review and out.exists():
                r = subprocess.run(
                    [sys.executable, str(HERE / "review.py"), "--result", str(out)],
                    capture_output=True, text=True, encoding="utf-8", errors="replace",
                )
                print((r.stdout or r.stderr).strip()[-400:], flush=True)

    print("\nsummary")
    errors = 0
    for task, rep, verdict, took, rc in summary:
        print(f"{task:<24} r{rep}  {verdict:<22} {took:>7.1f}s  rc={rc}")
        if verdict in ("error",):
            errors += 1
    (run_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2),
                                          encoding="utf-8")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
