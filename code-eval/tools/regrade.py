"""对已有结果重跑判分（不重新让 agent 干活）。

用途：判分口径改了、或想补 patch / 改动行数时，用现有工作目录重算一遍。
耗时和授权次数从 results/timing.json 与旧结果里带过来。

用法：python tools/regrade.py --run runs/<run>
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    a = ap.parse_args()

    run = Path(a.run).resolve()
    timing_path = run / "results" / "timing.json"
    timing = json.loads(timing_path.read_text(encoding="utf-8")) if timing_path.exists() else {}

    for path in sorted((run / "results").glob("*.json")):
        if path.name == "timing.json":
            continue
        old = json.loads(path.read_text(encoding="utf-8"))
        workdir = Path(old["workdir"])
        before = workdir.parent / (workdir.name + ".before.json")
        if not workdir.exists() or not before.exists():
            print(f"skip {path.name}: workdir/before missing")
            continue
        t = timing.get(path.stem, {})
        cmd = [
            sys.executable, str(HERE / "grade.py"),
            "--task", old["task"], "--workdir", str(workdir), "--before", str(before),
            "--out", str(path), "--rep", str(old["rep"]), "--tool", old["tool"],
            "--interventions", str(old.get("interventions", 0)),
        ]
        if t.get("duration_s") is not None:
            cmd += ["--duration", str(t["duration_s"])]
        p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
        if path.exists() and ("rounds" in old or "rounds_to_pass" in old):
            fresh = json.loads(path.read_text(encoding="utf-8"))
            fresh["rounds"] = old.get("rounds", 1)
            fresh["rounds_to_pass"] = old.get("rounds_to_pass")
            path.write_text(json.dumps(fresh, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"{path.stem:<26} rc={p.returncode} {p.stdout.strip().splitlines()[-2] if p.stdout else ''}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
