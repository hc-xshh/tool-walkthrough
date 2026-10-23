"""批量跑一个任务套件：每个任务 N 次，失败不中断，最后打表。

用法：
  python tools/run_suite.py --tasks L1-split-bill,L2-todo-due,L3-sales-pipeline \\
      --reps 3 --run runs/2026-10-22-code-eval [--force]
"""

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
EVAL = HERE.parent


def cdp_text():
    p = subprocess.run(
        [sys.executable, str(EVAL.parent / "harness" / "cdp.py"), "--match", "solo-lite", "text"],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
    )
    return p.stdout

def cdp_click(label):
    subprocess.run(
        [sys.executable, str(EVAL.parent / "harness" / "cdp.py"), "--match", "solo-lite",
         "clickel", label],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
    )


def reset_app():
    """上一轮如果卡在授权或还在跑，先拒掉，避免下一轮点不动。"""
    text = cdp_text()
    if "拒绝执行" in text:
        cdp_click("拒绝执行")
        time.sleep(1.5)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tasks", required=True)
    ap.add_argument("--reps", type=int, default=3)
    ap.add_argument("--run", required=True)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--only-missing", action="store_true")
    a = ap.parse_args()

    run_dir = Path(a.run).resolve()
    (run_dir / "results").mkdir(parents=True, exist_ok=True)
    tasks = [t.strip() for t in a.tasks.split(",") if t.strip()]
    summary = []

    for task in tasks:
        spec = json.loads((EVAL / "tasks" / f"{task}.json").read_text(encoding="utf-8"))
        for rep in range(1, a.reps + 1):
            out = run_dir / "results" / f"{task}-r{rep}.json"
            if out.exists() and not a.force:
                print(f"skip {task} r{rep} (exists)", flush=True)
                continue
            workdir = run_dir / "work" / f"{task}-r{rep}"
            reset_app()
            cmd = [
                sys.executable, str(HERE / "drive_trae.py"),
                "--task", task, "--workdir", str(workdir), "--rep", str(rep),
                "--out", str(out), "--prepare", "--force",
                "--timebox", str(spec.get("timebox_s", 900)),
            ]
            if spec.get("idle_s"):
                cmd += ["--idle", str(spec["idle_s"])]
            print(f"=== {task} r{rep} start ===", flush=True)
            started = time.time()
            p = subprocess.run(cmd, capture_output=True, text=True,
                               encoding="utf-8", errors="replace")
            print(p.stdout.strip()[-1500:], flush=True)
            if p.returncode != 0:
                print(p.stderr.strip()[-1500:], flush=True)
            took = round(time.time() - started, 1)
            verdict = "error"
            if out.exists():
                verdict = json.loads(out.read_text(encoding="utf-8"))["verdict"]
            summary.append((task, rep, verdict, took))
            print(f"=== {task} r{rep} -> {verdict} ({took}s) ===", flush=True)

    print("\nsummary")
    errors = 0
    for task, rep, verdict, took in summary:
        print(f"{task:<20} r{rep}  {verdict:<22} {took:>7.1f}s")
        if verdict in ("error",):
            errors += 1
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
