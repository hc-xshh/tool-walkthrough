#!/usr/bin/env python3
"""Cross-platform walkthrough harness.

One entry point for the operations that differ by OS:

  python3 harness/wt.py preflight
  python3 harness/wt.py new-run 2026-10-19-tool
  python3 harness/wt.py shot out.png
  python3 harness/wt.py click 300 241
  python3 harness/wt.py ocr out.png
  python3 harness/wt.py launch /path/to/app --log /tmp/app.log
  python3 harness/wt.py report runs/2026-10-19-tool

Linux uses X11 tooling (ffmpeg/xdotool). macOS uses screencapture and
cliclick (or AppleScript). Windows uses PowerShell/.NET and ctypes.
CDP stays in cdp.py and works on all three.
"""
from __future__ import annotations

import argparse
import os
import platform
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OS = platform.system()  # Linux / Darwin / Windows


def which_any(names):
    for n in names:
        p = shutil.which(n)
        if p:
            return p
    return None


def find_chrome():
    env = os.environ.get("WALKTHROUGH_CHROME")
    if env and Path(env).exists():
        return env
    if OS == "Darwin":
        for p in (
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Chromium.app/Contents/MacOS/Chromium",
            "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
        ):
            if Path(p).exists():
                return p
    if OS == "Windows":
        bases = [
            os.environ.get("ProgramFiles"),
            os.environ.get("ProgramFiles(x86)"),
            os.environ.get("LocalAppData"),
        ]
        rels = [
            r"Google\Chrome\Application\chrome.exe",
            r"Chromium\Application\chrome.exe",
            r"Microsoft\Edge\Application\msedge.exe",
        ]
        for base in filter(None, bases):
            for rel in rels:
                p = Path(base) / rel
                if p.exists():
                    return str(p)
    return which_any(["google-chrome", "chromium", "chromium-browser", "chrome", "msedge"])


def say(name, ok, detail, warn_only=False):
    status = "PASS" if ok else ("WARN" if warn_only else "FAIL")
    print(f"{name:<24} {status:<5} {detail}")
    return 0 if ok or warn_only else 1


def cmd_preflight(a):
    rc = 0
    print(f"{'os':<24} {'PASS':<5} {platform.platform()} ({platform.machine()})")
    rc |= say("python", sys.version_info >= (3, 9), platform.python_version())
    tess = which_any(["tesseract"])
    rc |= say("tesseract", bool(tess), tess or "install tesseract + chi_sim data")
    chrome = find_chrome()
    rc |= say("chrome", bool(chrome), chrome or "install Chrome/Chromium")
    print(f"{'git repo':<24} {'PASS':<5} {ROOT}")

    if OS == "Linux":
        for b in ("ffmpeg", "xdotool", "Xvfb", "openbox", "dbus-daemon"):
            p = which_any([b])
            rc |= say(b, bool(p), p or "missing (Linux desktop walkthroughs)")
        disp = a.display or os.environ.get("WALKTHROUGH_DISPLAY", ":98")
        ok = subprocess.run(
            ["xdpyinfo", "-display", disp], capture_output=True, text=True
        ).returncode == 0
        rc |= say(f"display {disp}", ok, "ok" if ok else "start desktop-up.sh")
    elif OS == "Darwin":
        say("screencapture", bool(which_any(["screencapture"])), "system tool", warn_only=True)
        clic = which_any(["cliclick"])
        say("cliclick", bool(clic), clic or "optional; brew install cliclick", warn_only=True)
        say("permissions", True, "grant Screen Recording + Accessibility to Terminal", warn_only=True)
    elif OS == "Windows":
        ps = which_any(["powershell", "pwsh"])
        rc |= say("powershell", bool(ps), ps or "missing")
        say("tesseract", bool(tess), tess or "install tesseract and add it to PATH")
        say("session", True, "run inside an interactive desktop session", warn_only=True)
    else:
        say("platform", False, f"unsupported OS: {OS}")
        rc = 1
    return 1 if rc else 0


def cmd_new_run(a):
    run = ROOT / "runs" / a.name
    for sub in ("shots", "logs", "artifacts"):
        (run / sub).mkdir(parents=True, exist_ok=True)
    print(run)
    print("runs/ is git-ignored. Do not 'git add -f' this directory.")


def cmd_shot(a):
    out = Path(a.out).expanduser().resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    if OS == "Linux":
        disp = a.display or os.environ.get("WALKTHROUGH_DISPLAY", ":98")
        env = dict(os.environ, DISPLAY=disp)
        subprocess.run(
            [
                "ffmpeg", "-hide_banner", "-loglevel", "error",
                "-f", "x11grab", "-video_size", a.geometry, "-i", disp,
                "-frames:v", "1", "-y", str(out),
            ],
            check=True, env=env,
        )
    elif OS == "Darwin":
        subprocess.run(["screencapture", "-x", "-o", str(out)], check=True)
    elif OS == "Windows":
        ps = r'''
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
$vs = [System.Windows.Forms.SystemInformation]::VirtualScreen
$bmp = New-Object System.Drawing.Bitmap $vs.Width, $vs.Height
$g = [System.Drawing.Graphics]::FromImage($bmp)
$g.CopyFromScreen($vs.Left, $vs.Top, 0, 0, $bmp.Size)
$bmp.Save($env:WT_OUT, [System.Drawing.Imaging.ImageFormat]::Png)
$g.Dispose(); $bmp.Dispose()
'''
        with tempfile.NamedTemporaryFile("w", suffix=".ps1", delete=False, encoding="utf-8") as f:
            f.write(ps)
            script = f.name
        try:
            subprocess.run(
                ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", script],
                check=True, env=dict(os.environ, WT_OUT=str(out)),
            )
        finally:
            os.unlink(script)
    else:
        raise SystemExit(f"unsupported OS: {OS}")
    print(out)


def cmd_click(a):
    if OS == "Linux":
        disp = a.display or os.environ.get("WALKTHROUGH_DISPLAY", ":98")
        subprocess.run(
            ["xdotool", "mousemove", "--sync", str(a.x), str(a.y), "click", str(a.button)],
            check=True, env=dict(os.environ, DISPLAY=disp),
        )
    elif OS == "Darwin":
        clic = which_any(["cliclick"])
        if clic:
            subprocess.run([clic, f"c:{a.x},{a.y}"], check=True)
        else:
            script = f'tell application "System Events" to click at {{{a.x}, {a.y}}}'
            subprocess.run(["osascript", "-e", script], check=True)
    elif OS == "Windows":
        import ctypes
        user32 = ctypes.windll.user32
        user32.SetCursorPos(int(a.x), int(a.y))
        down, up = (0x0002, 0x0004) if a.button == 1 else (0x0008, 0x0010)
        user32.mouse_event(down, 0, 0, 0, 0)
        user32.mouse_event(up, 0, 0, 0, 0)
    else:
        raise SystemExit(f"unsupported OS: {OS}")
    print(f"clicked {a.x},{a.y} button={a.button} os={OS}")


def cmd_ocr(a):
    tess = which_any(["tesseract"])
    if not tess:
        raise SystemExit("tesseract not found; install it and the chi_sim data")
    img = Path(a.image).expanduser().resolve()
    p = subprocess.run(
        [tess, str(img), "stdout", "-l", a.lang, "--psm", str(a.psm), "tsv"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if p.returncode != 0:
        raise SystemExit(p.stderr.strip() or "tesseract failed")
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
        print(f"{cols[11]}\tx={cols[6]} y={cols[7]} w={cols[8]} h={cols[9]}\tconf={cols[10]}")


def cmd_launch(a):
    log = Path(a.log).expanduser().resolve()
    log.parent.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    cmd = list(a.command)
    if cmd and cmd[0] == "--":
        cmd = cmd[1:]
    if OS == "Linux":
        base = Path(os.environ.get("WALKTHROUGH_BASE", "/tmp/walkthrough"))
        home = Path(os.environ.get("WALKTHROUGH_HOME", base / "home"))
        home.mkdir(parents=True, exist_ok=True)
        (base / "runtime").mkdir(parents=True, exist_ok=True)
        env.update(
            DISPLAY=a.display or os.environ.get("WALKTHROUGH_DISPLAY", ":98"),
            HOME=str(home),
            XDG_RUNTIME_DIR=str(base / "runtime"),
            DBUS_SESSION_BUS_ADDRESS=os.environ.get(
                "WALKTHROUGH_DBUS", f"unix:path={base}/runtime/bus"
            ),
            GDK_BACKEND="x11",
            LIBGL_ALWAYS_SOFTWARE="1",
            WEBKIT_DISABLE_COMPOSITING_MODE="1",
            WEBKIT_DISABLE_DMABUF_RENDERER="1",
        )
        with open(log, "wb") as fh:
            p = subprocess.Popen(cmd, stdout=fh, stderr=fh, env=env, start_new_session=True)
    elif OS == "Darwin":
        if a.app:
            cmd = ["open", "-a", a.app, "--args", *cmd]
        with open(log, "wb") as fh:
            p = subprocess.Popen(cmd, stdout=fh, stderr=fh, env=env, start_new_session=True)
    elif OS == "Windows":
        with open(log, "wb") as fh:
            p = subprocess.Popen(cmd, stdout=fh, stderr=fh, env=env)
    else:
        raise SystemExit(f"unsupported OS: {OS}")
    print(f"launched pid {p.pid} log={log}")


def cmd_report(a):
    script = ROOT / "harness" / "build-report.py"
    subprocess.run(
        [sys.executable, str(script), a.run_dir, "--out", a.out], check=True
    )


def main():
    ap = argparse.ArgumentParser(prog="wt.py", description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("preflight", help="check platform prerequisites")
    p.add_argument("--display", default=None)
    p.set_defaults(func=cmd_preflight)

    p = sub.add_parser("new-run", help="create runs/<name>/{shots,logs,artifacts}")
    p.add_argument("name")
    p.set_defaults(func=cmd_new_run)

    p = sub.add_parser("shot", help="capture the screen")
    p.add_argument("out")
    p.add_argument("--display", default=None)
    p.add_argument("--geometry", default="1440x900")
    p.set_defaults(func=cmd_shot)

    p = sub.add_parser("click", help="click at screen coordinates")
    p.add_argument("x", type=int)
    p.add_argument("y", type=int)
    p.add_argument("--button", type=int, default=1)
    p.add_argument("--display", default=None)
    p.set_defaults(func=cmd_click)

    p = sub.add_parser("ocr", help="OCR an image and print words with boxes")
    p.add_argument("image")
    p.add_argument("--lang", default="chi_sim+eng")
    p.add_argument("--psm", type=int, default=11)
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
    p.set_defaults(func=cmd_report)

    a = ap.parse_args()
    if a.cmd == "launch" and not a.command:
        ap.error("launch needs a command")
    return a.func(a)


if __name__ == "__main__":
    sys.exit(main() or 0)
