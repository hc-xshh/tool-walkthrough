#!/usr/bin/env python3
"""Cross-platform walkthrough harness.

One entry point for the operations that differ by OS:

  python3 harness/wt.py --run runs/2026-10-19-tool preflight
  python3 harness/wt.py new-run 2026-10-19-tool
  python3 harness/wt.py --run runs/2026-10-19-tool shot out.png
  python3 harness/wt.py --run runs/2026-10-19-tool click 300 241 --shot out.png
  python3 harness/wt.py --run runs/2026-10-19-tool ocr out.png
  python3 harness/wt.py --run runs/2026-10-19-tool launch --log app.log -- /path/to/app
  python3 harness/wt.py report runs/2026-10-19-tool
  python3 harness/wt.py audit --strict runs/2026-10-19-tool
  python3 harness/wt.py coverage runs/2026-10-19-tool

Linux uses X11 tooling (ffmpeg/xdotool). macOS uses screencapture and
cliclick (or AppleScript). Windows uses PowerShell/.NET and ctypes.
CDP stays in cdp.py and works on all three.

`shot` also writes `<png>.json` next to the image, recording where pixel (0,0)
sits (origin) and the pixels-per-click-unit ratio (scale). OCR returns pixel
coordinates inside the image, so pass `click --shot <png>` to land the click
where the word actually is: multi-monitor Windows and Retina macOS otherwise
click the wrong spot.

Checks live in wtcheck.py, capture in wtshot.py, shared plumbing in wtlib.py.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from wtlib import *  # noqa: F401,F403  (ROOT, OS, WT_VERSION, helpers)
from wtlib import profile, resolve_run, log_event
import wtshot
from wtshot import enable_dpi_awareness, read_shot_meta
from wtcheck import cmd_audit, cmd_coverage


def cmd_preflight(a):
    prof = profile(a)
    lock = load_lock()
    rc = 0
    print(f"{'profile':<24} {'PASS':<5} {prof.get('_name')} (os={OS})")
    print(f"{'os':<24} {'PASS':<5} {platform.platform()} ({platform.machine()})")

    py_min = version_tuple(lock.get("python_min", "3.9"))
    py_ok = sys.version_info[:2] >= py_min[:2]
    rc |= say("python", py_ok, platform.python_version())

    git = find_git()
    git_ver = git_version(git)
    git_min = version_tuple(lock.get("git_min", "2.20"))
    git_ok = bool(git) and bool(git_ver) and git_ver[:2] >= git_min[:2]
    if git:
        git_ver_text = ".".join(map(str, git_ver)) if git_ver else "version unknown"
        git_detail = f"{git} ({git_ver_text})"
    else:
        git_detail = "install git: new-run.sh, git hooks and code-eval diffs need it"
    rc |= say("git", git_ok, git_detail, warn_only=True)

    tess = which_any(["tesseract"])
    tess_ok = bool(tess)
    tess_min = version_tuple(lock.get("tesseract_min", "5.0"))
    tess_ver = tesseract_version()
    if tess and tess_ver and tess_min and tess_ver[:2] < tess_min[:2]:
        tess_ok = False
    langs = tesseract_langs() if tess else []
    wanted = [x for x in (prof.get("ocr_lang") or "eng").split("+") if x]
    missing_langs = [x for x in wanted if x not in langs]
    if missing_langs:
        tess_ok = False
    tess_detail = f"{tess or 'missing'} {'.'.join(map(str, tess_ver or ()))}".strip()
    if langs:
        tess_detail += f" langs={','.join(langs)}"
    if missing_langs:
        tess_detail += f" missing={','.join(missing_langs)} (put <lang>.traineddata in tessdata)"
    say("tesseract", tess_ok, tess_detail, warn_only=True)

    chrome = find_chrome()
    say("chrome", bool(chrome), chrome or "install Chrome/Chromium", warn_only=True)

    cdp_ok = all(module_available(m) for m in ("requests", "websocket"))
    say(
        "cdp deps",
        cdp_ok,
        "requests + websocket-client" if cdp_ok else "pip install -r harness/requirements.txt",
        warn_only=True,
    )

    if OS == "Linux":
        for b in ("ffmpeg", "xdotool", "Xvfb", "openbox", "dbus-daemon", "xdpyinfo"):
            p = which_any([b])
            say(b, bool(p), p or "missing (Linux desktop walkthroughs)", warn_only=True)
        disp = a.display or prof.get("display") or os.environ.get("WALKTHROUGH_DISPLAY", ":98")
        xdpy = which_any(["xdpyinfo"])
        ok = bool(xdpy) and subprocess.run(
            [xdpy, "-display", disp], capture_output=True, text=True
        ).returncode == 0
        rc |= say(f"display {disp}", ok, "ok" if ok else "start desktop-up.sh")
    elif OS == "Darwin":
        say("screencapture", bool(which_any(["screencapture"])), "system tool", warn_only=True)
        clic = which_any(["cliclick"])
        say("cliclick", bool(clic), clic or "optional; brew install cliclick", warn_only=True)
        say("permissions", True, "grant Screen Recording + Accessibility", warn_only=True)
    elif OS == "Windows":
        ps = which_any(["powershell", "pwsh"])
        say("powershell", bool(ps), ps or "missing", warn_only=True)
        say("session", True, "run inside an interactive desktop session", warn_only=True)
    else:
        say("platform", False, f"unsupported OS: {OS}")
        rc = 1

    caps = [
        "screenshot",
        "click" if OS != "Linux" or which_any(["xdotool"]) else "click:unavailable",
        "ocr" if tess_ok else "ocr:unavailable",
        "cdp" if cdp_ok else "cdp:unavailable",
        "git" if git_ok else "git:unavailable",
    ]
    print(f"{'capabilities':<24} {'INFO':<5} {', '.join(caps)}")
    native_ok = os.environ.get("WALKTHROUGH_NO_NATIVE_INPUT") != "1"
    print(
        f"{'native input':<24} {'INFO':<5} "
        + ("enabled: wt.py click moves the real pointer; prefer cdp.py"
           if native_ok else "disabled: cdp.py only, the pointer stays yours")
    )
    if lock and lock.get("wt_version") and lock["wt_version"] != WT_VERSION:
        say("lock version", False, f"lock={lock['wt_version']} wt={WT_VERSION}", warn_only=True)
    return 1 if rc else 0




def cmd_profiles(a):
    rows = []
    for p in sorted(PROFILES_DIR.glob("*.json")):
        d = json.loads(p.read_text(encoding="utf-8"))
        rows.append((d.get("name", p.stem), d.get("os", ""), d.get("isolation", "")))
    for name, os_name, isolation in rows:
        print(f"{name:<14} {os_name:<8} {isolation}")
    return {"target": "profiles", "detail": f"{len(rows)} profiles"}




def cmd_new_run(a):
    run = (ROOT / "runs" / a.name).resolve()
    for sub in ("shots", "screens", "logs", "trace", "artifacts"):
        (run / sub).mkdir(parents=True, exist_ok=True)
    tpl_dir = ROOT / "templates"
    scaffold = {
        "tool-profile.md": run / "tool-profile.md",
        "ui-map.md": run / "ui-map.md",
        "task-plan.md": run / "task-plan.md",
        "report.md": run / "report.md",
        "task-trace.md": run / "trace" / "task-trace.md",
    }
    copied = []
    for tpl, dest in scaffold.items():
        src = tpl_dir / tpl
        if src.exists() and not dest.exists():
            shutil.copyfile(src, dest)
            copied.append(str(dest.relative_to(run)))
    trace_log = run / "logs" / "task-trace.txt"
    trace_log.touch(exist_ok=True)
    crawl_notes = run / "logs" / "crawl-notes.txt"
    crawl_notes.touch(exist_ok=True)
    write_harness_json(run, profile(a))
    print(run)
    for rel in copied:
        print(f"scaffolded {rel}")
    print(f"scaffolded logs/{trace_log.name}, logs/{crawl_notes.name}, screens/")
    print("next: crawl the product (METHOD Step 1) and fill ui-map.md before designing tasks")
    print("runs/ is git-ignored. Do not 'git add -f' this directory.")
    return {"target": str(run), "detail": f"{len(copied)} templates + trace log"}




def cmd_shot(a):
    prof = profile(a)
    out = Path(a.out).expanduser().resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    disp = a.display or prof.get("display") or os.environ.get("WALKTHROUGH_DISPLAY", ":98")
    geom = a.geometry or prof.get("geometry") or ""

    meta = wtshot.capture_screen(out, disp, geom)
    print(out)
    print(
        f"shot origin={meta['origin_x']},{meta['origin_y']} "
        f"size={meta['width']}x{meta['height']} scale={meta['scale']} ({meta['source']})"
    )
    return {
        "target": str(out),
        "screenshot": str(out),
        "origin_x": meta["origin_x"],
        "origin_y": meta["origin_y"],
        "scale": meta["scale"],
        "detail": f"{meta['width']}x{meta['height']}",
    }


class _ShotArgs:
    """Minimal namespace so click can reuse cmd_shot's capture path."""

    display = None
    geometry = None
    profile = None

    def __init__(self, out):
        self.out = str(out)




def cmd_click(a):
    # 原生点击会移动用户的物理鼠标（Windows: SetCursorPos + mouse_event；
    # macOS: cliclick/osascript；Linux: xdotool）。想完全不碰用户的输入设备，
    # 就在这个开关下改用 cdp.py，或者把整轮走查放进隔离桌面。
    if getattr(a, "no_native_input", False) or os.environ.get("WALKTHROUGH_NO_NATIVE_INPUT") == "1":
        print(
            "native click disabled: it would move the physical pointer. "
            "Use `python3 harness/cdp.py clickel \"<label>\"` (DOM/mouse events inside the app) "
            "or run the walkthrough in an isolated desktop.",
            file=sys.stderr,
        )
        raise SystemExit(2)

    prof = profile(a)
    disp = a.display or prof.get("display") or os.environ.get("WALKTHROUGH_DISPLAY", ":98")
    x, y = float(a.x), float(a.y)
    note = ""
    if getattr(a, "shot", None):
        meta = read_shot_meta(Path(a.shot).expanduser().resolve())
        if meta:
            scale = meta.get("scale") or 1.0
            x = meta.get("origin_x", 0) + x / scale
            y = meta.get("origin_y", 0) + y / scale
            note = f" from {a.shot} (origin={meta.get('origin_x')},{meta.get('origin_y')} scale={scale})"
        else:
            print(f"warning: no sidecar for {a.shot}; using raw coordinates", file=sys.stderr)
    if getattr(a, "dry_run", False):
        print(f"would click {x:.0f},{y:.0f} button={a.button} os={OS}{note}")
        return {"target": f"{x:.0f},{y:.0f}", "detail": f"dry-run button={a.button}{note}"}
    if OS == "Linux":
        subprocess.run(
            ["xdotool", "mousemove", str(int(x)), str(int(y)), "click", str(a.button)],
            check=True, env=dict(os.environ, DISPLAY=disp),
        )
    elif OS == "Darwin":
        clic = which_any(["cliclick"])
        if clic:
            subprocess.run([clic, f"c:{x:.0f},{y:.0f}"], check=True)
        else:
            script = f'tell application "System Events" to click at {{{x:.0f}, {y:.0f}}}'
            subprocess.run(["osascript", "-e", script], check=True)
    elif OS == "Windows":
        enable_dpi_awareness()
        import ctypes
        user32 = ctypes.windll.user32
        if not user32.SetCursorPos(int(x), int(y)):
            raise SystemExit(f"SetCursorPos failed at {x:.0f},{y:.0f}")
        down, up = (0x0002, 0x0004) if a.button == 1 else (0x0008, 0x0010)
        user32.mouse_event(down, 0, 0, 0, 0)
        user32.mouse_event(up, 0, 0, 0, 0)
    else:
        raise SystemExit(f"unsupported OS: {OS}")
    print(f"clicked {x:.0f},{y:.0f} button={a.button} os={OS}{note}")
    rec = {"target": f"{x:.0f},{y:.0f}", "detail": f"button={a.button}{note}"}
    if getattr(a, "shot", None):
        rec["screenshot"] = str(Path(a.shot).expanduser().resolve())

    # A click without a screenshot is unverifiable later, and `audit` flags it.
    # Capture by default whenever there is a run to put the file in.
    if not getattr(a, "no_capture", False):
        run = resolve_run(a)
        if run:
            target = getattr(a, "capture", None)
            shot_out = (
                Path(target).expanduser().resolve()
                if target
                else run / "shots" / f"click-{datetime.now().strftime('%H%M%S')}-{int(x)}x{int(y)}.png"
            )
            cmd_shot(_ShotArgs(shot_out))
            rec["screenshot"] = str(shot_out)
    return rec




def cmd_ocr(a):
    prof = profile(a)
    tess = which_any(["tesseract"])
    if not tess:
        raise SystemExit("tesseract not found; install it and the chi_sim data")
    img = Path(a.image).expanduser().resolve()
    lang = a.lang or prof.get("ocr_lang") or "chi_sim+eng"
    psm = a.psm if a.psm is not None else prof.get("ocr_psm", 11)
    p = subprocess.run(
        [tess, str(img), "stdout", "-l", lang, "--psm", str(psm), "tsv"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if p.returncode != 0:
        raise SystemExit(p.stderr.strip() or "tesseract failed")
    count = 0
    for line in p.stdout.splitlines()[1:]:
        cols = line.split("\t")
        if len(cols) < 12 or not cols[11].strip():
            continue
        try:
            conf = float(cols[10])
        except ValueError:
            continue
        if conf < a.min_conf:
            continue
        count += 1
        print(f"{cols[11]}\tx={cols[6]} y={cols[7]} w={cols[8]} h={cols[9]}\tconf={cols[10]}")
    return {"target": str(img), "detail": f"{count} words"}




def cmd_launch(a):
    prof = profile(a)
    log = Path(a.log).expanduser().resolve()
    log.parent.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    cmd = list(a.command)
    if cmd and cmd[0] == "--":
        cmd = cmd[1:]
    if not cmd and OS != "Darwin":
        # --app only means "open -a <app>", which exists on macOS alone
        raise SystemExit(f"launch needs a command on {OS} (--app is macOS-only)")
    if OS == "Linux":
        base = Path(os.environ.get("WALKTHROUGH_BASE", "/tmp/walkthrough"))
        home = Path(os.environ.get("WALKTHROUGH_HOME", base / "home"))
        home.mkdir(parents=True, exist_ok=True)
        (base / "runtime").mkdir(parents=True, exist_ok=True)
        env.update(
            DISPLAY=a.display or prof.get("display") or os.environ.get("WALKTHROUGH_DISPLAY", ":98"),
            HOME=str(home),
            XDG_RUNTIME_DIR=str(base / "runtime"),
            DBUS_SESSION_BUS_ADDRESS=os.environ.get(
                "WALKTHROUGH_DBUS", f"unix:path={base}/runtime/bus"
            ),
        )
        # Software rendering is for headless/CI only. On a real desktop it
        # changes animation and scroll smoothness, which is exactly what a
        # walkthrough is supposed to judge.
        if prof.get("software_gl"):
            env.update(
                GDK_BACKEND="x11",
                LIBGL_ALWAYS_SOFTWARE="1",
                WEBKIT_DISABLE_COMPOSITING_MODE="1",
                WEBKIT_DISABLE_DMABUF_RENDERER="1",
            )
        with open(log, "wb") as fh:
            p = subprocess.Popen(cmd, stdout=fh, stderr=fh, env=env, start_new_session=True)
    elif OS == "Darwin":
        if a.app:
            cmd = ["open", "-a", a.app] + (["--args", *cmd] if cmd else [])
        with open(log, "wb") as fh:
            p = subprocess.Popen(cmd, stdout=fh, stderr=fh, env=env, start_new_session=True)
    elif OS == "Windows":
        with open(log, "wb") as fh:
            p = subprocess.Popen(cmd, stdout=fh, stderr=fh, env=env)
    else:
        raise SystemExit(f"unsupported OS: {OS}")
    print(f"launched pid {p.pid} log={log}")
    return {"target": " ".join(cmd), "detail": f"pid={p.pid} log={log}"}




def cmd_report(a):
    script = ROOT / "harness" / "build-report.py"
    cmd = [sys.executable, str(script), a.run_dir, "--out", a.out]
    for spec in getattr(a, "redact", []) or []:
        cmd += ["--redact", spec]
    for spec in getattr(a, "exclude", []) or []:
        cmd += ["--exclude", spec]
    if getattr(a, "appendix", False):
        cmd.append("--appendix")
    if getattr(a, "max_figure_height", None):
        cmd += ["--max-figure-height", a.max_figure_height]
    subprocess.run(cmd, check=True)
    return {"target": str(Path(a.run_dir).expanduser().resolve())}




def main():
    ap = argparse.ArgumentParser(prog="wt.py", description=__doc__)
    ap.add_argument("--run", default=None, help="run directory for events.jsonl")
    ap.add_argument("--profile", default=None, help="profile name (default: auto by OS)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("preflight", help="check platform prerequisites and capabilities")
    p.add_argument("--display", default=None)
    p.set_defaults(func=cmd_preflight)

    p = sub.add_parser("profiles", help="list platform profiles")
    p.set_defaults(func=cmd_profiles)

    p = sub.add_parser("new-run", help="create runs/<name>/{shots,logs,trace,artifacts} + templates")
    p.add_argument("name")
    p.set_defaults(func=cmd_new_run)

    p = sub.add_parser("shot", help="capture the screen")
    p.add_argument("out")
    p.add_argument("--display", default=None)
    p.add_argument("--geometry", default=None)
    p.set_defaults(func=cmd_shot)

    p = sub.add_parser("click", help="click at screen coordinates")
    p.add_argument("x", type=int)
    p.add_argument("y", type=int)
    p.add_argument("--button", type=int, default=1)
    p.add_argument("--display", default=None)
    p.add_argument("--shot", default=None,
                   help="translate coordinates from this shot's pixel space (uses its .json sidecar)")
    p.add_argument("--dry-run", action="store_true", help="print the translated target without clicking")
    p.add_argument("--capture", default=None, help="screenshot path to write right after clicking")
    p.add_argument("--no-capture", action="store_true",
                   help="do not screenshot after the click (audit will flag the click as unpaired)")
    p.add_argument("--no-native-input", action="store_true",
                   help="refuse to move the physical pointer; use cdp.py instead")
    p.set_defaults(func=cmd_click)

    p = sub.add_parser("ocr", help="OCR an image and print words with boxes")
    p.add_argument("image")
    p.add_argument("--lang", default=None)
    p.add_argument("--psm", type=int, default=None)
    p.add_argument("--min-conf", type=float, default=40)
    p.set_defaults(func=cmd_ocr)

    p = sub.add_parser("launch", help="launch an app with a log file")
    p.add_argument("command", nargs=argparse.REMAINDER)
    p.add_argument("--app", default=None, help="macOS app name for 'open -a'")
    p.add_argument("--log", default="/tmp/walkthrough/app.log")
    p.add_argument("--display", default=None)
    p.set_defaults(func=cmd_launch)

    p = sub.add_parser("report", help="render report.md to PDF")
    p.add_argument("run_dir")
    p.add_argument("--out", default="report.pdf")
    p.add_argument("--redact", action="append", default=[], metavar="X,Y,W,H",
                   help="paint this rectangle white in every embedded image (repeatable)")
    p.add_argument("--exclude", action="append", default=[], metavar="GLOB",
                   help="leave shots matching this glob out of the appendix (repeatable)")
    p.add_argument("--appendix", action="store_true",
                   help="also append the remaining shots as an appendix")
    p.add_argument("--max-figure-height", default=None, help="cap figure height, e.g. 105mm")
    p.set_defaults(func=cmd_report)

    p = sub.add_parser("audit", help="cross-check events, report and evidence")
    p.add_argument("run_dir")
    p.add_argument("--strict", action="store_true", help="treat WARN as failure (use in CI)")
    p.set_defaults(func=cmd_audit)

    p = sub.add_parser("coverage", help="show controls in ui-map.md that no task covers")
    p.add_argument("run_dir")
    p.add_argument("--strict", action="store_true", help="exit non-zero when anything is uncovered")
    p.set_defaults(func=cmd_coverage)

    a = ap.parse_args()
    if a.cmd == "launch" and not a.command and not a.app:
        ap.error("launch needs a command, or --app on macOS")

    run = resolve_run(a)
    started = time.monotonic()
    try:
        result = a.func(a)
        if isinstance(result, dict):
            extra, rc = result, 0
        elif isinstance(result, int):
            extra, rc = {}, result
        else:
            extra, rc = {}, 0
        if a.cmd != "audit":
            log_event(
                run,
                action=a.cmd,
                result="ok" if rc == 0 else "error",
                duration_ms=int((time.monotonic() - started) * 1000),
                **extra,
            )
        return rc
    except SystemExit as e:
        code = e.code if isinstance(e.code, int) else 1
        if a.cmd != "audit":
            log_event(
                run,
                action=a.cmd,
                result="error",
                duration_ms=int((time.monotonic() - started) * 1000),
                detail=str(e),
            )
        if code:
            print(e, file=sys.stderr)
        return code
    except Exception as e:
        if a.cmd != "audit":
            log_event(
                run,
                action=a.cmd,
                result="error",
                duration_ms=int((time.monotonic() - started) * 1000),
                detail=f"{type(e).__name__}: {e}",
            )
        raise


if __name__ == "__main__":
    sys.exit(main() or 0)
