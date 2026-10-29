#!/usr/bin/env python3
"""One-command health check for this repository.

Runs the checks a maintainer would otherwise remember by hand: unit tests,
task-spec consistency, both self-test suites, Node syntax, and Python bytecode.

Usage:
  python3 verify_all.py            # full check (~1 min)
  python3 verify_all.py --quick    # skip the two slow self-test suites
  python3 verify_all.py --strict   # a SKIP also fails (CI / release gate)
  python3 verify_all.py --json out.json
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PY = sys.executable


def run(cmd, timeout):
    started = time.time()
    try:
        p = subprocess.run(
            cmd, cwd=ROOT, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=timeout,
        )
        detail = ((p.stdout or "") + "\n" + (p.stderr or "")).strip().splitlines()
        return p.returncode, round(time.time() - started, 1), detail[-1] if detail else ""
    except subprocess.TimeoutExpired:
        return 124, round(time.time() - started, 1), f"timeout after {timeout}s"
    except OSError as exc:
        return 127, round(time.time() - started, 1), str(exc)


def check_tests():
    return run([PY, "-m", "unittest", "discover", "-s", "tests", "-q"], 180)


def check_help():
    return run([PY, "harness/wt.py", "--help"], 60)


def check_tasks():
    return run([PY, "code-eval/tools/check_tasks.py", "--strict"], 120)


def check_code_selftest():
    return run([PY, "code-eval/tools/selftest.py"], 600)


def check_office_selftest():
    return run([PY, "office-eval/tools/selftest.py"], 300)


def check_node():
    node = shutil.which("node")
    if not node:
        return None
    total = 0.0
    for rel in ("harness/webapp_accept.mjs", "code-eval/dashboard/app.js"):
        rc, seconds, detail = run([node, "--check", rel], 60)
        total += seconds
        if rc != 0:
            return rc, round(total, 1), f"{rel}: {detail}"
    return 0, round(total, 1), "webapp_accept.mjs + dashboard/app.js"


def check_compile():
    return run([PY, "-m", "compileall", "-q", "harness", "code-eval/tools", "office-eval/tools"], 120)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--quick", action="store_true", help="skip code-eval/office-eval self-tests")
    ap.add_argument("--strict", action="store_true", help="treat SKIP as failure")
    ap.add_argument("--json", default=None, help="write machine-readable results")
    a = ap.parse_args()

    checks = [
        ("unit tests", check_tests),
        ("wt.py help", check_help),
        ("task specs", check_tasks),
        ("python compile", check_compile),
        ("node syntax", check_node),
    ]
    if not a.quick:
        checks += [
            ("code-eval selftest", check_code_selftest),
            ("office-eval selftest", check_office_selftest),
        ]

    rows = []
    print(f"{'CHECK':<24} {'STATUS':<6} {'SECONDS':>7}  DETAIL")
    for name, fn in checks:
        result = fn()
        if result is None:
            rows.append({"check": name, "status": "SKIP", "seconds": 0, "detail": "node not found"})
            print(f"{name:<24} {'SKIP':<6} {0:>7.1f}  node not found")
            continue
        rc, seconds, detail = result
        if rc == 0:
            status = "PASS"
        elif name == "office-eval selftest" and "openpyxl" in detail:
            status = "SKIP"
            detail = "no interpreter with openpyxl; set OFFICE_PYTHON"
        else:
            status = "FAIL"
        rows.append({"check": name, "status": status, "seconds": seconds, "detail": detail})
        print(f"{name:<24} {status:<6} {seconds:>7.1f}  {detail}")

    failed = [r for r in rows if r["status"] == "FAIL"]
    skipped = [r for r in rows if r["status"] == "SKIP"]
    print(f"\nSUMMARY {len(rows) - len(failed) - len(skipped)} PASS / "
          f"{len(failed)} FAIL / {len(skipped)} SKIP")
    if a.json:
        Path(a.json).write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"-> {a.json}")
    return 1 if failed or (a.strict and skipped) else 0


if __name__ == "__main__":
    raise SystemExit(main())
