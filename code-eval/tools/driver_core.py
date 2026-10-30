#!/usr/bin/env python3
"""Plumbing shared by the CDP drivers (TRAE / Qoder / Cursor).

Each driver keeps what is product-specific: selectors, the composer protocol,
approval labels, and when a run counts as finished. What is identical across
products lives here instead of being copied into every drive_*.py:

  * invoking `harness/cdp.py` for one app window,
  * evaluating JS through a temp file and JSON-decoding the reply,
  * reading visible page text,
  * appending one JSONL record per event to the run trace,
  * polling a predicate with a deadline,
  * turning hidden-acceptance failures into the next round's prompt.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
CDP_SCRIPT = REPO / "harness" / "cdp.py"


def devtools_version(port: int) -> dict:
    """`/json/version` for one app: Browser/User-Agent carry its version.

    Results used to say only "Qoder CN", so a UI regression and a model
    regression looked the same a week later. Best effort: an unreachable port
    returns {} instead of failing the run.
    """
    try:
        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/json/version", timeout=5
        ) as fh:
            return json.load(fh)
    except Exception:  # noqa: BLE001 - attribution must never abort a run
        return {}


APP_VERSION_SKIP = {"mozilla", "chrome", "chromium", "safari", "electron",
                    "applewebkit", "gecko"}


def app_version(value: str) -> str:
    """Product version from a DevTools Browser / User-Agent string.

    'QoderCN/1.37.0 Chrome/148...' -> '1.37.0'. Engine tokens are skipped, so
    a UA with no product prefix yields '' instead of reporting the browser.
    """
    for match in re.finditer(r"([A-Za-z][A-Za-z0-9 ._-]*?)/(\d+\.\d+(?:\.\d+)*)", value or ""):
        if match.group(1).strip().lower() not in APP_VERSION_SKIP:
            return match.group(2)
    return ""


def repo_dirty() -> bool:
    """True when the harness checkout has uncommitted changes."""
    try:
        proc = subprocess.run(
            ["git", "-C", str(REPO), "status", "--porcelain"],
            capture_output=True, text=True, timeout=5,
        )
        return proc.returncode == 0 and bool(proc.stdout.strip())
    except (OSError, subprocess.SubprocessError):
        return False


def repo_sha() -> str:
    """Short HEAD of the harness checkout, for the run's provenance."""
    try:
        proc = subprocess.run(
            ["git", "-C", str(REPO), "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=5,
        )
        return proc.stdout.strip() if proc.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def log(path, event, **fields):
    """Append one trace record; `path` must already exist."""
    rec = {"ts": time.strftime("%H:%M:%S"), "event": event, **fields}
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")


class Cdp:
    """A `cdp.py` client bound to one window.

    `argv` is the cdp.py command prefix (port / match / match-title); `tmp_name`
    is the scratch JS file written next to the driver, so concurrent runs of
    different drivers do not overwrite each other's file.
    """

    def __init__(self, argv, tmp_name="_cdp_tmp.js"):
        self.argv = list(argv)
        self.tmp = HERE / tmp_name

    def port(self):
        """DevTools port from argv, or 0 when the client binds no port."""
        argv = self.argv
        if "--port" in argv:
            try:
                return int(argv[argv.index("--port") + 1])
            except (IndexError, ValueError):
                return 0
        return 0

    def click_label(self, label, timeout=60):
        """Click a label with a real pointer, in one cdp.py process.

        `clickel` finds the element and dispatches the mouse events itself, so
        the rect cannot go stale between the two steps. Calling eval here and
        clickxy there is a race: while the chat re-renders, the click lands on
        a neighbour. Returns "clicked" or "not found".
        """
        proc = self.run("clickel", label, timeout=timeout)
        return "clicked" if proc.returncode == 0 else "not found"

    def run(self, op, arg=None, timeout=90, check=False):
        cmd = self.argv + [op] + ([arg] if arg else [])
        proc = subprocess.run(
            cmd, capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=timeout,
        )
        if check and proc.returncode != 0:
            detail = (proc.stdout + proc.stderr)[-600:]
            raise RuntimeError(f"cdp {op} failed: {detail}")
        return proc

    def js(self, source, timeout=60):
        """Evaluate `source` in the page; JSON-decode the result when possible."""
        self.tmp.write_text(source, encoding="utf-8")
        try:
            proc = self.run("eval", "@" + str(self.tmp), timeout=timeout)
        finally:
            self.tmp.unlink(missing_ok=True)
        if proc.returncode != 0:
            return None
        raw = proc.stdout.strip()
        try:
            return json.loads(raw)
        except ValueError:
            return raw

    def text(self):
        """Visible page text, or '' when CDP is unreachable."""
        proc = self.run("text")
        return proc.stdout if proc.returncode == 0 else ""

    def pending_label(self, labels):
        """First visible button/role/div whose exact text is in `labels`."""
        wanted = json.dumps(list(labels), ensure_ascii=False)
        return self.js(f"""(() => {{
          const labels = {wanted};
          const els = Array.from(document.querySelectorAll('button,[role="button"],div,span'))
            .filter(e => e.offsetParent !== null);
          for (const label of labels) {{
            if (els.some(e => (e.innerText || '').trim() === label)) return label;
          }}
          return null;
        }})()""")


def wait_for(predicate, timeout, interval=1.0, label=""):
    """Poll `predicate` until true or the deadline passes; report timeouts."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    print(f"timeout waiting for {label}", file=sys.stderr)
    return False


def build_feedback(result, test_line):
    """Turn hidden-acceptance failures into the next round's prompt.

    Only test names and the last assertion line are shared with the tool, never
    the hidden test source.
    """
    lines = ["上一轮没有通过验收，请继续在这个仓库里修（不要改 tests/）："]
    for failure in (result.get("accept") or {}).get("failures", [])[:8]:
        tail = [ln for ln in (failure.get("message") or "").splitlines() if ln.strip()]
        lines.append(f"- {failure.get('test')}: {tail[-1][:160] if tail else ''}")
    lines.append(test_line)
    return "\n".join(lines)
