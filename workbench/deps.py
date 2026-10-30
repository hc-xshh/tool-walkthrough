#!/usr/bin/env python3
"""Optional dependencies for the workbench, kept out of the system Python.

`cdp.py` needs websocket-client; Debian/Ubuntu often refuse `pip install`
system-wide (PEP 668) and this box has no `ensurepip` for a venv. So the
workbench installs the harness requirements into `workbench/.deps/` and puts
that directory on `sys.path` at startup.

Nothing is installed unless the user asks for it (Settings → 安装依赖).
"""
from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
REQUIREMENTS = ROOT / "harness" / "requirements.txt"
OFFICE_REQUIREMENTS = ROOT / "office-eval" / "requirements.txt"

# import name -> what the run needs it for
REQUIRED = {
    "websocket": "CDP 驱动（Qoder / Cursor / TRAE）和走查的 CDP 后端",
    "requests": "CDP 的 /json/list 探测",
}


def deps_dir() -> Path:
    override = os.environ.get("WT_DEPS_DIR")
    if override:
        return Path(override).expanduser()
    return HERE / ".deps"


def ensure() -> bool:
    """Put an existing .deps directory on sys.path. Returns True if it exists."""
    path = deps_dir()
    if not path.is_dir():
        return False
    entry = str(path)
    if entry not in sys.path:
        sys.path.insert(0, entry)
        importlib.invalidate_caches()
    return True


def annotate(env: dict) -> dict:
    """Make .deps visible to child processes (run_tool → driver → cdp.py)."""
    path = deps_dir()
    if not path.is_dir():
        return env
    entry = str(path)
    parts = [entry] + [p for p in (env.get("PYTHONPATH") or "").split(os.pathsep)
                       if p and p != entry]
    env["PYTHONPATH"] = os.pathsep.join(parts)
    return env


def missing() -> dict[str, str]:
    """Import names that are still missing, with the reason they matter."""
    ensure()
    return {name: why for name, why in REQUIRED.items()
            if importlib.util.find_spec(name) is None}


def install(timeout: int = 300) -> tuple[bool, str]:
    """Install harness/requirements.txt into .deps. Network access needed."""
    path = deps_dir()
    path.mkdir(parents=True, exist_ok=True)
    reqs = [REQUIREMENTS]
    if OFFICE_REQUIREMENTS.is_file():
        reqs.append(OFFICE_REQUIREMENTS)  # openpyxl: unit tests and office-eval
    cmd = [sys.executable, "-m", "pip", "install", "--disable-pip-version-check",
           "--target", str(path)]
    for req in reqs:
        cmd += ["-r", str(req)]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=timeout)
    except subprocess.TimeoutExpired:
        return False, f"pip install timed out after {timeout}s"
    except OSError as exc:
        return False, f"cannot run pip: {exc}"
    log = ((p.stdout or "") + (p.stderr or "")).strip()
    ensure()
    ok = p.returncode == 0 and not missing()
    return ok, log[-2000:]
