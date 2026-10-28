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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--driver", required=True, help="drive_*.py 文件名或路径")
    ap.add_argument("--tasks", required=True)
    ap.add_argument("--reps", type=int, default=3)
    ap.add_argument("--run", required=True)
    ap.add_argument("--preflight", default=None,
                    help="preflight.json from preflight.py; blocked => do not run")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--only-missing", action="store_true")
    ap.add_argument("--timebox-extra", type=int, default=180)
    ap.add_argument("--review", action="store_true",
                    help="每次尝试后跑 review.py（Alibaba Open Code Review）");
    a = ap.parse_args()

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

    run_dir = Path(a.run).resolve()
    (run_dir / "results").mkdir(parents=True, exist_ok=True)
    (run_dir / "logs").mkdir(parents=True, exist_ok=True)
    tasks = [t.strip() for t in a.tasks.split(",") if t.strip()]
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
