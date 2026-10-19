#!/usr/bin/env python3
"""Drive an Electron / Chromium app through its DevTools port.

Launch the app with --remote-debugging-port=<port>, then:

  cdp.py text                  # visible text
  cdp.py eval '<js>'           # evaluate JS (JSON result)
  cdp.py click '<css>'         # DOM click on a selector
  cdp.py clicktext '<label>'   # DOM click by exact/contained label
  cdp.py clickel '<label>'     # real mouse click by label (React pointer handlers)
  cdp.py clickel '<label>' --nth 1  # pick the 2nd visible match (0-based)
  cdp.py shot out.png          # renderer screenshot
  cdp.py info                  # list page targets

Why: a WebView/Electron UI is a DOM. Reading it beats OCR, and clicking by
label beats guessing coordinates. Use this before falling back to
ffmpeg + tesseract on the X11 desktop.

If WALKTHROUGH_RUN is set, each operation appends one line to
<run>/events.jsonl so `wt.py audit` can see CDP steps too.
"""
import argparse
import base64
import json
import os
import platform
import sys
import time
from datetime import datetime
from pathlib import Path

try:
    import requests
    import websocket
except ImportError as exc:  # actionable error when another project venv is active
    raise SystemExit(
        f"missing dependency: {exc.name}; run: pip install -r harness/requirements.txt"
    )


def _log(op, target, status, started, screenshot=None, detail=""):
    run = os.environ.get("WALKTHROUGH_RUN")
    if not run:
        return
    path = Path(run).expanduser().resolve()
    path.mkdir(parents=True, exist_ok=True)
    rec = {
        "ts": datetime.now().astimezone().isoformat(timespec="seconds"),
        "os": platform.system(),
        "action": f"cdp:{op}",
        "result": status,
        "duration_ms": int((time.monotonic() - started) * 1000),
        "target": str(target or "")[:200].replace("\n", " "),
    }
    if screenshot:
        rec["screenshot"] = str(screenshot)
    if detail:
        rec["detail"] = str(detail)[:300]
    with open(path / "events.jsonl", "a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")


def page_ws(port, match=None):
    tabs = requests.get(f"http://127.0.0.1:{port}/json/list", timeout=5).json()
    pages = [t for t in tabs if t.get("type") == "page"]
    if match:
        pages = [t for t in pages if match in (t.get("url") or "")]
    if not pages:
        raise SystemExit("no page target on port %s%s" % (port, f" matching {match!r}" if match else ""))
    return pages[0]["webSocketDebuggerUrl"]


class CDP:
    def __init__(self, port, match=None):
        # suppress_origin: Chrome rejects the default websocket Origin with 403
        self.ws = websocket.create_connection(page_ws(port, match), timeout=30, suppress_origin=True)
        self.n = 0

    def cmd(self, method, params=None):
        self.n += 1
        self.ws.send(json.dumps({"id": self.n, "method": method, "params": params or {}}))
        while True:
            msg = json.loads(self.ws.recv())
            if msg.get("id") == self.n:
                return msg

    def eval(self, expr):
        r = self.cmd("Runtime.evaluate", {"expression": expr, "returnByValue": True})
        return r.get("result", {}).get("result", {}).get("value")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=9339)
    ap.add_argument("op")
    ap.add_argument("arg", nargs="?")
    ap.add_argument("--nth", type=int, default=None,
                    help="0-based match index for clicktext/clickel (default: last)")
    ap.add_argument("--match", default=None,
                    help="pick the first page target whose URL contains this string (e.g. app://renderer)")
    a = ap.parse_args()

    started = time.monotonic()
    status, detail, shot_path = "ok", "", None

    try:
        c = CDP(a.port, a.match)
        if a.op == "text":
            print((c.eval("document.body.innerText") or "")[:6000])
        elif a.op == "eval":
            print(json.dumps(c.eval(a.arg), ensure_ascii=False))
        elif a.op == "click":
            sel = json.dumps(a.arg)
            print(c.eval(f"""(() => {{
              const el = document.querySelector({sel});
              if (!el) return 'not found';
              el.scrollIntoView({{block:'center'}}); el.click();
              return 'clicked: ' + (el.innerText || el.tagName).slice(0,40);
            }})()"""))
        elif a.op in ("clicktext", "clickel"):
            want = json.dumps(a.arg)
            pick = "hits[hits.length - 1]" if a.nth is None else f"hits[{a.nth}]"
            rect = c.eval(f"""(() => {{
              const all = Array.from(document.querySelectorAll('button,a,div,span,li'));
              let hits = all.filter(e => (e.innerText || '').trim() === {want} && e.offsetParent !== null);
              if (!hits.length) hits = all.filter(e => (e.innerText || '').includes({want})
                  && (e.innerText || '').length < {len(a.arg) + 12} && e.offsetParent !== null);
              const el = {pick};
              if (!el) return null;
              el.scrollIntoView({{block:'center'}});
              const r = el.getBoundingClientRect();
              return {{x: r.x + r.width / 2, y: r.y + r.height / 2, text: (el.innerText || '').slice(0, 40)}};
            }})()""")
            if not rect:
                print("not found")
                status, detail = "error", "not found"
                return
            if a.op == "clicktext":
                c.eval(f"""(() => {{
                  const all = Array.from(document.querySelectorAll('button,a,div,span,li'));
                  let hits = all.filter(e => (e.innerText || '').trim() === {want} && e.offsetParent !== null);
                  if (!hits.length) hits = all.filter(e => (e.innerText || '').includes({want})
                      && (e.innerText || '').length < {len(a.arg) + 12} && e.offsetParent !== null);
                  {pick}.click();
                }})()""")
            else:
                for t in ("mousePressed", "mouseReleased"):
                    c.cmd("Input.dispatchMouseEvent", {"type": t, "x": rect["x"], "y": rect["y"],
                                                       "button": "left", "clickCount": 1})
            print("clicked", rect["text"], "at %.0f,%.0f" % (rect["x"], rect["y"]))
        elif a.op == "shot":
            r = c.cmd("Page.captureScreenshot", {"format": "png"})
            open(a.arg, "wb").write(base64.b64decode(r["result"]["data"]))
            shot_path = a.arg
            print(a.arg)
        elif a.op == "info":
            for t in requests.get(f"http://127.0.0.1:{a.port}/json/list", timeout=5).json():
                print(t.get("type"), "|", t.get("title"), "|", t.get("url", "")[:100])
        else:
            print(__doc__)
    except Exception as e:
        status, detail = "error", f"{type(e).__name__}: {e}"
        raise
    finally:
        _log(a.op, a.arg, status, started, screenshot=shot_path, detail=detail)


if __name__ == "__main__":
    main()
