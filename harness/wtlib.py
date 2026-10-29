#!/usr/bin/env python3
"""Shared primitives: paths, profiles, run resolution, events, harness.json."""
from __future__ import annotations

import json
import os
import platform
import re
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OS = platform.system()  # Linux / Darwin / Windows
WT_VERSION = "1.9.0"
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


def find_git():
    """git binary: PATH first, then the usual install locations.

    Windows installers put C:\\Program Files\\Git\\cmd on the *machine* PATH, but a
    long-running parent process keeps its own stale copy of the environment; a
    freshly installed git then looks missing until the app restarts. Resolving
    the install path directly keeps `preflight` honest.
    """
    env = os.environ.get("WALKTHROUGH_GIT")
    if env and Path(env).exists():
        return env
    found = which_any(["git"])
    if found:
        return found
    if OS == "Windows":
        candidates = [
            r"C:\Program Files\Git\cmd\git.exe",
            r"C:\Program Files (x86)\Git\cmd\git.exe",
        ]
        base = os.environ.get("LocalAppData")
        if base:
            candidates.append(str(Path(base) / "Programs" / "Git" / "cmd" / "git.exe"))
    else:
        candidates = ["/usr/bin/git", "/usr/local/bin/git", "/opt/homebrew/bin/git"]
    for p in candidates:
        if Path(p).exists():
            return p
    return None


def git_version(binary=None):
    p = binary or find_git()
    if not p:
        return None
    try:
        out = subprocess.run([p, "--version"], capture_output=True, text=True, timeout=5)
        return version_tuple(out.stdout or out.stderr)
    except Exception:
        return None




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


