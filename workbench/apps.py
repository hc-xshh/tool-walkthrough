#!/usr/bin/env python3
"""Launch (or restart) a GUI app with its DevTools port, and open a folder in it.

The workbench is allowed to start Qoder/Cursor/TRAE because the alternative is
asking the user to remember a flag and a path. Two rules keep it safe:

  * restarting a running IDE is explicit (`restart=True`) and refuses to
    SIGKILL: if the app asks to save, it stays alive and we report that;
  * opening a folder is limited to a path the caller already validated.
"""
from __future__ import annotations

import os
import shutil
import signal
import subprocess
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
LOG_DIR = ROOT / "runs" / "workbench" / "apps"

APPS: dict[str, dict] = {
    "qoder": {
        "label": "Qoder CN",
        "exe": os.environ.get("WT_QODER_EXE", "/usr/share/qoder-cn-ide/qoder-cn-ide"),
        "open": ["/usr/share/qoder-cn-ide/bin/qoder-cn", "-n"],
        "port": 9444,
    },
    "cursor": {
        "label": "Cursor",
        "exe": os.environ.get("WT_CURSOR_EXE", ""),
        "open": [],
        "port": 9562,
    },
    "trae": {
        "label": "TRAE CN",
        "exe": os.environ.get("WT_TRAE_EXE", ""),
        "open": [],
        "port": 9339,
    },
}


def _resolve(app: dict) -> str:
    exe = app.get("exe") or ""
    if exe and Path(exe).exists():
        return exe
    return shutil.which(app.get("label", "")) or ""


def _processes(exe: str) -> list[tuple[int, str]]:
    """Main processes only: Electron helper processes carry --type=."""
    if not exe:
        return []
    try:
        out = subprocess.run(["ps", "-eo", "pid=,args="], capture_output=True,
                             text=True, encoding="utf-8", errors="replace", timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    found = []
    for line in (out or "").splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) != 2:
            continue
        pid, args = parts
        if exe in args and "--type=" not in args and pid.isdigit():
            found.append((int(pid), args))
    return found


def _port_open(port: int, timeout: float = 0.5) -> bool:
    import socket
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout):
            return True
    except OSError:
        return False


def status(app_id: str) -> dict:
    app = APPS.get(app_id)
    if not app:
        raise KeyError(app_id)
    exe = _resolve(app)
    procs = _processes(exe)
    port = int(app["port"])
    flag = f"--remote-debugging-port={port}"
    return {
        "id": app_id,
        "label": app["label"],
        "installed": bool(exe),
        "exe": exe,
        "port": port,
        "port_open": _port_open(port),
        "running": bool(procs),
        "pid": procs[0][0] if procs else None,
        "debug_flag": any(flag in args for _, args in procs),
        "can_open_folder": bool(app.get("open")) and bool(Path(app["open"][0]).exists()),
    }


def all_status() -> list[dict]:
    return [status(app_id) for app_id in APPS]


def launch(app_id: str, restart: bool = False, wait: float = 25.0) -> dict:
    app = APPS.get(app_id)
    if not app:
        raise KeyError(app_id)
    current = status(app_id)
    if not current["installed"]:
        raise ValueError(f"没有找到 {app['label']} 的可执行文件；在 config.json 里配 "
                         f"apps.{app_id}.exe，或设环境变量 WT_{app_id.upper()}_EXE")
    if current["port_open"] and not restart:
        return {**current, "action": "already"}

    if current["running"]:
        if not restart:
            raise ValueError(f"{app['label']} 已经在运行（PID {current['pid']}），但不是带 "
                             f"--remote-debugging-port={current['port']} 启动的；"
                             f"需要重启一次（会关掉当前窗口）")
        for pid, _ in _processes(current["exe"]):
            try:
                os.kill(pid, signal.SIGTERM)
            except OSError:
                pass
        deadline = time.time() + 12
        while time.time() < deadline and _processes(current["exe"]):
            time.sleep(0.4)
        if _processes(current["exe"]):
            raise ValueError(f"{app['label']} 没有退出，可能弹出了保存对话框；"
                             f"处理完再点一次，或手动退出")

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log = (LOG_DIR / f"{app_id}.log").open("a", encoding="utf-8")
    try:
        proc = subprocess.Popen(
            [current["exe"], f"--remote-debugging-port={app['port']}"],
            cwd=str(Path.home()), stdout=log, stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    finally:
        log.close()

    deadline = time.time() + wait
    while time.time() < deadline:
        if _port_open(int(app["port"])):
            return {**status(app_id), "action": "launched", "pid": proc.pid}
        time.sleep(0.5)
    raise ValueError(f"{app['label']} 已启动（PID {proc.pid}），但 "
                     f"{wait:.0f}s 内端口 {app['port']} 没起来；看 {LOG_DIR / (app_id + '.log')}")


def _page_targets(port: int) -> list[dict]:
    import json
    import urllib.request
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=3) as resp:
            return [t for t in json.loads(resp.read().decode("utf-8"))
                    if t.get("type") == "page"]
    except Exception:  # noqa: BLE001 - verification only
        return []


def _page_titles(port: int) -> list[str]:
    return [str(t.get("title") or "") for t in _page_targets(port)]


def _close_target(port: int, target_id: str) -> bool:
    """Close one window through the DevTools HTTP API (no websocket needed)."""
    import urllib.request
    try:
        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/json/close/{target_id}", timeout=3
        ) as resp:
            return "closing" in resp.read().decode("utf-8", "replace").lower()
    except Exception:  # noqa: BLE001 - the caller verifies by re-listing
        return False


# How long a stale window may take to disappear before we give up.
CLOSE_TIMEOUT = 8.0


def open_folder(app_id: str, path: Path, wait: float = 10.0) -> dict:
    app = APPS.get(app_id)
    if not app:
        raise KeyError(app_id)
    if not path.is_dir():
        raise ValueError(f"目录不存在：{path}")
    current = status(app_id)
    if not current["port_open"]:
        raise ValueError(f"{app['label']} 还没带调试端口启动；先点「启动 / 重启」")
    if not app.get("open") or not Path(app["open"][0]).exists():
        raise ValueError(f"{app['label']} 没有配置命令行打开方式")
    port = int(app["port"])
    # The window title only carries the folder name, so a second window with
    # the same name makes every later CDP call ambiguous — and the driver
    # would attach to the old window while the run thinks it talks to the new
    # one. Qoder restores its windows on launch, so stale ones are the norm:
    # close them here instead of making every run a manual cleanup.
    stale = [t for t in _page_targets(port) if path.name in (t.get("title") or "")]
    for target in stale:
        _close_target(port, target["id"])
    if stale:
        deadline = time.time() + CLOSE_TIMEOUT
        while time.time() < deadline:
            if not [t for t in _page_targets(port) if path.name in (t.get("title") or "")]:
                break
            time.sleep(0.5)
        else:
            raise ValueError(
                f"旧的「{path.name}」窗口关不掉（可能有未保存改动）。"
                "手动关掉它再试；两个同名窗口会让驱动连错一个。"
            )
        # Closing the last window quits the app. Bring it back with the debug
        # port first: the `-n` below would otherwise start an instance we
        # cannot drive, and the run would fail after a minute of retries.
        if not _port_open(port):
            launch(app_id, restart=True)
    before = {t.get("id") for t in _page_targets(port)}
    subprocess.Popen([*app["open"], str(path)], cwd=str(Path.home()),
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=True)

    # Trust but verify: the window title carries the folder name, and only a
    # target that did not exist before may count as the window we just opened.
    deadline = time.time() + wait
    while time.time() < deadline:
        after = _page_targets(port)
        hit = next((t for t in after
                    if t.get("id") not in before and path.name in (t.get("title") or "")),
                   None)
        if hit:
            return {"opened": str(path), "app": app_id, "verified": True,
                    "target_id": hit.get("id"),
                    "titles": [t.get("title") or "" for t in after]}
        time.sleep(0.5)
    raise ValueError(f"{app['label']} 没有出现「{path.name}」窗口；"
                     f"可能被旧窗口拦住了，先重启应用再试")
