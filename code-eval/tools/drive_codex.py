"""用 Codex CLI（非交互 `codex exec`）跑一次 code-eval 任务，然后交给 grade.py 判分。

- 单轮任务：`codex exec --json "<prompt>"`
- 多轮任务（spec.prompts）：第一轮 `exec`，后续 `exec resume --last`
- 不给 Codex 任何隐藏验收；判分在进程外由 grade.py 完成
"""

import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
EVAL = HERE.parent
CODEX = shutil.which("codex") or "codex"


def run_codex(args, cwd, timeout):
    started = time.time()
    try:
        p = subprocess.run(args, cwd=str(cwd), capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=timeout)
        return p, round(time.time() - started, 1), False
    except subprocess.TimeoutExpired as e:
        out = (e.stdout or "") if isinstance(e.stdout, str) else ""
        err = (e.stderr or "") if isinstance(e.stderr, str) else ""
        return subprocess.CompletedProcess(args, 124, out, err), round(time.time() - started, 1), True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", required=True)
    ap.add_argument("--workdir", required=True)
    ap.add_argument("--rep", type=int, default=1)
    ap.add_argument("--out", required=True)
    ap.add_argument("--prepare", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--timebox", type=int, default=900)
    ap.add_argument("--tool", default="Codex CLI 0.163.0 / deepseek-flash")
    ap.add_argument("--idle", type=int, default=30)
    ap.add_argument("--max-rounds", type=int, default=1)
    a = ap.parse_args()

    workdir = Path(a.workdir).resolve()
    spec = json.loads((EVAL / "tasks" / f"{a.task}.json").read_text(encoding="utf-8"))
    prompt_files = spec.get("prompts") or [spec["prompt"]]
    prompts = [(EVAL / rel).read_text(encoding="utf-8").replace("{workdir}", str(workdir))
               for rel in prompt_files]

    log_path = Path(a.out).parent / (Path(a.out).stem + ".trace.jsonl")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text("", encoding="utf-8")

    if a.prepare:
        cmd = [sys.executable, str(HERE / "prepare.py"), "--task", a.task, "--workdir", str(workdir)]
        if a.force:
            cmd.append("--force")
        p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
        if p.returncode != 0:
            raise SystemExit(f"prepare failed: {p.stderr}")
        print(p.stdout.strip())

    before = workdir.parent / (workdir.name + ".before.json")
    started = time.time()
    timed_out = False
    for index, prompt in enumerate(prompts, 1):
        if index == 1:
            args = [CODEX, "exec", "--skip-git-repo-check", "-s", "workspace-write",
                    "--json", prompt]
        else:
            args = [CODEX, "exec", "resume", "--last", "--json", prompt]
        p, secs, timed_out = run_codex(args, workdir, a.timebox)
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"round": index, "seconds": secs, "rc": p.returncode,
                                 "stdout": p.stdout[-200000:], "stderr": p.stderr[-20000:]},
                                ensure_ascii=False) + "\n")
        print(f"round {index}: rc={p.returncode} {secs}s")
        if timed_out:
            break
    elapsed = round(time.time() - started, 1)

    cmd = [sys.executable, str(HERE / "grade.py"),
           "--task", a.task, "--workdir", str(workdir), "--before", str(before),
           "--out", a.out, "--rep", str(a.rep), "--tool", a.tool,
           "--duration", str(elapsed)]
    g = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    print((g.stdout or "").strip()[-2000:])
    if g.returncode != 0:
        print((g.stderr or "")[-800:], file=sys.stderr)
    return 0 if not timed_out else 2


if __name__ == "__main__":
    sys.exit(main())
