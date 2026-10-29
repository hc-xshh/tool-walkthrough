#!/usr/bin/env python3
"""Cross-platform walkthrough harness.

One entry point for the operations that differ by OS:

  python3 harness/wt.py --run runs/2026-10-19-tool preflight
  python3 harness/wt.py new-run 2026-10-19-tool
  python3 harness/wt.py --run runs/2026-10-19-tool shot out.png
  python3 harness/wt.py --run runs/2026-10-19-tool click 300 241 --shot out.png
  python3 harness/wt.py --run runs/2026-10-19-tool ocr out.png
  python3 harness/wt.py --run runs/2026-10-19-tool agent --goal "完成一次走查" --backend cdp --port 9339
  python3 harness/wt.py --run runs/2026-10-19-tool launch --log app.log -- /path/to/app
  python3 harness/wt.py report runs/2026-10-19-tool
  python3 harness/wt.py audit --strict runs/2026-10-19-tool
  python3 harness/wt.py coverage runs/2026-10-19-tool
  python3 harness/wt.py evidence --strict runs/2026-10-19-tool

Linux uses X11 tooling (ffmpeg/xdotool). Only the real desktop :0 is
supported; :98/:99/Xvfb are rejected. macOS uses screencapture and
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
import csv
import json
import os
import platform
import shutil
import struct
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

from wtlib import *  # noqa: F401,F403  (ROOT, OS, WT_VERSION, helpers)
from wtlib import profile, resolve_run, log_event
import wtshot
from wtshot import enable_dpi_awareness, read_shot_meta
from wtcheck import cmd_audit, cmd_coverage


def launch_env(base=None):
    """Environment for a launched GUI app.

    Electron reads ELECTRON_RUN_AS_NODE. When an agent host exports it, the app
    starts as plain Node: no window, exit 9, and `--version` prints a Node
    version. Strip it for the child instead of asking the user to relaunch.
    Returns (env, stripped) so the caller can say what it changed.
    """
    env = dict(os.environ if base is None else base)
    stripped = env.pop("ELECTRON_RUN_AS_NODE", None) is not None
    return env, stripped



def require_real_display(disp):
    """Reject virtual displays and prove the Linux session is a real desktop."""
    value = str(disp or ":0").strip()
    if value.split(".")[0] != ":0":
        raise SystemExit(
            f"virtual displays are disabled ({value}); use the real desktop DISPLAY=:0"
        )
    verify_real_session(value)
    return value


def cmd_preflight(a):
    prof = profile(a)
    if OS == "Linux":
        require_real_display(
            a.display or prof.get("display") or os.environ.get("WALKTHROUGH_DISPLAY", ":0")
        )
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
    if os.environ.get("ELECTRON_RUN_AS_NODE"):
        say(
            "electron env",
            False,
            "ELECTRON_RUN_AS_NODE is set; Electron apps would start as Node "
            "(no window, exit 9). launch strips it for the child.",
            warn_only=True,
        )

    if OS == "Linux":
        for b in ("ffmpeg", "xdotool", "xdpyinfo"):
            p = which_any([b])
            say(b, bool(p), p or "missing (Linux desktop walkthroughs)", warn_only=True)
        disp = a.display or prof.get("display") or os.environ.get("WALKTHROUGH_DISPLAY", ":0")
        xdpy = which_any(["xdpyinfo"])
        check_env = dict(os.environ)
        auth_hint = ""
        if OS == "Linux" and disp == ":0" and not check_env.get("XAUTHORITY"):
            # An agent shell often has no DISPLAY/XAUTHORITY even when the GNOME
            # session is running. Try the current user's Xwayland auth file for
            # the check; tell the user the exact export instead of guessing.
            auths = sorted(Path(f"/run/user/{os.getuid()}").glob(".mutter-Xwaylandauth.*"))
            if auths:
                check_env["XAUTHORITY"] = str(auths[0])
                auth_hint = f"export DISPLAY=:0 XAUTHORITY={auths[0]}"
        ok = bool(xdpy) and subprocess.run(
            [xdpy, "-display", disp], capture_output=True, text=True, env=check_env
        ).returncode == 0
        if ok:
            detail = "ok; " + auth_hint if auth_hint else "ok"
        elif disp == ":0":
            detail = auth_hint or "run inside the desktop session, or set DISPLAY/XAUTHORITY"
        else:
            detail = "start a real desktop session, or export DISPLAY/XAUTHORITY"
        rc |= say(f"display {disp}", ok, detail)
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
    llm_key = bool((os.environ.get("WT_LLM_API_KEY") or "").strip())
    llm_model = os.environ.get("WT_LLM_MODEL") or "default"
    print(f"{'llm key':<24} {'INFO':<5} " + (
        f"set; model={llm_model}" if llm_key else
        "not set; `wt.py agent` will refuse until WT_LLM_API_KEY is exported"
    ))
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
    disp = require_real_display(
        a.display or prof.get("display") or os.environ.get("WALKTHROUGH_DISPLAY", ":0")
    )
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
    # 就在这个开关下改用 cdp.py；本项目不提供虚拟桌面路径。
    if getattr(a, "no_native_input", False) or os.environ.get("WALKTHROUGH_NO_NATIVE_INPUT") == "1":
        print(
            "native click disabled: it would move the physical pointer. "
            "Use `python3 harness/cdp.py clickel \"<label>\"` (DOM/mouse events inside the app) "
            "or use a separate user/VM for native dialogs.",
            file=sys.stderr,
        )
        raise SystemExit(2)

    prof = profile(a)
    disp = require_real_display(
        a.display or prof.get("display") or os.environ.get("WALKTHROUGH_DISPLAY", ":0")
    )
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




PNG_MAGIC = bytes.fromhex("89504e470d0a1a0a")


def png_size(path):
    """Return (width, height) from a PNG or JPEG header, or (0, 0) if neither.

    `evidence` globs jpg/jpeg as well, so decoding only PNG silently marked
    every JPEG screenshot as `not-image` and failed `--strict`.
    """
    try:
        with open(path, "rb") as f:
            head = f.read(24)
            if len(head) >= 24 and head[:8] == PNG_MAGIC:
                return struct.unpack(">II", head[16:24])
            if head[:2] != b"\xff\xd8":
                return 0, 0
            f.seek(2)
            while True:
                b = f.read(1)
                while b and b != b"\xff":
                    b = f.read(1)
                while b == b"\xff":
                    b = f.read(1)
                if not b:
                    return 0, 0
                marker = b[0]
                if marker == 0x01 or marker == 0xD8 or 0xD0 <= marker <= 0xD7:
                    continue
                seg = f.read(2)
                if len(seg) < 2:
                    return 0, 0
                length = struct.unpack(">H", seg)[0]
                if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
                              0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                    data = f.read(5)
                    if len(data) < 5:
                        return 0, 0
                    height, width = struct.unpack(">HH", data[1:5])
                    return width, height
                f.seek(max(length - 2, 0), 1)
    except OSError:
        pass
    return 0, 0


def _evidence_meta(root):
    meta = {}
    candidates = [root / "evidence.json", root / "shots" / "captions.json"]
    if root.name in ("shots", "screens"):
        candidates.append(root.parent / "evidence.json")
        # --shots <run>/shots 时 captions.json 就在这一层，别去找 shots/shots/
        candidates.append(root / "captions.json")
    for p in candidates:
        if not p.exists():
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError) as exc:
            print(f"WARN: cannot read {p}: {exc}")
            continue
        for key, value in (data or {}).items():
            meta[str(key).replace("\\", "/")] = value if isinstance(value, dict) else {"caption": str(value)}
    return meta


def _evidence_type(meta, path, root):
    rel = ""
    if path.is_relative_to(root):
        rel = str(path.relative_to(root)).replace("\\", "/")
    for key in (path.name, rel, f"shots/{path.name}", f"screens/{path.name}"):
        if key and key in meta:
            v = meta[key]
            return v.get("type") or "未标注", v.get("caption") or ""
    return "未标注", ""


def _evidence_status(w, h, typ, min_w, min_h):
    if not w or not h:
        return "not-image"
    bits = []
    if w < min_w or h < min_h:
        bits.append("low-res")
    if typ == "未标注":
        bits.append("unlabeled")
    return "+".join(bits) if bits else "ok"


def cmd_evidence(a):
    if a.cells:
        root = Path(a.cells).expanduser().resolve().parent
    elif a.shots:
        root = Path(a.shots).expanduser().resolve()
    elif getattr(a, "run_dir", None):
        # 文档写的是 `wt.py evidence --strict runs/<run>`；位置参数一直没被读，
        # 只有 WALKTHROUGH_RUN 生效，显式路径会被忽略。
        root = Path(a.run_dir).expanduser().resolve()
    else:
        root = resolve_run(a)
    if not root:
        raise SystemExit("evidence needs a run dir, --shots or --cells")
    rows = []
    meta = {} if a.cells else _evidence_meta(root)

    if a.cells:
        cells = Path(a.cells).expanduser().resolve()
        with cells.open(encoding="utf-8-sig", newline="") as f:
            for rec in csv.DictReader(f):
                item = (rec.get("item") or "").strip()
                tool = (rec.get("tool") or "").strip()
                raw = (rec.get("file") or "").strip()
                typ = (rec.get("type") or "").strip() or "无独立截图"
                caption = (rec.get("caption") or "").strip()
                if not raw:
                    rows.append({"item": item, "tool": tool, "file": "", "width": 0,
                                 "height": 0, "type": "无独立截图", "caption": caption,
                                 "status": "no-shot"})
                    continue
                path = Path(raw)
                if not path.is_absolute():
                    direct = path.resolve()
                    path = direct if direct.exists() else (cells.parent / path).resolve()
                w, h = png_size(path)
                rows.append({"item": item, "tool": tool, "file": str(path), "width": w,
                             "height": h, "type": typ, "caption": caption,
                             "status": _evidence_status(w, h, typ, a.min_width, a.min_height)})
    else:
        paths = set()
        subdirs = [root / "shots", root / "screens"]
        bases = [p for p in subdirs if p.exists()] or [root]
        for base in bases:
            for ext in ("*.png", "*.jpg", "*.jpeg"):
                paths.update(base.glob(ext))
        for path in sorted(paths):
            w, h = png_size(path)
            typ, caption = _evidence_type(meta, path, root)
            rows.append({"item": "", "tool": "", "file": str(path), "width": w,
                         "height": h, "type": typ, "caption": caption,
                         "status": _evidence_status(w, h, typ, a.min_width, a.min_height)})

    print(f"{'file':60} {'size':>10}  {'type':16} status")
    bad = 0
    for r in rows:
        name = Path(r["file"]).name if r["file"] else "(no screenshot)"
        print(f"{name:60} {r['width']:>4}x{r['height']:<4} {r['type']:16} {r['status']}")
        if r["status"] not in ("ok", "no-shot"):
            bad += 1
    print(f"{len(rows)} rows, {bad} need attention, min {a.min_width}x{a.min_height}")

    if a.out:
        out = Path(a.out).expanduser().resolve()
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["item", "tool", "file", "width", "height",
                                              "type", "caption", "status"])
            w.writeheader()
            w.writerows(rows)
        print(f"wrote {out}")

    return 1 if (a.strict and bad) else 0


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
    env, stripped = launch_env()
    cmd = list(a.command)
    if cmd and cmd[0] == "--":
        cmd = cmd[1:]
    if not cmd and OS != "Darwin":
        # --app only means "open -a <app>", which exists on macOS alone
        raise SystemExit(f"launch needs a command on {OS} (--app is macOS-only)")
    # Headless commands would bypass the real-window gate and produce a
    # different UI from the one users see. Refuse them before spawning.
    for token in cmd:
        low = str(token).lower()
        if low == "--headless" or low.startswith("--headless=") \
                or low == "--ozone-platform=headless" \
                or low.startswith("--virtual-time-budget"):
            raise SystemExit(
                f"refusing headless launch argument {token!r}; "
                "the walkthrough must use the real desktop window"
            )
    if OS == "Linux":
        # Launch into the user's real session. Do not replace HOME, DBus or
        # the runtime dir: login state, keyring, notifications and native
        # dialogs are part of what an experience walkthrough is judging.
        env.update(
            DISPLAY=require_real_display(
                a.display or prof.get("display") or os.environ.get("WALKTHROUGH_DISPLAY", ":0")
            ),
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
    if stripped:
        print("stripped ELECTRON_RUN_AS_NODE for the child (Electron would otherwise run as Node)")
    return {"target": " ".join(cmd), "detail": f"pid={p.pid} log={log}"}




def cmd_focus(a):
    """Bring a running app's window to the foreground.

    Chromium throttles occluded windows: CDP still answers `text`, but
    Page.captureScreenshot can hang until the window is visible again.
    """
    name = a.name
    if OS == "Windows":
        ps = which_any(["powershell", "pwsh"])
        if not ps:
            raise SystemExit("focus needs PowerShell on Windows")
        helper = ROOT / "harness" / "focus.ps1"
        p = subprocess.run(
            [ps, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(helper), name],
            capture_output=True, text=True,
        )
        if p.returncode != 0:
            raise SystemExit(f"no visible window for {name!r}")
        print(p.stdout.strip())
        return {"target": name, "detail": p.stdout.strip()}
    if OS == "Darwin":
        subprocess.run(["osascript", "-e", f'tell application "{name}" to activate'], check=False)
        return {"target": name, "detail": "activated"}
    xdo = which_any(["xdotool"])
    if not xdo:
        raise SystemExit("focus needs xdotool on Linux")
    p = subprocess.run([xdo, "search", "--name", name], capture_output=True, text=True)
    ids = [x for x in p.stdout.split() if x]
    if not ids:
        raise SystemExit(f"no window matching {name!r}")
    subprocess.run([xdo, "windowactivate", "--sync", ids[-1]], check=False)
    print(f"activated {ids[-1]}")
    return {"target": name, "detail": f"window {ids[-1]}"}


def cmd_agent(a):
    """Run the LLM operator against a CDP or desktop backend."""
    from dataclasses import replace

    from llm_client import ChatClient, LLMConfig, LLMError
    from llm_operator import Operator, OperatorError, make_backend

    run = resolve_run(a)
    if run is None:
        stamp = datetime.now().strftime("%Y-%m-%d-%H%M%S")
        run = ROOT / "runs" / f"{stamp}-agent"
    try:
        cfg = LLMConfig.from_env()
        if getattr(a, "model", None):
            cfg = replace(cfg, model=a.model)
        if getattr(a, "display", None):
            require_real_display(a.display)
        # Keep the selected profile's real display. Virtual displays are not
        # a supported evaluation environment in this project.
        if a.backend == "desktop":
            a.display = require_real_display(a.display or profile(a).get("display"))
        backend = make_backend(
            a.backend,
            port=a.port,
            match=a.match,
            kind=a.kind,
            nested=a.nested,
            display=a.display,
            geometry=a.geometry,
            ocr=a.ocr,
        )
        operator = Operator(
            ChatClient(cfg), backend, run, a.goal,
            max_steps=a.max_steps,
            max_seconds=a.max_seconds,
            max_total_tokens=a.max_total_tokens,
            dry_run=a.dry_run,
        )
        result = operator.run_loop()
    except (LLMError, OperatorError) as exc:
        raise SystemExit(f"agent: {exc}") from None
    except Exception as exc:
        raise SystemExit(f"agent: {type(exc).__name__}: {exc}") from None
    print(f"agent run: {run}")
    print(f"status: {result.status}  steps: {result.steps}  findings: {len(result.findings)}")
    print(f"summary: {run / 'agent-summary.md'}")
    print(f"data:    {run / 'findings.json'}")
    return {
        "target": str(run),
        "status": result.status,
        "detail": f"{result.steps} steps, {len(result.findings)} findings",
        "_rc": 0 if result.status in ("done", "blocked") else 1,
    }


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
    p.add_argument("--log", default=os.path.join(tempfile.gettempdir(), "walkthrough", "app.log"))
    p.add_argument("--display", default=None)
    p.set_defaults(func=cmd_launch)

    p = sub.add_parser("focus", help="bring a running app's window to the foreground")
    p.add_argument("name", help="process name substring (Windows) or window title (Linux/macOS)")
    p.set_defaults(func=cmd_focus)

    p = sub.add_parser("agent", help="let an LLM operate the product (CDP or Linux desktop)")
    p.add_argument("--goal", required=True, help="what the walkthrough should accomplish")
    p.add_argument("--max-steps", type=int, default=20)
    p.add_argument("--max-seconds", type=float, default=600)
    p.add_argument("--max-total-tokens", type=int, default=200000)
    p.add_argument("--backend", choices=["cdp", "desktop"], default="cdp")
    p.add_argument("--port", type=int, default=9339)
    p.add_argument("--match", default=None, help="CDP page URL substring")
    p.add_argument("--kind", choices=["page", "iframe", "any"], default="page")
    p.add_argument("--nested", action="store_true", help="evaluate inside the first inner iframe")
    p.add_argument("--display", default=None)
    p.add_argument("--geometry", default=None)
    p.add_argument("--ocr", action="store_true", help="desktop: include tesseract text")
    p.add_argument("--dry-run", action="store_true", help="observe and plan, but do not act")
    p.add_argument("--model", default=None, help="override WT_LLM_MODEL")
    p.set_defaults(func=cmd_agent)

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

    p = sub.add_parser("evidence", help="check screenshot size, evidence type and no-shot cells")
    p.add_argument("run_dir", nargs="?", default=None)
    p.add_argument("--shots", default=None, help="check a shots/ directory instead of a run")
    p.add_argument("--cells", default=None,
                   help="CSV item,tool,file,type,caption; empty file => 无独立截图")
    p.add_argument("--out", default=None, help="write the audit CSV here")
    p.add_argument("--min-width", type=int, default=800)
    p.add_argument("--min-height", type=int, default=400)
    p.add_argument("--strict", action="store_true", help="exit non-zero on low-res/unlabeled/not-image")
    p.set_defaults(func=cmd_evidence)

    a = ap.parse_args()
    if a.cmd == "launch" and not a.command and not a.app:
        ap.error("launch needs a command, or --app on macOS")

    run = resolve_run(a)
    started = time.monotonic()
    try:
        result = a.func(a)
        if isinstance(result, dict):
            extra = {k: v for k, v in result.items() if not k.startswith("_")}
            rc = int(result.get("_rc", 0))
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
