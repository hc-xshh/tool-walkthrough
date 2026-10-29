"""用 Codex CLI（非交互 `codex exec`）跑一次 code-eval 任务，然后交给 grade.py 判分。

- 单轮任务：`codex exec --json "<prompt>"`
- 多轮任务（spec.prompts）：第一轮 `exec`，后续 `exec resume --last`
- `max_rounds`：指定轮次都跑完仍不通过时，把隐藏验收的失败摘要（只给测试名和
  最后一行断言）喂回去继续修；轮次记进 result，供 scorecard 的「轮次」列使用。
- 不给 Codex 任何隐藏验收；判分在进程外由 grade.py 完成。
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


def last_agent_message(stdout):
    """从 `codex exec --json` 的事件流里取最后一条 agent_message。"""
    text = None
    for line in (stdout or "").splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            event = json.loads(line)
        except ValueError:
            continue
        item = event.get("item") or {}
        if item.get("type") == "agent_message" and item.get("text"):
            text = item["text"]
        elif event.get("type") == "agent_message" and event.get("message"):
            text = event["message"]
    return text


def build_feedback(result):
    lines = ["上一轮没有通过验收，请继续在这个仓库里修（不要改 tests/）："]
    for failure in (result.get("accept") or {}).get("failures", [])[:8]:
        tail = [ln for ln in (failure.get("message") or "").splitlines() if ln.strip()]
        lines.append(f"- {failure.get('test')}: {tail[-1][:160] if tail else ''}")
    lines.append("改完自己跑一遍仓库现有测试，再说明改了什么。")
    return "\n".join(lines)


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
    final_path = Path(a.out).with_suffix(".final.md")

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
    deadline = started + a.timebox
    timed_out = False
    index = 0
    result = None
    final_text = None

    def grade(rounds, status):
        cmd = [sys.executable, str(HERE / "grade.py"),
               "--task", a.task, "--workdir", str(workdir), "--before", str(before),
               "--out", a.out, "--rep", str(a.rep), "--tool", a.tool,
               "--duration", str(round(time.time() - started, 1)),
               "--rounds", str(rounds), "--status", status]
        if final_text:
            final_path.write_text(final_text, encoding="utf-8")
            cmd += ["--final-message", str(final_path)]
        Path(a.out).unlink(missing_ok=True)  # 防止上一轮旧结果被当成本轮结果
        try:
            g = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                               timeout=300)
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(f"grade timed out after 300s: {exc}") from exc
        print((g.stdout or "").strip()[-2000:])
        if not Path(a.out).exists():
            raise RuntimeError(f"grade failed (rc={g.returncode}): {(g.stderr or '')[-800:]}")
        return json.loads(Path(a.out).read_text(encoding="utf-8"))

    while True:
        index += 1
        final_text = None
        if index > max(a.max_rounds, len(prompts)):
            index -= 1
            break
        if index <= len(prompts):
            prompt = prompts[index - 1]
        else:
            if result is None or result.get("verdict") == "pass" or index > a.max_rounds:
                index -= 1
                break
            prompt = build_feedback(result)

        if index == 1:
            args = [CODEX, "exec", "--skip-git-repo-check", "-s", "workspace-write",
                    "--json", prompt]
        else:
            args = [CODEX, "exec", "resume", "--last", "--json", prompt]
        remaining = int(deadline - time.time())
        if remaining <= 0:
            timed_out = True
            index -= 1
            break
        p, secs, timed_out = run_codex(args, workdir, remaining)
        msg = last_agent_message(p.stdout)
        final_text = msg if msg else None
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"round": index, "seconds": secs, "rc": p.returncode,
                                 "stdout": p.stdout[-200000:], "stderr": p.stderr[-20000:]},
                                ensure_ascii=False) + "\n")
        print(f"round {index}: rc={p.returncode} {secs}s")
        result = grade(index, "timeout" if timed_out else "ok")
        if timed_out:
            break

    if result is not None:
        result["rounds"] = index
        result["rounds_to_pass"] = index if result.get("verdict") == "pass" else None
        Path(a.out).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if not timed_out else 2


if __name__ == "__main__":
    sys.exit(main())
