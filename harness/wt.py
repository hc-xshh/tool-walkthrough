#!/usr/bin/env python3
"""Cross-platform walkthrough harness.

One entry point for the operations that differ by OS:

  python3 harness/wt.py --run runs/2026-10-19-tool preflight
  python3 harness/wt.py new-run 2026-10-19-tool
  python3 harness/wt.py --run runs/2026-10-19-tool shot out.png
  python3 harness/wt.py --run runs/2026-10-19-tool click 300 241
  python3 harness/wt.py --run runs/2026-10-19-tool ocr out.png
  python3 harness/wt.py --run runs/2026-10-19-tool launch --log app.log -- /path/to/app
  python3 harness/wt.py report runs/2026-10-19-tool
  python3 harness/wt.py audit runs/2026-10-19-tool

Linux uses X11 tooling (ffmpeg/xdotool). macOS uses screencapture and
cliclick (or AppleScript). Windows uses PowerShell/.NET and ctypes.
CDP stays in cdp.py and works on all three.

Every command with --run (or WALKTHROUGH_RUN) appends one line to
runs/<run>/events.jsonl: timestamp, action, target, result, duration and
evidence path. `audit` cross-checks that log against report.md and shots/.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OS = platform.system()  # Linux / Darwin / Windows
WT_VERSION = "1.2.0"
PROFILES_DIR = ROOT / "harness" / "profiles"
LOCK_FILE = ROOT / "harness" / "harness.lock"


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


def load_profile(name):
    if not name or name == "auto":
        name = {"Linux": "linux-desktop", "Darwin": "macos", "Windows": "windows"}.get(OS, "linux-desktop")
    path = PROFILES_DIR / f"{name}.json"
    if not path.exists():
        raise SystemExit(f"unknown profile: {name} (looked in {PROFILES_DIR})")
    data = json.loads(path.read_text(encoding="utf-8"))
    data["_name"] = name
    return data


def profile(a):
    if not hasattr(a, "_profile"):
        a._profile = load_profile(getattr(a, "profile", None))
    return a._profile


def version_tuple(text):
    m = re.search(r"(\d+)(?:\.(\d+))?(?:\.(\d+))?", str(text))
    if not m:
        return ()
    return tuple(int(x) for x in m.groups() if x is not None)


def tesseract_version():
    p = which_any(["tesseract"])
    if not p:
        return None
    try:
        out = subprocess.run([p, "--version"], capture_output=True, text=True, timeout=5)
        return version_tuple(out.stdout or out.stderr)
    except Exception:
        return None


def load_lock():
    if LOCK_FILE.exists():
        try:
            return json.loads(LOCK_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def resolve_run(a):
    if getattr(a, "run", None):
        return Path(a.run).expanduser().resolve()
    if getattr(a, "cmd", None) == "new-run":
        return (ROOT / "runs" / a.name).resolve()
    if getattr(a, "cmd", None) in ("report", "audit"):
        return Path(a.run_dir).expanduser().resolve()
    env = os.environ.get("WALKTHROUGH_RUN")
    return Path(env).expanduser().resolve() if env else None


def log_event(run, **fields):
    if not run:
        return
    run.mkdir(parents=True, exist_ok=True)
    rec = {
        "ts": datetime.now().astimezone().isoformat(timespec="seconds"),
        "os": OS,
        **fields,
    }
    with open(run / "events.jsonl", "a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")


def read_events(run):
    events = []
    path = run / "events.jsonl"
    if not path.exists():
        return events
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return events


def write_harness_json(run, prof):
    path = run / "harness.json"
    if path.exists():
        return
    lock = load_lock()
    data = {
        "schema": 1,
        "wt_version": WT_VERSION,
        "profile": prof.get("_name"),
        "os": platform.platform(),
        "python": platform.python_version(),
        "tesseract": ".".join(map(str, tesseract_version() or ())) or "not found",
        "chrome": find_chrome() or "not found",
        "lock": lock,
        "created": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def say(name, ok, detail, warn_only=False):
    status = "PASS" if ok else ("WARN" if warn_only else "FAIL")
    print(f"{name:<24} {status:<5} {detail}")
    return 0 if ok or warn_only else 1


def cmd_preflight(a):
    prof = profile(a)
    lock = load_lock()
    rc = 0
    print(f"{'profile':<24} {'PASS':<5} {prof.get('_name')} (os={OS})")
    print(f"{'os':<24} {'PASS':<5} {platform.platform()} ({platform.machine()})")

    py_min = version_tuple(lock.get("python_min", "3.9"))
    py_ok = sys.version_info[:2] >= py_min[:2]
    rc |= say("python", py_ok, platform.python_version())

    tess = which_any(["tesseract"])
    tess_ok = bool(tess)
    tess_min = version_tuple(lock.get("tesseract_min", "5.0"))
    tess_ver = tesseract_version()
    if tess and tess_ver and tess_min and tess_ver[:2] < tess_min[:2]:
        tess_ok = False
    say("tesseract", tess_ok, f"{tess or 'missing'} {'.'.join(map(str, tess_ver or ()))}".strip(), warn_only=True)

    chrome = find_chrome()
    say("chrome", bool(chrome), chrome or "install Chrome/Chromium", warn_only=True)

    if OS == "Linux":
        for b in ("ffmpeg", "xdotool", "Xvfb", "openbox", "dbus-daemon"):
            p = which_any([b])
            say(b, bool(p), p or "missing (Linux desktop walkthroughs)", warn_only=True)
        disp = a.display or prof.get("display") or os.environ.get("WALKTHROUGH_DISPLAY", ":98")
        ok = subprocess.run(
            ["xdpyinfo", "-display", disp], capture_output=True, text=True
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
        "cdp",
    ]
    print(f"{'capabilities':<24} {'INFO':<5} {', '.join(caps)}")
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
    for sub in ("shots", "logs", "artifacts"):
        (run / sub).mkdir(parents=True, exist_ok=True)
    write_harness_json(run, profile(a))
    print(run)
    print("runs/ is git-ignored. Do not 'git add -f' this directory.")
    return {"target": str(run)}


def cmd_shot(a):
    prof = profile(a)
    out = Path(a.out).expanduser().resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    disp = a.display or prof.get("display") or os.environ.get("WALKTHROUGH_DISPLAY", ":98")
    geom = a.geometry or prof.get("geometry") or "1440x900"

    if OS == "Linux":
        subprocess.run(
            [
                "ffmpeg", "-hide_banner", "-loglevel", "error",
                "-f", "x11grab", "-video_size", geom, "-i", disp,
                "-frames:v", "1", "-y", str(out),
            ],
            check=True, env=dict(os.environ, DISPLAY=disp),
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
    return {"target": str(out), "screenshot": str(out)}


def cmd_click(a):
    prof = profile(a)
    disp = a.display or prof.get("display") or os.environ.get("WALKTHROUGH_DISPLAY", ":98")
    if OS == "Linux":
        subprocess.run(
            ["xdotool", "mousemove", str(a.x), str(a.y), "click", str(a.button)],
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
    return {"target": f"{a.x},{a.y}", "detail": f"button={a.button}"}


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
    return {"target": " ".join(cmd), "detail": f"pid={p.pid} log={log}"}


def cmd_report(a):
    script = ROOT / "harness" / "build-report.py"
    subprocess.run(
        [sys.executable, str(script), a.run_dir, "--out", a.out], check=True
    )
    return {"target": str(Path(a.run_dir).expanduser().resolve())}


def cmd_audit(a):
    run = Path(a.run_dir).expanduser().resolve()
    events = read_events(run)
    checks = []

    report = run / "report.md"
    report_ok = report.exists() and report.stat().st_size > 0
    checks.append(("report.md", "PASS" if report_ok else "FAIL", str(report)))

    text = report.read_text(encoding="utf-8", errors="replace") if report_ok else ""
    refs = re.findall(r"shots/[^\s)`\"']+\.(?:png|jpg|jpeg)", text)
    missing_refs = [r for r in refs if not (run / r).exists()]
    checks.append((
        "report image refs",
        "PASS" if refs and not missing_refs else ("FAIL" if missing_refs else "WARN"),
        f"{len(refs)} refs, {len(missing_refs)} missing",
    ))

    shots = [e for e in events if e.get("action") in ("shot", "cdp:shot")]
    bad_shots = []
    for e in shots:
        p = Path(e.get("screenshot", ""))
        if not p.is_absolute():
            candidates = [run / p, run.parent / p, Path.cwd() / p]
            p = next((c for c in candidates if c.exists()), p)
        if not p.exists():
            bad_shots.append(str(p))
    checks.append((
        "shot files",
        "PASS" if shots and not bad_shots else ("FAIL" if bad_shots else "WARN"),
        f"{len(shots)} shots, {len(bad_shots)} missing",
    ))

    errors = [e for e in events if e.get("result") == "error"]
    checks.append((
        "error events",
        "PASS" if not errors else "WARN",
        f"{len(errors)} (last: {errors[-1].get('action') if errors else '-'})",
    ))

    gaps = 0
    for i, e in enumerate(events):
        if e.get("action") == "click":
            if not any(x.get("action") == "shot" for x in events[i + 1:i + 6]):
                gaps += 1
    checks.append((
        "click -> shot",
        "PASS" if gaps == 0 else "WARN",
        f"{gaps} clicks without a later shot",
    ))

    harness = run / "harness.json"
    checks.append(("harness.json", "PASS" if harness.exists() else "WARN", str(harness)))

    print(f"audit {run}")
    print(f"{'check':<24} {'status':<6} detail")
    fails = warns = 0
    for name, status, detail in checks:
        print(f"{name:<24} {status:<6} {detail}")
        fails += status == "FAIL"
        warns += status == "WARN"

    if events:
        print("\nlast events:")
        for e in events[-5:]:
            print(f"  {e.get('ts','')} {e.get('action',''):<8} {e.get('result',''):<5} {e.get('target','')}")

    return 1 if fails else 0


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

    p = sub.add_parser("new-run", help="create runs/<name>/{shots,logs,artifacts}")
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
    p.set_defaults(func=cmd_report)

    p = sub.add_parser("audit", help="cross-check events, report and evidence")
    p.add_argument("run_dir")
    p.set_defaults(func=cmd_audit)

    a = ap.parse_args()
    if a.cmd == "launch" and not a.command:
        ap.error("launch needs a command")

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
