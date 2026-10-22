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

Linux uses X11 tooling (ffmpeg/xdotool). macOS uses screencapture and
cliclick (or AppleScript). Windows uses PowerShell/.NET and ctypes.
CDP stays in cdp.py and works on all three.

`shot` also writes `<png>.json` next to the image, recording where pixel (0,0)
sits (origin) and the pixels-per-click-unit ratio (scale). OCR returns pixel
coordinates inside the image, so pass `click --shot <png>` to land the click
where the word actually is: multi-monitor Windows and Retina macOS otherwise
click the wrong spot.

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
WT_VERSION = "1.3.0"
PROFILES_DIR = ROOT / "harness" / "profiles"
LOCK_FILE = ROOT / "harness" / "harness.lock"


def which_any(names):
    for n in names:
        p = shutil.which(n)
        if p:
            return p
    return None


def enable_dpi_awareness():
    """Make this process DPI-aware so screenshot pixels and click coords agree.

    Windows only. A non-aware process gets its coordinates virtualised by the
    shell, so a click lands off-target on any display scaled above 100%.
    """
    if OS != "Windows":
        return None
    import ctypes

    try:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.SetProcessDpiAwarenessContext.argtypes = [ctypes.c_void_p]
        user32.SetProcessDpiAwarenessContext.restype = ctypes.c_bool
        if user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)):  # per-monitor v2
            return "per-monitor-v2"
    except Exception:
        pass
    try:
        shcore = ctypes.WinDLL("shcore")
        shcore.SetProcessDpiAwareness.argtypes = [ctypes.c_int]
        shcore.SetProcessDpiAwareness.restype = ctypes.c_int
        if shcore.SetProcessDpiAwareness(2) == 0:  # per-monitor
            return "per-monitor"
    except Exception:
        pass
    try:
        if ctypes.windll.user32.SetProcessDPIAware():
            return "system"
    except Exception:
        pass
    return None


def _x11_size(display):
    """Screen size in pixels, straight from the X server."""
    p = which_any(["xdpyinfo"])
    if not p:
        return (0, 0)
    try:
        out = subprocess.run([p, "-display", display], capture_output=True, text=True, timeout=15)
        m = re.search(r"dimensions:\s+(\d+)x(\d+)", out.stdout or "")
        return (int(m.group(1)), int(m.group(2))) if m else (0, 0)
    except Exception:
        return (0, 0)


def _png_size(png):
    """Read width/height out of a PNG header without extra dependencies."""
    try:
        with open(png, "rb") as fh:
            head = fh.read(24)
        if head[:8] != b"\x89PNG\r\n\x1a\n":
            return (0, 0)
        return (int.from_bytes(head[16:20], "big"), int.from_bytes(head[20:24], "big"))
    except Exception:
        return (0, 0)


def _macos_logical_size():
    """Desktop size in points (Finder reports the same units clicks use)."""
    try:
        p = subprocess.run(
            ["osascript", "-e", 'tell application "Finder" to get bounds of window of desktop'],
            capture_output=True, text=True, timeout=15,
        )
        nums = [int(x) for x in re.findall(r"-?\d+", p.stdout or "")]
        if len(nums) >= 4:
            return (nums[2] - nums[0], nums[3] - nums[1])
    except Exception:
        pass
    return (0, 0)


def desktop_metrics(png=None):
    """Map screenshot pixels onto click coordinates.

    `origin` is where pixel (0,0) of the capture sits in the coordinate space
    the click API uses; `scale` is capture pixels per click unit. Windows grabs
    the whole virtual desktop (negative origins with a left-hand secondary
    monitor); macOS captures physical pixels while clicks use points (Retina).
    """
    if OS == "Windows":
        enable_dpi_awareness()
        import ctypes

        g = ctypes.windll.user32.GetSystemMetrics
        return {
            "origin_x": g(76), "origin_y": g(77),  # SM_XVIRTUALSCREEN / SM_YVIRTUALSCREEN
            "width": g(78), "height": g(79),
            "scale": 1.0,
            "source": "GetSystemMetrics(virtual screen)",
        }
    if OS == "Darwin":
        lw, lh = _macos_logical_size()
        pw, ph = _png_size(png) if png else (0, 0)
        scale = round(pw / lw, 3) if lw and pw else 1.0
        return {
            "origin_x": 0, "origin_y": 0,
            "width": pw or lw, "height": ph or lh,
            "scale": scale,
            "source": "screencapture + Finder bounds",
        }
    w, h = _png_size(png) if png else (0, 0)
    return {"origin_x": 0, "origin_y": 0, "width": w, "height": h, "scale": 1.0, "source": "x11"}


def shot_meta_path(png):
    return Path(str(png) + ".json")


def read_shot_meta(png):
    path = shot_meta_path(png)
    if not path.exists():
        return None
    try:
        # utf-8-sig: hand-edited sidecars (e.g. PowerShell) often carry a BOM
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
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


def tesseract_langs():
    """Installed language packs, e.g. ['chi_sim', 'eng', 'osd']."""
    p = which_any(["tesseract"])
    if not p:
        return []
    try:
        out = subprocess.run([p, "--list-langs"], capture_output=True, text=True, timeout=10)
        lines = (out.stdout or "").splitlines()[1:]  # first line is the banner
        return [ln.strip() for ln in lines if re.fullmatch(r"[a-z0-9_]+", ln.strip() or "")]
    except Exception:
        return []


def module_available(name):
    try:
        __import__(name)
        return True
    except Exception:
        return False


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
    # utf-8-sig: a BOM would make the first line unparsable and silently drop
    # every event, which is exactly the kind of false PASS audit exists to stop
    for line in path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return events


def write_harness_json(run, prof):
    path = run / "harness.json"
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
    if path.exists():
        # Keep hand-edited extras (e.g. "raters") and the original timestamp,
        # but refresh the machine facts: re-running new-run with another
        # --profile must not leave a stale profile behind.
        try:
            old = json.loads(path.read_text(encoding="utf-8-sig"))
        except Exception:
            old = {}
        if isinstance(old, dict):
            data["created"] = old.get("created", data["created"])
            for key, value in old.items():
                data.setdefault(key, value)
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
    for sub in ("shots", "logs", "trace", "artifacts"):
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
    write_harness_json(run, profile(a))
    print(run)
    for rel in copied:
        print(f"scaffolded {rel}")
    print(f"scaffolded logs/{trace_log.name}")
    print("runs/ is git-ignored. Do not 'git add -f' this directory.")
    return {"target": str(run), "detail": f"{len(copied)} templates + trace log"}


class _ShotArgs:
    """Minimal namespace so click can reuse cmd_shot's capture path."""

    display = None
    geometry = None
    profile = None

    def __init__(self, out):
        self.out = str(out)


def cmd_shot(a):
    prof = profile(a)
    out = Path(a.out).expanduser().resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    disp = a.display or prof.get("display") or os.environ.get("WALKTHROUGH_DISPLAY", ":98")
    geom = a.geometry or prof.get("geometry") or ""

    if OS == "Linux":
        if not geom or geom == "screen":
            w, h = _x11_size(disp)
            geom = f"{w}x{h}" if w and h else "1440x900"
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
# Be DPI-aware before measuring, otherwise SystemInformation reports a
# virtualised (logical) size while CopyFromScreen grabs physical pixels.
$sig = @"
using System;
using System.Runtime.InteropServices;
public class WtDpi {
  [DllImport("user32.dll")] public static extern bool SetProcessDpiAwarenessContext(IntPtr v);
  [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
}
"@
try { Add-Type -TypeDefinition $sig -ErrorAction Stop } catch {}
try { [WtDpi]::SetProcessDpiAwarenessContext([IntPtr](-4)) | Out-Null }
catch { try { [WtDpi]::SetProcessDPIAware() | Out-Null } catch {} }
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

    meta = desktop_metrics(out)
    pw, ph = _png_size(out)
    meta["width"] = meta.get("width") or pw
    meta["height"] = meta.get("height") or ph
    meta["screenshot"] = str(out)
    shot_meta_path(out).write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
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


def cmd_click(a):
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


def read_ui_map(run):
    """Parse ui-map.md: rows with a U-id, their covered task ids and notes."""
    path = run / "ui-map.md"
    if not path.exists():
        return None
    controls = []
    header = None
    screen = "（未命名界面）"
    text = path.read_text(encoding="utf-8", errors="replace")
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)  # ignore template examples
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("## "):
            screen = line[3:].strip()
            header = None
            continue
        if not line.startswith("|"):
            header = None if not line else header
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if header is None:
            if any(c.upper() == "ID" for c in cells):
                header = {c: i for i, c in enumerate(cells)}
            continue
        if all(set(c) <= set("-: ") for c in cells):
            continue  # separator row
        uid = cells[header.get("ID", 0)] if cells else ""
        if not re.fullmatch(r"U\d+", uid):
            continue
        cover_idx = header.get("覆盖任务")
        note_idx = header.get("备注")
        covers = cells[cover_idx] if cover_idx is not None and cover_idx < len(cells) else ""
        note = cells[note_idx] if note_idx is not None and note_idx < len(cells) else ""
        task_ids = re.findall(r"T\d+", covers)
        controls.append({"id": uid, "screen": screen, "covers": task_ids, "note": note.strip()})
    return controls


def ui_coverage(run):
    """(total, covered, skipped-with-reason, uncovered, dangling task refs)."""
    controls = read_ui_map(run)
    if controls is None:
        return None
    plan = run / "task-plan.md"
    known = set(re.findall(r"T\d+", plan.read_text(encoding="utf-8", errors="replace"))) if plan.exists() else set()
    covered = [c for c in controls if c["covers"]]
    skipped = [c for c in controls if not c["covers"] and c["note"]]
    uncovered = [c for c in controls if not c["covers"] and not c["note"]]
    dangling = sorted({t for c in controls for t in c["covers"] if known and t not in known})
    screens = {}
    for c in controls:
        screens.setdefault(c["screen"], []).append(c)
    return {
        "controls": controls,
        "total": len(controls),
        "covered": len(covered),
        "skipped": len(skipped),
        "uncovered": uncovered,
        "dangling": dangling,
        "tasks_known": len(known),
        "screens": screens,
        "screen_count": len(screens),
    }


def cmd_coverage(a):
    run = Path(a.run_dir).expanduser().resolve()
    cov = ui_coverage(run)
    if cov is None:
        print(f"no {run / 'ui-map.md'} — build the page map first (METHOD Step 1)")
        return 1 if getattr(a, "strict", False) else 0
    print(f"coverage {run}")
    print(f"  screens    {cov['screen_count']}")
    print(f"  controls   {cov['total']}")
    print(f"  covered    {cov['covered']}")
    print(f"  skipped    {cov['skipped']}  (has a reason in 备注)")
    print(f"  uncovered  {len(cov['uncovered'])}")
    for name, items in cov["screens"].items():
        mine = sum(1 for c in items if c["covers"])
        print(f"  - {name}: {len(items)} controls, {mine} covered")
    if cov["dangling"]:
        print(f"  unknown task ids: {', '.join(cov['dangling'])}")
    for c in cov["uncovered"]:
        print(f"  - {c['id']} has no task and no reason")
    if getattr(a, "strict", False) and (cov["uncovered"] or cov["dangling"]):
        return 1
    return 0


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

    SHOT_ACTIONS = {"shot", "cdp:shot"}
    CLICK_ACTIONS = {"click", "cdp:click", "cdp:clicktext", "cdp:clickel", "cdp:clickxy"}

    shot_events = [e for e in events if e.get("action") in SHOT_ACTIONS and e.get("result") != "error"]
    # clicks and other actions can carry a screenshot too (`click` captures by
    # default); those are evidence as well and must point at real files
    carried = [
        e for e in events
        if str(e.get("screenshot") or "").strip() and e.get("result") != "error"
    ]
    bad_shots = []
    for e in carried:
        p = Path(str(e["screenshot"]))
        if not p.is_absolute():
            candidates = [run / p, run.parent / p, Path.cwd() / p]
            p = next((c for c in candidates if c.exists()), p)
        if not p.exists():
            bad_shots.append(str(p))
    unattributed = sum(1 for e in shot_events if not str(e.get("screenshot") or "").strip())
    if not shot_events and not carried:
        shot_status = "FAIL"
    elif bad_shots:
        shot_status = "FAIL"
    elif unattributed:
        shot_status = "WARN"
    else:
        shot_status = "PASS"
    checks.append((
        "shot files",
        shot_status,
        f"{len(shot_events)} shots, {len(carried)} screenshots, "
        f"{len(bad_shots)} missing, {unattributed} without a path",
    ))

    errors = [e for e in events if e.get("result") == "error"]
    checks.append((
        "error events",
        "PASS" if not errors else "WARN",
        f"{len(errors)} (last: {errors[-1].get('action') if errors else '-'})",
    ))

    def evidence_ok(ev):
        raw = str(ev.get("screenshot") or "").strip()
        if not raw:
            return False
        p = Path(raw)
        if not p.is_absolute():
            p = next((c for c in (run / p, run.parent / p, Path.cwd() / p) if c.exists()), p)
        return p.exists()

    gaps = 0
    for i, e in enumerate(events):
        if e.get("action") in CLICK_ACTIONS:
            # `wt.py click` / `cdp.py --capture` now shoot at click time, so a
            # click carrying a real screenshot is already paired.
            if evidence_ok(e):
                continue
            if any(x.get("action") in SHOT_ACTIONS or evidence_ok(x) for x in events[i + 1:i + 6]):
                continue
            gaps += 1
    checks.append((
        "click -> shot",
        "PASS" if gaps == 0 else "WARN",
        f"{gaps} clicks without a later shot",
    ))

    harness = run / "harness.json"
    checks.append(("harness.json", "PASS" if harness.exists() else "WARN", str(harness)))

    cov = ui_coverage(run)
    if cov is None:
        checks.append(("ui coverage", "WARN", f"no {run.name}/ui-map.md (METHOD Step 1)"))
    elif not cov["total"]:
        checks.append(("ui coverage", "WARN", "ui-map.md has no control rows yet"))
    elif cov["uncovered"]:
        checks.append((
            "ui coverage",
            "WARN",
            f"{cov['screen_count']} screens, {cov['total']} controls, "
            f"{len(cov['uncovered'])} without a task or reason",
        ))
    else:
        checks.append((
            "ui coverage",
            "PASS",
            f"{cov['screen_count']} screens, {cov['total']} controls, "
            f"{cov['covered']} covered, {cov['skipped']} skipped with reason",
        ))

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

    if fails or (getattr(a, "strict", False) and warns):
        return 1
    return 0


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
