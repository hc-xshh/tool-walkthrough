"""办公产物判分：把隐藏验收拷进工作目录跑一遍，检查禁区有没有被改。

用法：
  python tools/grade.py --task O1-xlsx-quarterly --workdir runs/x/work/O1-r1 \\
      --out runs/x/results/O1-r1.json [--python <带 openpyxl 的解释器>]

验收脚本依赖 openpyxl / python-docx，所以 `--python` 要指向装了这些库的解释器；
不传时用当前解释器，并在缺库时给出明确提示。
"""

import argparse
import fnmatch
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
OFFICE = HERE.parent
CODE_EVAL = OFFICE.parent / "code-eval"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def forbidden_changes(workdir, fixture, patterns):
    """fixture 里命中 forbidden 的文件，在工作目录中内容是否变了。"""
    hits = []
    for src in Path(fixture).rglob("*"):
        if not src.is_file():
            continue
        rel = src.relative_to(fixture).as_posix()
        if not any(fnmatch.fnmatch(rel, g) for g in patterns):
            continue
        dst = Path(workdir) / rel
        if not dst.exists() or sha(dst) != sha(src):
            hits.append(rel)
    return hits


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", required=True)
    ap.add_argument("--workdir", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--python", default=os.environ.get("OFFICE_PYTHON") or sys.executable)
    ap.add_argument("--duration", type=float, default=None)
    ap.add_argument("--interventions", type=int, default=0)
    ap.add_argument("--timeout", type=int, default=180)
    a = ap.parse_args()

    spec = json.loads((OFFICE / "tasks" / f"{a.task}.json").read_text(encoding="utf-8"))
    workdir = Path(a.workdir).resolve()
    fixture = OFFICE / spec["fixture"]

    probe = subprocess.run([a.python, "-c", "import openpyxl"], capture_output=True)
    if probe.returncode != 0:
        raise SystemExit(
            f"{a.python} has no openpyxl; pass --python <interpreter> "
            "(or set OFFICE_PYTHON) to one that does"
        )

    result = {
        "schema": 1,
        "task": spec["id"],
        "level": spec.get("level"),
        "tool": "office",
        "workdir": str(workdir),
        "duration_s": a.duration,
        "interventions": a.interventions,
    }

    result["forbidden_changes"] = forbidden_changes(
        workdir, fixture, spec.get("forbidden", [])
    )

    accept_src = OFFICE / spec["accept"]
    accept_dst = workdir / "_accept"
    payload = {"total": 0, "passed": 0, "failures": [{"test": "<not run>", "message": ""}]}
    try:
        if accept_dst.exists():
            shutil.rmtree(accept_dst)
        shutil.copytree(accept_src, accept_dst)
        try:
            probe = subprocess.run(
                [a.python, str(CODE_EVAL / "tools" / "accept_run.py"), "_accept"],
                cwd=str(workdir),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=a.timeout,
            )
        except subprocess.TimeoutExpired:
            # 超时要写成一条验收失败，不能让异常穿过 main()——那会把 --out 一起丢掉。
            payload = {
                "total": 0,
                "passed": 0,
                "failures": [{
                    "test": "<probe>",
                    "status": "error",
                    "message": f"timeout after {a.timeout}s",
                }],
            }
        else:
            try:
                payload = json.loads(probe.stdout.strip().splitlines()[-1])
            except (ValueError, IndexError):
                payload = {
                    "total": 0,
                    "passed": 0,
                    "failures": [{
                        "test": "<probe>",
                        "status": "error",
                        "message": (probe.stderr or probe.stdout)[-1200:],
                    }],
                }
    finally:
        shutil.rmtree(accept_dst, ignore_errors=True)

    result["accept"] = payload

    if result["forbidden_changes"]:
        verdict = "scope_violation"
        reason = "改了禁区：" + ", ".join(result["forbidden_changes"])
    elif payload.get("total", 0) == 0 or payload.get("failures"):
        verdict = "failed"
        reason = (
            f"隐藏验收 {payload.get('passed')}/{payload.get('total')}；"
            + ", ".join(f["test"] for f in payload.get("failures", []))
        )
    else:
        verdict = "pass"
        reason = "隐藏验收全过，产物符合规格"

    result["verdict"] = verdict
    result["reason"] = reason

    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: result[k] for k in ("task", "verdict", "reason", "duration_s")},
                     ensure_ascii=False))
    print(f"result -> {out}")
    return 0 if verdict == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
