"""对一次判分结果做独立代码评审（Alibaba Open Code Review，命令名 `ocr`）。

它看的是「agent 改过的文件」而不是「过没过」：判分回答能不能收，评审回答改得怎么样。
与 grade.py 分开，是因为两者的失败模式不同——判分失败可以重跑，评审失败只该记
`unavailable`，不能让整轮评测变成 error。

用法：
  python tools/review.py --result runs/x/results/L1-r1.json [--out ...]
  python tools/review.py --result L1-r1.json --ocr /path/to/ocr --timeout 600

前置：`ocr` 能用（`ocr llm test` 通过）。没有 ocr 时退出 0 并写 status=unavailable，
因为「没装评审工具」不等于「这次尝试有问题」。产物默认写在结果旁边：
`<result>.review.json`。
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


def find_ocr(explicit=None):
    if explicit:
        return explicit if Path(explicit).exists() else None
    env = os.environ.get("OCR_BIN")
    if env and Path(env).exists():
        return env
    return shutil.which("ocr")


def changed_files(result):
    changes = result.get("changes") or {}
    files = list(changes.get("added") or []) + list(changes.get("modified") or [])
    # 保序去重；删除的文件在 scan 里没有意义
    seen, out = set(), []
    for f in files:
        if f not in seen:
            seen.add(f)
            out.append(f)
    return out


def normalize(comments):
    out = []
    for c in comments or []:
        if not isinstance(c, dict):
            continue
        out.append({
            "path": c.get("path"),
            "start_line": c.get("start_line"),
            "end_line": c.get("end_line"),
            "content": (c.get("content") or "").strip(),
            "suggestion": (c.get("suggestion_code") or "").strip(),
        })
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--result", required=True, help="grade.py 写出的结果 JSON")
    ap.add_argument("--workdir", default=None, help="默认读结果里的 workdir")
    ap.add_argument("--out", default=None, help="默认 <result>.review.json")
    ap.add_argument("--ocr", default=None, help="ocr 可执行文件路径")
    ap.add_argument("--timeout", type=int, default=900)
    ap.add_argument("--extra-args", default="", help="透传给 ocr scan 的参数（空格分隔）")
    a = ap.parse_args()

    result_path = Path(a.result).expanduser().resolve()
    if not result_path.exists():
        raise SystemExit(f"result not found: {result_path}")
    result = json.loads(result_path.read_text(encoding="utf-8-sig"))

    payload = {
        "schema": 1,
        "task": result.get("task"),
        "rep": result.get("rep"),
        "tool": result.get("tool"),
        "result": str(result_path),
        "status": "ok",
        "comments": [],
    }
    files = changed_files(result)
    payload["files"] = files

    if not files:
        payload["status"] = "no-changes"
    else:
        ocr = find_ocr(a.ocr)
        if not ocr:
            payload["status"] = "unavailable"
            payload["reason"] = "ocr not found; install @alibaba-group/open-code-review"
        else:
            workdir = Path(a.workdir or result.get("workdir") or "").expanduser()
            if not workdir.is_dir():
                payload["status"] = "error"
                payload["reason"] = f"workdir not found: {workdir}"
            else:
                cmd = [ocr, "scan", "--path", ",".join(files), "--format", "json"]
                cmd += [x for x in a.extra_args.split(" ") if x]
                try:
                    p = subprocess.run(cmd, cwd=str(workdir), capture_output=True,
                                       text=True, encoding="utf-8", errors="replace",
                                       timeout=a.timeout)
                except subprocess.TimeoutExpired:
                    payload["status"] = "timeout"
                    payload["reason"] = f"ocr scan exceeded {a.timeout}s"
                else:
                    if p.returncode != 0:
                        payload["status"] = "error"
                        payload["reason"] = (p.stderr or p.stdout).strip()[-800:]
                    else:
                        try:
                            data = json.loads(p.stdout)
                        except json.JSONDecodeError:
                            payload["status"] = "error"
                            payload["reason"] = "ocr returned non-JSON: " + p.stdout.strip()[:400]
                        else:
                            payload["comments"] = normalize(data.get("comments"))
                            payload["summary"] = data.get("summary")
                            payload["ocr"] = data.get("llm")

    out = Path(a.out).expanduser().resolve() if a.out else result_path.with_suffix(".review.json")
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    if payload["status"] == "ok":
        print(f"review: {len(payload['comments'])} comment(s) on {len(files)} file(s) -> {out}")
    else:
        print(f"review: {payload['status']}"
              + (f" — {payload.get('reason')}" if payload.get("reason") else "")
              + f" -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
