"""判分：把一次尝试的改动、可见测试、隐藏验收汇成一个 result.json。

用法：
  python tools/grade.py --task L1-split-bill --workdir runs/x/work/L1-r1 \\
      --before runs/x/work/L1-r1.before.json --rep 1 --tool "TRAE CN 3.4.4" \\
      --duration 42 --out runs/x/results/L1-r1.json

判分口径（写进报告时要一致）：
- 隐藏验收全过 + 可见测试全过 + 没碰禁区 = pass
- 碰了 forbidden（默认 tests/**）= scope_violation，无论验收是否通过
- 可见测试挂了 = visible_tests_failed，说明它没做到「别改坏现有行为」
- timeout / blocked 是「没测成」，不是「能力差」；它们覆盖正常 verdict 并单独记录

额外的两个维度（2026-10 补，不改变 pass 的硬门槛）：
- requirements：隐藏验收按任务书条目分组，给出 0–1 的完成度。全过才算 pass，
  但「8 条里过了 7 条」现在能看见，而不是只剩一个 ❌。
- deliverable：把 agent 的改动提交后 clone 到干净目录，重跑可见测试与隐藏验收，
  记录「交付物能不能在干净副本上复现」。同时做交付说明对账与依赖声明检查。
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

ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
PYTEST_LINE_RE = re.compile(
    r"^(?P<test>\S+::\S+?)\s+(?P<status>PASSED|FAILED|ERROR|SKIPPED|XFAIL|XPASS)\b"
)
IMPORT_RE = re.compile(r"^\+\s*(?:from\s+([A-Za-z_][\w.]*)|import\s+([A-Za-z_][\w.]*))")
PATH_RE = re.compile(
    r"[A-Za-z0-9_./-]+\.(?:py|jsx|js|tsx|ts|json|md|toml|txt|csv|html|css|yml|yaml)"
)


def run_cmd(cmd, cwd, timeout, env=None, full=False):
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
            "stdout": p.stdout if full else p.stdout[-4000:],
            "stderr": p.stderr if full else p.stderr[-4000:],
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


DEBUG_RE = re.compile(
    r"(?:\bpdb\.set_trace\b|\bbreakpoint\(|\bimport pdb\b|\bTODO\b|\bFIXME\b|\bXXX\b)"
)
STDLIB_NAMES = getattr(sys, "stdlib_module_names", None)
STDLIB = set(STDLIB_NAMES or ()) | {"__future__"}


def quality_checks(spec, changes, patch, verdict, scope):
    """「结果能不能直接用」：多出来的文件、调试残留、允许范围外的改动。"""
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
    outside = scope.get("outside_allowed", [])
    return {
        "extra_files": extra,
        "debug_markers": markers,
        "outside_allowed": outside,
        "scoped": not outside,
        "usable": verdict == "pass" and not extra and not markers and not outside,
    }


def pytest_payload(output, seconds=0.0):
    """把 pytest -v 的输出折成和 accept_run.py 一样的 JSON。

    tests[] 是逐条结果，requirements 的完成度要靠它；没有逐条行时退回计数口径。
    """
    clean = ANSI_RE.sub("", output)
    tests = []
    for line in clean.splitlines():
        m = PYTEST_LINE_RE.match(line.strip())
        if m:
            tests.append({"test": m.group("test"), "status": m.group("status").lower()})
    if tests:
        failed_messages = {}
        for line in clean.splitlines():
            if not line.startswith("FAILED "):
                continue
            rest = line[len("FAILED "):]
            test_id, _, message = rest.partition(" - ")
            failed_messages[test_id.strip()] = message.strip()[:400]
        passed = sum(1 for t in tests if t["status"] == "passed")
        failures = [
            {
                "test": t["test"],
                "status": "fail" if t["status"] == "failed" else t["status"],
                "message": failed_messages.get(t["test"], t["test"]),
            }
            for t in tests
            if t["status"] in ("failed", "error")
        ]
        return {
            "total": len(tests),
            "passed": passed,
            "failures": failures,
            "tests": tests,
            "seconds": seconds,
        }

    passed = int(m.group(1)) if (m := re.search(r"(\d+) passed", clean)) else 0
    failed = int(m.group(1)) if (m := re.search(r"(\d+) failed", clean)) else 0
    errors = int(m.group(1)) if (m := re.search(r"(\d+) error", clean)) else 0
    skipped = int(m.group(1)) if (m := re.search(r"(\d+) skipped", clean)) else 0
    xfailed = int(m.group(1)) if (m := re.search(r"(\d+) xfailed", clean)) else 0
    xpassed = int(m.group(1)) if (m := re.search(r"(\d+) xpassed", clean)) else 0
    failures = [
        {"test": line[len("FAILED "):].strip(), "status": "fail", "message": line[:400]}
        for line in clean.splitlines()
        if line.startswith("FAILED ")
    ]
    if not failures and (errors or failed):
        failures = [{"test": "<pytest>", "status": "error",
                     "message": clean.strip().splitlines()[-1][:400] if clean.strip() else ""}]
    return {
        "total": passed + failed + errors + skipped + xfailed + xpassed,
        "passed": passed,
        "failures": failures,
        "tests": [],
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


def eval_env(workdir, spec, base=None):
    env = dict(base or os.environ)
    scratch = Path(workdir).parent / ".eval-tmp"
    scratch.mkdir(parents=True, exist_ok=True)
    env["TEMP"] = env["TMP"] = env["TMPDIR"] = str(scratch)
    if spec.get("pythonpath"):
        env["PYTHONPATH"] = str(Path(workdir) / spec["pythonpath"]) + os.pathsep + env.get("PYTHONPATH", "")
    # Global pytest plugins (anyio, randomly, ...) have broken collection on
    # clean hosts more than once; hidden acceptance must not depend on them.
    # Tasks that genuinely need a plugin can set "pytest_autoload": true.
    if (spec.get("runner") == "pytest" or _visible_uses_pytest(spec)) and not spec.get("pytest_autoload"):
        env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    return env


def _visible_uses_pytest(spec):
    cmd = (spec.get("visible") or {}).get("cmd") or []
    return "pytest" in " ".join(str(c) for c in cmd)


def run_accept(workdir, spec, py, env, timeout):
    accept_src = EVAL_ROOT / spec["accept"]
    accept_dst = Path(workdir) / "_accept"
    try:
        if accept_dst.exists():
            shutil.rmtree(accept_dst)
        shutil.copytree(accept_src, accept_dst)
        if spec.get("runner") == "node":
            cmd = spec.get("accept_cmd") or [
                "node", "--test", "--test-reporter=tap", "_accept/test_accept.test.js"
            ]
            probe = run_cmd(cmd, workdir, timeout, env=env, full=True)
            payload = tap_payload(
                (probe["stdout"] or "") + "\n" + (probe["stderr"] or ""),
                probe["seconds"],
            )
            payload["rc"] = probe["rc"]
            return payload
        if spec.get("runner") == "pytest":
            probe = run_cmd(
                [py, "-m", "pytest", "-v", "-o", "addopts=", "-o", "filterwarnings=", "_accept"],
                workdir,
                timeout,
                env=env,
                full=True,
            )
            payload = pytest_payload(
                (probe["stdout"] or "") + "\n" + (probe["stderr"] or ""),
                probe["seconds"],
            )
            payload["rc"] = probe["rc"]
            return payload
        probe = run_cmd(
            [py, str(HERE / "accept_run.py"), "_accept"], workdir, timeout, env=env, full=True
        )
        try:
            payload = json.loads(probe["stdout"].strip().splitlines()[-1])
        except (ValueError, IndexError):
            payload = {
                "total": 0,
                "passed": 0,
                "failures": [{"test": "<probe>", "status": "error",
                              "message": (probe["stderr"] or probe["stdout"])[-800:]}],
            }
        payload["seconds"] = probe["seconds"]
        payload["rc"] = probe["rc"]
        return payload
    finally:
        shutil.rmtree(accept_dst, ignore_errors=True)


def tap_payload(output, seconds):
    """Parse `node --test --test-reporter=tap` top-level test lines."""
    tests = []
    messages = {}
    last = None
    for line in output.splitlines():
        m = re.match(r"^(not ok|ok) \d+ - (.+?)(?:\s+#\s*(SKIP|TODO)\b.*)?$", line)
        if m:
            name = m.group(2).strip()
            if m.group(3):
                status = "skipped"
            else:
                status = "failed" if m.group(1) == "not ok" else "passed"
            tests.append({"test": name, "status": status})
            last = name
            continue
        if last and re.match(r"^\s+(error|stack):", line):
            messages.setdefault(last, line.strip()[:400])
    failures = [
        {"test": t["test"], "status": "fail" if t["status"] == "failed" else t["status"],
         "message": messages.get(t["test"], t["test"])}
        for t in tests
        if t["status"] in ("failed", "error")
    ]
    passed = sum(1 for t in tests if t["status"] == "passed")
    if not tests:
        tail = (output or "").strip().splitlines()[-1:] or [""]
        failures = [{"test": "<node>", "status": "error", "message": tail[0][:400]}]
    return {
        "total": len(tests),
        "passed": passed,
        "failures": failures,
        "tests": tests,
        "seconds": seconds,
    }


def score_requirements(spec, accept_payload):
    """按任务书条目给完成度。没有 requirements 的任务退回「通过条数/总条数」。"""
    reqs = spec.get("requirements") or []
    tests = accept_payload.get("tests") or []
    if not reqs:
        total = accept_payload.get("total") or 0
        passed = accept_payload.get("passed") or 0
        if total:
            return None, round(passed / total, 3)
        return None, 0.0

    detail = []
    for req in reqs:
        patterns = req.get("tests") or []
        matched = [
            t for t in tests
            if any(p in t["test"] for p in patterns)
        ]
        missing = [
            p for p in patterns
            if not any(p in t["test"] for t in tests)
        ]
        met = bool(matched) and not missing and all(
            t["status"] in ("passed", "xpass") for t in matched
        )
        detail.append({
            "id": req.get("id"),
            "text": req.get("text", ""),
            "met": met,
            "tests": [t["test"] for t in matched],
            "failed": [t["test"] for t in matched if t["status"] not in ("passed", "xpass")],
            "missing": missing,
        })
    met = sum(1 for d in detail if d["met"])
    return detail, round(met / len(detail), 3)


def _git(args, cwd, timeout=60):
    git = git_binary()
    if not git:
        return None
    return run_cmd([git, *args], cwd, timeout)


def clean_clone_check(workdir, spec, py, timeout):
    """把 agent 的改动提交后 clone，重跑可见测试与隐藏验收。

    判的是「交付物」：只存在本机未跟踪文件、绝对路径、缺失依赖时，原地判分会过，
    干净副本会失败。结果进 deliverable，不改 verdict（原地验收仍是判分依据）。
    """
    git = git_binary()
    if not git:
        return {"status": "skipped", "reason": "git not found"}

    base = Path(workdir).parent / ".deliverable"
    src = base / Path(workdir).name
    clone = base / (Path(workdir).name + "-clone")
    shutil.rmtree(src, ignore_errors=True)
    shutil.rmtree(clone, ignore_errors=True)
    base.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copytree(
            workdir, src, symlinks=True,
            ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache", "*.pyc", "*.pyo"),
        )
        add = _git(["add", "-A", "--", ".",
                    ":(exclude)**/__pycache__/**", ":(exclude)**/*.pyc"], src)
        if add is None or add["rc"] != 0:
            return {
                "status": "error",
                "reason": f"git add failed: {(add or {}).get('stderr', 'git missing')[-400:]}",
                "add_rc": None if add is None else add["rc"],
            }
        commit = _git(["-c", "user.name=code-eval", "-c", "user.email=eval@local",
                       "commit", "-qm", "agent changes"], src)
        if commit is not None and commit["rc"] != 0:
            combined = (commit.get("stdout") or "") + (commit.get("stderr") or "")
            if "nothing to commit" not in combined and "无文件要提交" not in combined:
                return {"status": "error",
                        "reason": f"git commit failed: {combined[-400:]}"}
        cl = _git(["clone", "--quiet", str(src), str(clone)], base)
        if cl is None or cl["rc"] != 0:
            return {"status": "error", "reason": (cl or {}).get("stderr", "clone failed")[-400:]}

        env = eval_env(clone, spec)
        visible = None
        if spec.get("visible"):
            cmd = [py if c == "{python}" else c for c in spec["visible"]["cmd"]]
            visible = run_cmd(cmd, clone, spec["visible"].get("timeout", 180), env=env)
        accept = run_accept(clone, spec, py, env, timeout)
        return {
            "status": "ok",
            "visible_rc": None if visible is None else visible["rc"],
            "accept_passed": accept.get("passed", 0),
            "accept_total": accept.get("total", 0),
            "failed": [f["test"] for f in accept.get("failures", [])][:10],
            "ok": (
                bool(accept.get("total"))
                and not accept.get("failures")
                and accept.get("passed", 0) == accept.get("total", 0)
                and (visible is None or visible["rc"] == 0)
            ),
            "add_rc": None if add is None else add["rc"],
        }
    except Exception as exc:  # 交付物检查失败不能拖垮判分
        return {"status": "error", "reason": f"{type(exc).__name__}: {exc}"[-400:]}
    finally:
        shutil.rmtree(clone, ignore_errors=True)
        shutil.rmtree(src, ignore_errors=True)


def declared_dependencies(workdir):
    names = set()
    for rel in ("requirements.txt", "requirements-dev.txt", "requirements_dev.txt"):
        path = Path(workdir) / rel
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.split("#", 1)[0].strip()
            if not line or line.startswith(("-", "git+", "http")):
                continue
            names.add(re.split(r"[<>=!~\[; ]", line, 1)[0].strip().lower())
    for rel in ("pyproject.toml", "setup.cfg", "setup.py"):
        path = Path(workdir) / rel
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for dep in re.findall(r"[\"']([A-Za-z0-9][A-Za-z0-9_.-]{1,60})(?:\[[^\]]*\])?(?:[<>=!~][^\"']*)?[\"']", text):
            names.add(dep.lower())
    return names


def undeclared_imports(workdir, patch, spec=None):
    if STDLIB_NAMES is None:
        return []
    declared = declared_dependencies(workdir)
    local = {p.stem for p in Path(workdir).glob("*.py")}
    local |= {p.name for p in Path(workdir).iterdir() if p.is_dir() and not p.name.startswith(".")}
    if spec and spec.get("pythonpath"):
        root = Path(workdir) / spec["pythonpath"]
        if root.is_dir():
            local |= {p.name for p in root.iterdir() if p.is_dir()}
            local |= {p.stem for p in root.glob("*.py")}
    found = set()
    for line in patch.splitlines():
        m = IMPORT_RE.match(line)
        if not m:
            continue
        module = (m.group(1) or m.group(2)).split(".")[0]
        if not module or module in STDLIB or module in declared or module in local:
            continue
        found.add(module)
    return sorted(found)


def claims_audit(final_text, changes):
    """交付说明对账：说了改哪些文件，和实际 diff 对不上就记下来。不参与 verdict。"""
    if not final_text:
        return None
    mentioned = {p.lstrip("./") for p in PATH_RE.findall(final_text)}
    changed = set(changes.get("added", [])) | set(changes.get("modified", [])) | set(
        changes.get("deleted", [])
    )
    not_changed = sorted(
        p for p in mentioned
        if p not in changed and not any(p.endswith(c) or c.endswith(p) for c in changed)
    )
    not_mentioned = sorted(
        c for c in changed
        if c not in mentioned and not any(m.endswith(c) or c.endswith(m) for m in mentioned)
    )
    return {
        "files_mentioned": sorted(mentioned),
        "files_changed": sorted(changed),
        "mentioned_not_changed": not_changed,
        "changed_not_mentioned": not_mentioned,
        "claims_ran_tests": bool(re.search(r"(跑过|执行过|已运行|全部通过|ran\b|pytest|unittest)", final_text, re.I)),
    }


TAMPER_NAMES = {
    "conftest.py",
    "pytest.ini",
    "tox.ini",
    "sitecustomize.py",
    "usercustomize.py",
}


def harness_tamper(changes):
    """改测试装置（而不是被测代码）单独判，别混进能力结论。

    `tests/**` 由 forbidden 拦；这里补的是能改 pytest 收集/跳过行为的文件：
    根目录 conftest.py、pytest.ini、tox.ini、sitecustomize.py、*.pth。
    """
    paths = changes.get("added", []) + changes.get("modified", []) + changes.get("deleted", [])
    return [
        p for p in paths
        if Path(p).name in TAMPER_NAMES or p.endswith(".pth")
    ]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", required=True)
    ap.add_argument("--workdir", required=True)
    ap.add_argument("--before", required=True)
    ap.add_argument("--out", default=None)
    ap.add_argument("--rep", type=int, default=1)
    ap.add_argument("--rounds", type=int, default=None, help="实际用了几轮（驱动器回填）")
    ap.add_argument("--tool", default="unknown")
    ap.add_argument("--duration", type=float, default=None)
    ap.add_argument("--interventions", type=int, default=0,
                    help="人工介入次数（补 prompt、手动点授权都算）")
    ap.add_argument("--accept-timeout", type=int, default=180)
    ap.add_argument("--status", default="ok",
                    choices=["ok", "timeout", "blocked"],
                    help="timeout/blocked = 没测成，不是能力失败")
    ap.add_argument("--final-message", default=None,
                    help="agent 的最终交付说明（用于 claims 对账）")
    ap.add_argument("--no-clone", action="store_true", help="跳过干净副本复现检查")
    ap.add_argument("--app-version", default=None, help="被测应用版本（驱动回填）")
    ap.add_argument("--app-ua", default=None, help="被测应用 UA（驱动回填）")
    ap.add_argument("--driver", default=None, help="驱动文件名（驱动回填）")
    ap.add_argument("--harness-sha", default=None, help="驱动所在仓库的 commit（驱动回填）")
    ap.add_argument("--harness-dirty", action="store_true",
                    help="驱动的仓库有未提交改动（无法只靠 commit 复现）")
    a = ap.parse_args()

    spec = json.loads((EVAL_ROOT / "tasks" / f"{a.task}.json").read_text(encoding="utf-8"))
    workdir = Path(a.workdir).resolve()

    result = {
        "schema": 2,
        "task": spec["id"],
        "title": spec.get("title"),
        "level": spec.get("level"),
        "rep": a.rep,
        "tool": a.tool,
        "started": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "workdir": str(workdir),
        "duration_s": a.duration,
        "interventions": a.interventions,
        "run_status": a.status,
        "rounds": a.rounds,
    }
    # Provenance: a verdict is only comparable when the app version and the
    # driver are known. Optional, so older drivers keep producing valid results.
    env = {
        key: value
        for key, value in (
            ("app_version", a.app_version),
            ("user_agent", a.app_ua),
            ("driver", a.driver),
            ("harness_sha", a.harness_sha),
            ("harness_dirty", True if a.harness_dirty else None),
        )
        if value
    }
    if env:
        result["env"] = env

    changes = snap.diff(a.before, workdir)
    patch = changes.pop("patch", "")
    result["changes"] = changes
    result["scope"] = scope_check(changes, spec)
    result["scope"]["harness_tamper"] = harness_tamper(changes)

    py = os.environ.get("CODE_EVAL_PYTHON") or sys.executable
    env = eval_env(workdir, spec)

    if spec.get("visible"):
        cmd = [py if c == "{python}" else c for c in spec["visible"]["cmd"]]
        result["visible"] = run_cmd(cmd, workdir, spec["visible"].get("timeout", 180), env=env)
    else:
        result["visible"] = None

    accept_payload = run_accept(workdir, spec, py, env, a.accept_timeout)
    result["accept"] = accept_payload
    result["requirements"], result["score"] = score_requirements(spec, accept_payload)

    result["git"] = git_evidence(workdir)
    # 快照只存哈希，改过的文件原文已不在；patch 用 git diff 重建。
    # 但 git diff 不含未跟踪的新文件，这部分由快照补上（否则新增的调试文件看不见）。
    git_patch = (result["git"] or {}).get("diff") or ""
    result["patch"] = git_patch + ("\n" + patch if patch.strip() else "")
    result["changes"]["lines_added"], result["changes"]["lines_removed"] = patch_line_counts(
        result["patch"]
    )

    result["deliverable"] = {"status": "skipped", "reason": "--no-clone"}
    if not a.no_clone:
        result["deliverable"] = clean_clone_check(
            workdir, spec, py, a.accept_timeout
        )

    final_text = None
    if a.final_message and Path(a.final_message).exists():
        final_text = Path(a.final_message).read_text(encoding="utf-8", errors="replace")
        result["final_message"] = str(Path(a.final_message).resolve())
    result["claims"] = claims_audit(final_text, changes)

    accept_ok = (
        accept_payload.get("total", 0) > 0
        and accept_payload.get("rc", 0) == 0
        and not accept_payload.get("failures")
        and accept_payload.get("passed", 0) == accept_payload.get("total", 0)
    )
    visible_ok = result["visible"] is None or result["visible"]["rc"] == 0
    scope = result["scope"]

    if scope["harness_tamper"]:
        verdict, reason = (
            "scope_violation",
            "改了测试装置： " + ", ".join(scope["harness_tamper"])
            + "（conftest/pytest.ini/sitecustomize 等会影响验收收集）",
        )
    elif scope["forbidden_hits"]:
        verdict, reason = "scope_violation", "改了禁区文件：" + ", ".join(scope["forbidden_hits"])
    elif not visible_ok:
        verdict, reason = "visible_tests_failed", "现有测试没跑通；产品或 agent 把已有行为改坏了"
    elif not accept_ok:
        failed = [f["test"] for f in accept_payload.get("failures", [])]
        verdict = "failed"
        if failed:
            reason = f"隐藏验收 {accept_payload.get('passed')}/{accept_payload.get('total')} 通过；失败：{', '.join(failed)}"
        else:
            reason = (
                f"隐藏验收 {accept_payload.get('passed')}/{accept_payload.get('total')} 通过；"
                "没有失败明细（skip/xfail 或测试未被收集都算未通过）"
            )
    else:
        verdict, reason = "pass", "隐藏验收全过，可见测试全过，改动在允许范围内"

    if a.status == "timeout":
        verdict, reason = "timeout", f"超过时限，按未完成记；{reason}"
    elif a.status == "blocked":
        verdict, reason = "blocked", f"账号/额度/窗口不可用，本轮没测成；{reason}"

    result["verdict"] = verdict
    result["reason"] = reason
    result["quality"] = quality_checks(
        spec, changes, result["patch"], verdict, result["scope"]
    )
    result["quality"]["undeclared_imports"] = undeclared_imports(
        workdir, result["patch"], spec
    )
    result["quality"]["usable"] = (
        verdict == "pass"
        and not result["quality"]["extra_files"]
        and not result["quality"]["debug_markers"]
        and not result["quality"]["outside_allowed"]
        and not result["quality"]["undeclared_imports"]
    )

    out = Path(a.out) if a.out else workdir.parent / "results" / f"{spec['id']}-r{a.rep}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: result[k] for k in
                      ("task", "rep", "tool", "verdict", "reason", "score", "duration_s")},
                     ensure_ascii=False))
    print(f"result -> {out}")
    return 0 if verdict == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
