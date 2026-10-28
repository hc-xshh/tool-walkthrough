#!/usr/bin/env python3
"""Preflight a tool before a code-eval suite: quota, account/model entitlement, wrong window.

  python code-eval/tools/preflight.py --tool cursor --port 9562 \
      --out runs/2026-10-26-cursor/preflight.json
  python code-eval/tools/preflight.py --tool qoder --port 9444 --expect Qoder
  python code-eval/tools/preflight.py --tool codex --out runs/.../preflight.json
  python code-eval/tools/run_tool.py ... --preflight runs/.../preflight.json

Exit: 0 ok, 1 unknown/connection error, 2 blocked (quota / account / wrong window).
The check is deliberately conservative: "ok" means no blocking marker was seen,
not that the plan has enough quota for the whole suite.
"""
import argparse
import json
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "harness"))

MARKERS = {
    "cursor": [
        ("quota", ["usage limit", "upgrade to pro", "out of usage"]),
    ],
    "qoder": [
        ("account/model", ["当前账号无法使用", "模型不可用", "额度不足", "余额不足", "credits 不足"]),
    ],
    "trae": [
        ("quota", ["积分不足", "额度不足", "升级套餐"]),
    ],
}

DEFAULT_PORTS = {"cursor": 9562, "qoder": 9444, "trae": 9339}


def redact(text):
    text = re.sub(r"[\w.+-]+@[\w.-]+", "<email>", text)
    text = re.sub(r"\b(?:sk|ak)-[A-Za-z0-9_-]{8,}\b", "<key>", text)
    return " ".join(text.split())[:400]


def detect_marker(tool, text):
    low = text.lower()
    for reason, words in MARKERS.get(tool, []):
        if any(w.lower() in low for w in words):
            return reason
    return None


def cdp_text(port, expect):
    from cdp import CDP

    c = CDP(port)
    try:
        text = c.eval("document.body.innerText") or ""
    finally:
        try:
            c.ws.close()
        except Exception:
            pass
    if expect and expect.lower() not in text.lower():
        return text, f"expected {expect!r} in window text; got another window/product"
    return text, None


def codex_info():
    exe = shutil.which("codex")
    if not exe:
        return None, "codex not on PATH"
    try:
        ver = subprocess.run([exe, "--version"], capture_output=True, text=True,
                             encoding="utf-8", errors="replace", timeout=15)
    except Exception as exc:
        return None, f"codex --version failed: {type(exc).__name__}: {exc}"
    cfg = Path.home() / ".codex" / "config.toml"
    model = provider = None
    if cfg.exists():
        raw = cfg.read_text(encoding="utf-8", errors="replace")
        m = re.search(r'^\s*model\s*=\s*"([^"]+)"', raw, re.M)
        p = re.search(r'^\s*model_provider\s*=\s*"([^"]+)"', raw, re.M)
        model = m.group(1) if m else None
        provider = p.group(1) if p else None
    return {
        "version": (ver.stdout or ver.stderr).strip(),
        "model": model,
        "provider": provider,
        "config": str(cfg),
    }, None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tool", required=True, choices=sorted(DEFAULT_PORTS) + ["codex"])
    ap.add_argument("--port", type=int, default=None)
    ap.add_argument("--expect", default=None, help="text that must appear in the window (wrong-window guard)")
    ap.add_argument("--out", default=None)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    result = {
        "tool": a.tool,
        "checked_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "status": "unknown",
        "reason": None,
        "evidence": None,
        "quota": "unknown",
    }

    try:
        if a.tool == "codex":
            info, err = codex_info()
            if err:
                result.update(status="blocked", reason=err)
            else:
                result.update(status="ok", **info)
                result["quota"] = "unknown (CLI has no balance/credits endpoint)"
        else:
            port = a.port or DEFAULT_PORTS[a.tool]
            result["port"] = port
            text, expect_err = cdp_text(port, a.expect)
            result["evidence"] = redact(text)
            if expect_err:
                result.update(status="blocked", reason=expect_err)
            else:
                hit = detect_marker(a.tool, text)
                if hit:
                    result.update(status="blocked", reason=f"{hit} marker found in window")
                else:
                    result.update(status="ok", reason="no blocking marker found")
    except Exception as exc:
        result.update(status="unknown", reason=f"{type(exc).__name__}: {exc}")

    text = json.dumps(result, ensure_ascii=False, indent=2)
    if a.out:
        out = Path(a.out).expanduser().resolve()
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text + "\n", encoding="utf-8")
        print(f"wrote {out}")
    if a.json:
        print(text)
    else:
        print(f"{result['tool']}: {result['status']} — {result['reason']}")
        if result.get("evidence"):
            print(f"  evidence: {result['evidence'][:160]}")
        if result.get("model"):
            print(f"  model={result['model']} provider={result['provider']}")

    return 2 if result["status"] == "blocked" else (0 if result["status"] == "ok" else 1)


if __name__ == "__main__":
    sys.exit(main())
