"""判分：把一次尝试的改动、可见测试、隐藏验收汇成一个 result.json。

用法：
  python tools/grade.py --task L1-split-bill --workdir runs/x/work/L1-r1 \\
      --before runs/x/work/L1-r1.before.json --rep 1 --tool "TRAE CN 3.4.4" \\
      --duration 42 --out runs/x/results/L1-r1.json

判分口径（写进报告时要一致）：
- 隐藏验收全过 + 可见测试全过 + 没碰禁区 = pass
- 碰了 forbidden（默认 tests/**）= scope_violation，无论验收是否通过
- 可见测试挂了 = visible_tests_failed，说明它没做到「别改坏现有行为」
"""

import argparse
import fnmatch
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
EVAL_ROOT = HERE.parent
sys.path.insert(0, str(HERE))

import snap  # noqa: E402

# Interpreter caches are written by every test run and are not agent edits.
# Without this, `git diff` put binary __pycache__ hunks into the evidence patch
# and `git status` made the change list look larger than it was.
GIT_EXCLUDES = [
    ":(exclude)**/__pycache__/**",
    ":(exclude)**/*.pyc",
    ":(exclude)**/*.pyo",
]


def run_cmd(cmd, cwd, timeout, env=None):
    started = time.time()
    try:
        p = subprocess.run(
            cmd,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            env=env,
        )
        return {
            "cmd": cmd,
            "rc": p.returncode,
            "seconds": round(time.time() - started, 1),
            "stdout": p.stdout[-4000:],
            "stderr": p.stderr[-4000:],
        }
    except subprocess.TimeoutExpired:
        return {
            "cmd": cmd,
            "rc": None,
            "seconds": round(time.time() - started, 1),
            "stdout": "",
            "stderr": f"timeout after {timeout}s",
        }


def git_binary():
    return snap.find_git()


def git_evidence(workdir):
    git = git_binary()
    if not git or not (Path(workdir) / ".git").exists():
        return None
    status = run_cmd([git, "status", "--porcelain", "-uall", "--", "."] + GIT_EXCLUDES, workdir, 30)
    patch = run_cmd([git, "diff", "--", "."] + GIT_EXCLUDES, workdir, 60)
    return {
        "status": status["stdout"][-4000:],
        "diff": patch["stdout"][-20000:],
    }


def patch_line_counts(patch_text):
    added = sum(
        1 for line in patch_text.splitlines()
        if line.startswith("+") and not line.startswith("+++")
    )
    removed = sum(
        1 for line in patch_text.splitlines()
        if line.startswith("-") and not line.startswith("---")
    )
    return added, removed


DEBUG_RE = re.compile(r"\b(pdb\.set_trace|breakpoint\(|import pdb|TODO|FIXME|XXX)\b")


def quality_checks(spec, changes, patch, verdict):
    """「结果能不能直接用」：多出来的文件、调试残留。"""
    allowed = spec.get("allowed", ["**"])
    extra = [
        p for p in changes.get("added", [])
        if not any(fnmatch.fnmatch(p, glob) for glob in allowed)
    ]
    markers = []
    for line in patch.splitlines():
        if line.startswith("+") and not line.startswith("+++"):
            if DEBUG_RE.search(line):
                markers.append(line[1:].strip()[:120])
    return {
        "extra_files": extra,
        "debug_markers": markers,
        "usable": verdict == "pass" and not extra and not markers,
    }


def pytest_payload(output, seconds=0.0):
    """把 pytest -q 的输出折成和 accept_run.py 一样的 JSON。"""
    clean = re.sub(r"\x1b\[[0-9;]*m", "", output)
    passed = int(m.group(1)) if (m := re.search(r"(\d+) passed", clean)) else 0
    failed = int(m.group(1)) if (m := re.search(r"(\d+) failed", clean)) else 0
    errors = int(m.group(1)) if (m := re.search(r"(\d+) error", clean)) else 0
    failures = [
        {"test": line[len("FAILED "):].strip(), "status": "fail", "message": line[:400]}
        for line in clean.splitlines()
        if line.startswith("FAILED ")
    ]
    if not failures and (errors or failed):
        failures = [{"test": "<pytest>", "status": "error",
                     "message": clean.strip().splitlines()[-1][:400] if clean.strip() else ""}]
    return {
        "total": passed + failed + errors,
        "passed": passed,
        "failures": failures,
        "seconds": seconds,
    }


def scope_check(changes, spec):
    forbidden = spec.get("forbidden", [])
    allowed = spec.get("allowed", ["**"])
    touched = changes["added"] + changes["modified"] + changes["deleted"]
    fatal = [p for p in touched if any(fnmatch.fnmatch(p, g) for g in forbidden)]
    outside = [
        p
        for p in touched
        if p not in fatal and not any(fnmatch.fnmatch(p, g) for g in allowed)
    ]
    return {
        "touched": touched,
        "forbidden_hits": fatal,
        "outside_allowed": outside,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", required=True)
    ap.add_argument("--workdir", required=True)
    ap.add_argument("--before", required=True)
    ap.add_argument("--out", default=None)
    ap.add_argument("--rep", type=int, default=1)
    ap.add_argument("--tool", default="unknown")
    ap.add_argument("--duration", type=float, default=None)
    ap.add_argument("--interventions", type=int, default=0,
                    help="人工介入次数（补 prompt、手动点授权都算）")
    ap.add_argument("--accept-timeout", type=int, default=180)
    a = ap.parse_args()

    spec = json.loads((EVAL_ROOT / "tasks" / f"{a.task}.json").read_text(encoding="utf-8"))
    workdir = Path(a.workdir).resolve()

    result = {
        "schema": 1,
        "task": spec["id"],
        "level": spec.get("level"),
        "rep": a.rep,
        "tool": a.tool,
        "started": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "workdir": str(workdir),
        "duration_s": a.duration,
        "interventions": a.interventions,
    }

    changes = snap.diff(a.before, workdir)
    patch = changes.pop("patch", "")
    result["changes"] = changes
    result["scope"] = scope_check(changes, spec)

    visible = spec.get("visible")
    py = os.environ.get("CODE_EVAL_PYTHON") or sys.executable
    env = dict(os.environ)
    # 判分子进程的临时目录放进本轮目录：宿主的 %TEMP% 在沙箱里未必可写，
    # 验收测试里的 TemporaryDirectory 会直接报 "No usable temporary directory"。
    scratch = workdir.parent / ".eval-tmp"
    scratch.mkdir(parents=True, exist_ok=True)
    env["TEMP"] = env["TMP"] = env["TMPDIR"] = str(scratch)
    if spec.get("pythonpath"):
        env["PYTHONPATH"] = str(workdir / spec["pythonpath"]) + os.pathsep + env.get("PYTHONPATH", "")
    if visible:
        cmd = [py if c == "{python}" else c for c in visible["cmd"]]
        result["visible"] = run_cmd(cmd, workdir, visible.get("timeout", 180), env=env)
    else:
        result["visible"] = None

    accept_src = EVAL_ROOT / spec["accept"]
    accept_dst = workdir / "_accept"
    accept_payload = {"total": 0, "passed": 0, "failures": [{"test": "<not run>"}]}
    try:
        if accept_dst.exists():
            shutil.rmtree(accept_dst)
        shutil.copytree(accept_src, accept_dst)
        if spec.get("runner") == "pytest":
            probe = run_cmd(
                [py, "-m", "pytest", "-q", "-o", "addopts=", "-o", "filterwarnings=", "_accept"],
                workdir,
                a.accept_timeout,
                env=env,
            )
            accept_payload = pytest_payload(
                (probe["stdout"] or "") + "\n" + (probe["stderr"] or ""), probe["seconds"]
            )
        else:
            probe = run_cmd(
                [py, str(HERE / "accept_run.py"), "_accept"],
                workdir,
                a.accept_timeout,
                env=env,
            )
            try:
                accept_payload = json.loads(probe["stdout"].strip().splitlines()[-1])
            except (ValueError, IndexError):
                accept_payload = {
                    "total": 0,
                    "passed": 0,
                    "failures": [{"test": "<probe>", "status": "error",
                                  "message": (probe["stderr"] or probe["stdout"])[-800:]}],
                }
            accept_payload["seconds"] = probe["seconds"]
    finally:
        shutil.rmtree(accept_dst, ignore_errors=True)

    result["accept"] = accept_payload
    result["git"] = git_evidence(workdir)
    # 快照只存哈希，改过的文件原文已不在；patch 用 git diff 重建。
    # 但 git diff 不含未跟踪的新文件，这部分由快照补上（否则新增的调试文件看不见）。
    git_patch = (result["git"] or {}).get("diff") or ""
    result["patch"] = git_patch + ("\n" + patch if patch.strip() else "")
    result["changes"]["lines_added"], result["changes"]["lines_removed"] = patch_line_counts(
        result["patch"]
    )

    accept_ok = accept_payload.get("total", 0) > 0 and not accept_payload.get("failures")
    visible_ok = result["visible"] is None or result["visible"]["rc"] == 0
    scope = result["scope"]

    if scope["forbidden_hits"]:
        verdict, reason = "scope_violation", "改了禁区文件：" + ", ".join(scope["forbidden_hits"])
    elif not visible_ok:
        verdict, reason = "visible_tests_failed", "现有测试没跑通；产品或 agent 把已有行为改坏了"
    elif not accept_ok:
        failed = [f["test"] for f in accept_payload.get("failures", [])]
        verdict = "failed"
        reason = f"隐藏验收 {accept_payload.get('passed')}/{accept_payload.get('total')} 通过；失败：{', '.join(failed)}"
    else:
        verdict, reason = "pass", "隐藏验收全过，可见测试全过，改动在允许范围内"

    result["verdict"] = verdict
    result["reason"] = reason
    result["quality"] = quality_checks(spec, changes, result["patch"], verdict)

    out = Path(a.out) if a.out else workdir.parent / "results" / f"{spec['id']}-r{a.rep}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: result[k] for k in
                      ("task", "rep", "tool", "verdict", "reason", "duration_s")},
                     ensure_ascii=False))
    print(f"result -> {out}")
    return 0 if verdict == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
