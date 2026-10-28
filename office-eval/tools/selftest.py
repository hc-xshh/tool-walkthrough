"""办公判分自测：用参考产物和三个错误变体验证口径。

需要装了 openpyxl 的解释器：设 `OFFICE_PYTHON`，否则依次尝试当前解释器和
DSH 自带的运行时。

用法：python tools/selftest.py
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
OFFICE = HERE.parent
FIXTURE = OFFICE / "fixtures" / "O1-xlsx-quarterly" / "repo"
BUILDER = OFFICE / "solutions" / "build_quarterly.py"
GRADE = HERE / "grade.py"

CASES = [
    ("correct", "pass"),
    ("missing_detail", "failed"),
    ("wrong_total", "failed"),
    ("string_numbers", "failed"),
    ("baseline", "failed"),
]


def python_with_openpyxl():
    candidates = [
        os.environ.get("OFFICE_PYTHON"),
        sys.executable,
        os.path.expanduser(
            r"~/.dsh/dsh-runtimes/dsh-primary-runtime/dependencies/python/python.exe"
        ),
    ]
    for cand in filter(None, candidates):
        try:
            probe = subprocess.run(
                [cand, "-c", "import openpyxl"], capture_output=True
            )
        except OSError:
            # 不存在的候选（例如只在 Windows 上有的 .exe 路径）应当跳过，
            # 而不是让整轮自测带着 traceback 退出。
            continue
        if probe.returncode == 0:
            return cand
    raise SystemExit("no python with openpyxl; set OFFICE_PYTHON")


def main():
    py = python_with_openpyxl()
    print(f"python: {py}")
    failures = 0
    root_base = OFFICE / ".selftest-tmp"
    if root_base.exists():
        shutil.rmtree(root_base, ignore_errors=True)
    root_base.mkdir(parents=True, exist_ok=True)
    try:
        for variant, expect in CASES:
            root = root_base / variant
            workdir = root / "work"
            shutil.copytree(FIXTURE, workdir)
            if variant != "baseline":
                built = subprocess.run(
                    [py, str(BUILDER), "--workdir", str(workdir), "--variant", variant],
                    capture_output=True, text=True, encoding="utf-8",
                )
                if built.returncode != 0:
                    print(f"FAIL  {variant}: builder failed\n{built.stderr[-600:]}")
                    failures += 1
                    continue
            out = root / "results" / f"{variant}.json"
            subprocess.run(
                [sys.executable, str(GRADE), "--task", "O1-xlsx-quarterly",
                 "--workdir", str(workdir), "--out", str(out), "--python", py],
                capture_output=True, text=True, encoding="utf-8",
            )
            result = json.loads(out.read_text(encoding="utf-8"))
            ok = result["verdict"] == expect
            print(f"{'PASS' if ok else 'FAIL'}  {variant:<16} expect={expect:<8} got={result['verdict']}")
            if not ok:
                failures += 1
                print("      ", result["reason"][:200])
    finally:
        shutil.rmtree(root_base, ignore_errors=True)
    print(f"\n{len(CASES) - failures}/{len(CASES)} cases matched")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
