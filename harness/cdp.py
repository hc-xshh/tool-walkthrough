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
  cdp.py frames                # list every target, incl. webview iframes
  cdp.py --kind iframe --nested text   # VS Code / IDE webview panels

Webview panels (VS Code extensions, some IDE sidebars) are not `page` targets
and cannot be read from the host page: probe with `frames`, then drive the
iframe target directly. Their content often lives one level deeper, so
`--nested` swaps `document` for the inner iframe document.


Only the real desktop is allowed. On Linux the target must have a visible
window on DISPLAY=:0 inside an active seated session; headless and virtual
targets are refused.

Why: a WebView/Electron UI is a DOM. Reading it beats OCR, and clicking by
label beats guessing coordinates. Use this before falling back to
ffmpeg + tesseract on the real desktop.

If WALKTHROUGH_RUN is set, each operation appends one line to
<run>/events.jsonl so `wt.py audit` can see CDP steps too.
"""
import argparse
import base64
import json
import os
import platform
import re
import shutil
import struct
import subprocess
import time
from datetime import datetime
from pathlib import Path

from wtlib import verify_real_session

try:
    import requests
    import websocket
except ImportError as exc:  # actionable error when another project venv is active
    raise SystemExit(
        f"missing dependency: {exc.name}; run: pip install -r harness/requirements.txt"
    )


VK = {
    "Enter": 13, "Escape": 27, "Tab": 9, "Backspace": 8, "Delete": 46,
    "ArrowLeft": 37, "ArrowUp": 38, "ArrowRight": 39, "ArrowDown": 40,
    "Home": 36, "End": 35, "PageUp": 33, "PageDown": 34, "Space": 32,
}


def require_real_window(title, disp=":0"):
    """Refuse CDP targets that are not backed by a visible desktop window.

    A headless Chromium has no X11/Wayland window; attaching to it would make
    the walkthrough evaluate a virtual browser and report findings that the
    real product may not have. On Linux we verify that a visible window with
    the target's document title exists on the current DISPLAY.
    """
    if platform.system() != "Linux":
        return
    xdo = shutil.which("xdotool")
    if not xdo:
        raise SystemExit(
            "cdp: cannot verify the real desktop window; install xdotool or "
            "use the real display session"
        )
    title = str(title or "").strip()
    if not title:
        raise SystemExit(
            "cdp: target has no window title; refusing an unverifiable/headless target"
        )
    p = subprocess.run(
        [xdo, "search", "--onlyvisible", "--name", re.escape(title)],
        capture_output=True, text=True, timeout=10,
        env=dict(os.environ, DISPLAY=disp),
    )
    if p.returncode != 0 or not (p.stdout or "").strip():
        raise SystemExit(
            f"cdp: no visible real-desktop window for {title!r}; "
            "headless/virtual targets are disabled"
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
        rec["screenshot"] = str(Path(screenshot).expanduser().resolve())
    if detail:
        rec["detail"] = str(detail)[:300]
    with open(path / "events.jsonl", "a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")


def pick_target(tabs, match=None, kind="page"):
    """Pick the main app page, not a pet/helper/empty target.

    Electron apps expose several `page` targets (Qoder: desktop-pet first,
    renderer second, an empty page third). `pages[0]` silently attached to the
    pet and `text` came back empty. Score by URL shape and skip known helpers.
    """
    kinds = ("page", "iframe") if kind == "any" else (kind,)
    pages = [t for t in tabs if t.get("type") in kinds]
    if match:
        pages = [t for t in pages if match in (t.get("url") or "")]
    if not pages:
        return None

    def score(tab):
        url = (tab.get("url") or "").lower()
        title = (tab.get("title") or "").strip()
        value = 0
        if "renderer" in url:
            value += 5
        if "index.html" in url:
            value += 3
        if url.startswith("app://") or url.startswith("file://"):
            value += 2
        if title:
            value += 1
        if any(bad in url for bad in ("desktop-pet", "fixed-surface", "devtools",
                                      "background", "worker")):
            value -= 10
        if not url:
            value -= 10
        return value

    return max(pages, key=score)


def page_ws(port, match=None, kind="page"):
    tabs = requests.get(f"http://127.0.0.1:{port}/json/list", timeout=5).json()
    target = pick_target(tabs, match, kind)
    if not target:
        raise SystemExit("no %s target on port %s%s" % (kind, port, f" matching {match!r}" if match else ""))
    return target["webSocketDebuggerUrl"]


class CDP:
    def __init__(self, port, match=None, kind="page", nested=False):
        # suppress_origin: Chrome rejects the default websocket Origin with 403
        self.ws = websocket.create_connection(page_ws(port, match, kind), timeout=30, suppress_origin=True)
        self.n = 0
        self.nested = nested
        disp = os.environ.get("DISPLAY") or ":0"
        if platform.system() == "Linux":
            if disp.split(".")[0] != ":0":
                raise SystemExit(
                    f"cdp: virtual displays are disabled ({disp}); use DISPLAY=:0"
                )
            verify_real_session(disp)
            require_real_window(self.eval("document.title"), disp)

    def cmd(self, method, params=None):
        self.n += 1
        self.ws.send(json.dumps({"id": self.n, "method": method, "params": params or {}}))
        while True:
            msg = json.loads(self.ws.recv())
            if msg.get("id") == self.n:
                return msg

    def eval(self, expr):
        if self.nested:
            # VS Code webview: the real UI sits in an inner iframe one level
            # down. Shadow `document` with a parameter instead of rewriting the
            # expression text, which used to corrupt identifiers such as
            # documentElement and any string literal containing "document".
            expr = (
                "(function (document) {"
                "  const inner = document.querySelector('iframe')?.contentDocument || document;"
                f"  return (function (document) {{ return ({expr}); }})(inner);"
                "})(document)"
            )
        r = self.cmd("Runtime.evaluate", {"expression": expr, "returnByValue": True})
        res = r.get("result", {})
        exc = res.get("exceptionDetails")
        if exc:
            text = (exc.get("exception") or {}).get("description") or exc.get("text") or "JS exception"
            raise RuntimeError(text.splitlines()[0])
        return res.get("result", {}).get("value")


def png_size(path):
    """Return (width, height) from a PNG IHDR, or (0, 0) if not a PNG."""
    try:
        with open(path, "rb") as f:
            head = f.read(24)
        if len(head) >= 24 and head[:8] == b"\x89PNG\r\n\x1a\n":
            return struct.unpack(">II", head[16:24])
    except OSError:
        pass
    return 0, 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=9339)
    ap.add_argument("op")
    ap.add_argument("arg", nargs="?")
    ap.add_argument("--nth", type=int, default=None,
                    help="0-based match index for clicktext/clickel (default: last)")
    ap.add_argument("--match", default=None,
                    help="pick the first page target whose URL contains this string (e.g. app://renderer)")
    ap.add_argument("--kind", default="page", choices=["page", "iframe", "any"],
                    help="target type to attach to; IDE webview panels live in 'iframe'")
    ap.add_argument("--nested", action="store_true",
                    help="evaluate inside the first inner iframe (VS Code webview payload)")
    ap.add_argument("--capture", default=None,
                    help="renderer screenshot to write after the operation (paired with clicks)")
    a = ap.parse_args()

    # `eval @path/to/expr.js`: Windows shells strip the quotes out of an inline
    # expression, so anything with spaces or string literals should come from a
    # file instead of the command line.
    if a.arg and a.arg.startswith("@") and a.op in ("eval", "click", "clicktext", "clickel", "type"):
        expr_file = Path(a.arg[1:]).expanduser()
        a.arg = expr_file.read_text(encoding="utf-8").strip()

    started = time.monotonic()
    status, detail, shot_path = "ok", "", None

    try:
        c = CDP(a.port, a.match, a.kind, a.nested)
        if a.op == "text":
            print((c.eval("document.body.innerText") or "")[:6000])
        elif a.op == "eval":
            print(json.dumps(c.eval(a.arg), ensure_ascii=False))
        elif a.op == "click":
            sel = json.dumps(a.arg)
            out = c.eval(f"""(() => {{
              const el = document.querySelector({sel});
              if (!el) return 'not found';
              el.scrollIntoView({{block:'center'}}); el.click();
              return 'clicked: ' + (el.innerText || el.tagName).slice(0,40);
            }})()""")
            print(out)
            if out == "not found":
                status, detail = "error", f"selector not found: {a.arg}"
                raise SystemExit(1)
        elif a.op == "clickxy":
            x, y = (float(v) for v in a.arg.split(","))
            for t in ("mousePressed", "mouseReleased"):
                c.cmd("Input.dispatchMouseEvent", {"type": t, "x": x, "y": y,
                                                   "button": "left", "clickCount": 1})
            print(f"clicked at {x:.0f},{y:.0f}")
        elif a.op == "type":
            c.cmd("Input.insertText", {"text": a.arg or ""})
            # Log the length, not the text: events.jsonl is copied into reports.
            print(f"typed {len(a.arg or '')} chars")
            detail = f"{len(a.arg or '')} chars"
        elif a.op == "key":
            key = a.arg or "Enter"
            code = VK.get(key, 13)
            for t in ("keyDown", "keyUp"):
                c.cmd("Input.dispatchKeyEvent", {"type": t, "key": key, "code": key,
                                                 "windowsVirtualKeyCode": code,
                                                 "nativeVirtualKeyCode": code})
            print(f"key {key}")
        elif a.op == "keycombo":
            parts = (a.arg or "").lower().split("+")
            key = parts[-1]
            mods = {"alt": 1, "ctrl": 2, "meta": 4, "shift": 8}
            modifiers = sum(mods.get(p, 0) for p in parts[:-1])
            named = {k.lower(): v for k, v in VK.items()}
            vk = ord(key.upper()) if len(key) == 1 else named.get(key, 0)
            code = ("Key" + key.upper()) if len(key) == 1 else key.capitalize()
            for t in ("keyDown", "keyUp"):
                c.cmd("Input.dispatchKeyEvent", {"type": t, "key": key, "code": code,
                                                 "modifiers": modifiers,
                                                 "windowsVirtualKeyCode": vk,
                                                 "nativeVirtualKeyCode": vk})
            print(f"key {a.arg}")
        elif a.op in ("clicktext", "clickel"):
            want = json.dumps(a.arg)
            pick = "hits[hits.length - 1]" if a.nth is None else f"hits[{a.nth}]"
            rect = c.eval(f"""(() => {{
              const all = Array.from(document.querySelectorAll('button,a,div,span,li'));
              const label = e => (e.innerText || e.getAttribute('aria-label') || e.getAttribute('title') || '').trim();
              let hits = all.filter(e => label(e) === {want} && e.offsetParent !== null);
              if (!hits.length) {{
                // substring fallback: shortest label wins, otherwise "文件"
                // matches "选择文件夹（可选）" and clicks the wrong control
                hits = all.filter(e => label(e).includes({want})
                    && label(e).length < {len(a.arg) + 12} && e.offsetParent !== null)
                  .sort((x, y) => label(x).length - label(y).length);
              }}
              const el = {pick};
              if (!el) return null;
              el.scrollIntoView({{block:'center'}});
              const r = el.getBoundingClientRect();
              return {{x: r.x + r.width / 2, y: r.y + r.height / 2, text: label(el).slice(0, 40)}};
            }})()""")
            if not rect:
                print("not found")
                status, detail = "error", f"label not found: {a.arg}"
                raise SystemExit(1)
            if a.op == "clicktext":
                c.eval(f"""(() => {{
                  const all = Array.from(document.querySelectorAll('button,a,div,span,li'));
                  const label = e => (e.innerText || e.getAttribute('aria-label') || e.getAttribute('title') || '').trim();
                  let hits = all.filter(e => label(e) === {want} && e.offsetParent !== null);
                  if (!hits.length) hits = all.filter(e => label(e).includes({want})
                      && label(e).length < {len(a.arg) + 12} && e.offsetParent !== null)
                    .sort((x, y) => label(x).length - label(y).length);
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
            w, h = png_size(a.arg)
            print(f"{a.arg} ({w}x{h})")
            if w and (w < 800 or h < 400):
                print(f"WARN: {w}x{h} is below 800x400; for evidence, crop to the control "
                      f"or capture a larger window")
        elif a.op == "info":
            for t in requests.get(f"http://127.0.0.1:{a.port}/json/list", timeout=5).json():
                print(t.get("type"), "|", t.get("title"), "|", t.get("url", "")[:100])
        elif a.op == "frames":
            for t in requests.get(f"http://127.0.0.1:{a.port}/json/list", timeout=5).json():
                if t.get("type") in ("page", "iframe"):
                    print(t.get("type"), "|", (t.get("title") or "")[:40], "|", (t.get("url") or "")[:100])
        else:
            print(__doc__)
        # A click with no screenshot cannot be verified later; `wt.py audit`
        # pairs click events with shot events, and a click event that carries
        # its own screenshot counts as paired.
        if a.capture and not shot_path:
            r = c.cmd("Page.captureScreenshot", {"format": "png"})
            out = Path(a.capture).expanduser().resolve()
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(base64.b64decode(r["result"]["data"]))
            shot_path = str(out)
            w, h = png_size(out)
            print(f"captured {out} ({w}x{h})")
            if w and (w < 800 or h < 400):
                print(f"WARN: {w}x{h} is below 800x400; for evidence, crop to the control "
                      f"or capture a larger window")
    except Exception as e:
        status, detail = "error", f"{type(e).__name__}: {e}"
        raise
    finally:
        # never write the typed text itself into events.jsonl
        logged_target = None if a.op == "type" else a.arg
        _log(a.op, logged_target, status, started, screenshot=shot_path, detail=detail)


if __name__ == "__main__":
    main()
