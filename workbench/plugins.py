#!/usr/bin/env python3
"""Local registry for user-added integrations.

The built-in apps and eval drivers stay in code. This file only stores the
extra apps/drivers a user adds from the workbench, plus explicit executable
overrides for the built-in GUI apps. It lives next to config.json, outside the
repository, mode 0600.

Shape:

    {
      "apps": [
        {"id": "custom-my-app", "label": "My App", "exe": "/opt/my-app", "port": 9222},
        {"id": "cursor", "exe": "/opt/cursor/cursor"}
      ],
      "drivers": [
        {"file": "/home/me/drive_my.py", "label": "My Tool", "kind": "gui",
         "port": 9222, "allowed_args": [], "features": [], "custom": true}
      ],
      "discovered": [
        {"id": "disc-kimi-work", "query": "Kimi Work", "name": "Kimi Work",
         "vendor": "Moonshot AI", "sources": [{"url": "https://..."}],
         "app_id": "custom-kimi-work"}
      ]
    }

`apps` entries whose id matches a built-in app only contribute an executable
override; the label/port stay under code control. Other ids are new GUI apps.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

def path() -> Path:
    override = os.environ.get("WT_PLUGINS")
    if override:
        return Path(override).expanduser()
    base = Path(os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config"))
    return base / "tool-walkthrough" / "plugins.json"


def _empty() -> dict:
    return {"apps": [], "drivers": [], "discovered": []}


def load() -> dict:
    target = path()
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return _empty()
    if not isinstance(data, dict):
        return _empty()
    apps = data.get("apps") if isinstance(data.get("apps"), list) else []
    drivers = data.get("drivers") if isinstance(data.get("drivers"), list) else []
    discovered = data.get("discovered") if isinstance(data.get("discovered"), list) else []
    return {
        "apps": [item for item in apps if isinstance(item, dict)],
        "drivers": [item for item in drivers if isinstance(item, dict)],
        "discovered": [item for item in discovered if isinstance(item, dict)],
    }


def save(data: dict) -> Path:
    target = path()
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        target.parent.chmod(0o700)
    except OSError:
        pass
    payload = {
        "apps": [item for item in data.get("apps", []) if isinstance(item, dict)],
        "drivers": [item for item in data.get("drivers", []) if isinstance(item, dict)],
        "discovered": [item for item in data.get("discovered", []) if isinstance(item, dict)],
    }
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    try:
        tmp.chmod(0o600)
    except OSError:
        pass
    tmp.replace(target)
    return target


def _clean_list(value) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item).strip()]


def upsert_app(entry: dict) -> dict:
    data = load()
    app_id = str(entry.get("id") or "").strip()
    if not app_id:
        raise ValueError("app id is required")
    data["apps"] = [item for item in data["apps"] if str(item.get("id") or "") != app_id]
    data["apps"].append(entry)
    save(data)
    return entry


def remove_app(app_id: str) -> bool:
    data = load()
    kept = [item for item in data["apps"] if str(item.get("id") or "") != app_id]
    if len(kept) == len(data["apps"]):
        return False
    data["apps"] = kept
    save(data)
    return True


def upsert_driver(entry: dict) -> dict:
    data = load()
    file = str(entry.get("file") or "").strip()
    if not file:
        raise ValueError("driver file is required")
    data["drivers"] = [item for item in data["drivers"] if str(item.get("file") or "") != file]
    data["drivers"].append(entry)
    save(data)
    return entry


def remove_driver(file: str) -> bool:
    data = load()
    kept = [item for item in data["drivers"] if str(item.get("file") or "") != file]
    if len(kept) == len(data["drivers"]):
        return False
    data["drivers"] = kept
    save(data)
    return True


def list_discovered() -> list[dict]:
    return list(load().get("discovered", []))


def upsert_discovered(entry: dict) -> dict:
    data = load()
    item_id = str(entry.get("id") or "").strip()
    if not item_id:
        raise ValueError("discovered product id is required")
    previous = next((item for item in data["discovered"]
                     if str(item.get("id") or "") == item_id), {})
    if previous.get("created_at") and not entry.get("created_at"):
        entry["created_at"] = previous["created_at"]
    data["discovered"] = [item for item in data["discovered"]
                          if str(item.get("id") or "") != item_id]
    data["discovered"].append(entry)
    save(data)
    return entry


def remove_discovered(item_id: str) -> bool:
    data = load()
    kept = [item for item in data["discovered"]
            if str(item.get("id") or "") != str(item_id)]
    if len(kept) == len(data["discovered"]):
        return False
    data["discovered"] = kept
    save(data)
    return True


def add_driver(body: dict) -> dict:
    raw = str(body.get("file") or "").strip()
    if not raw:
        raise ValueError("填一个 drive_*.py 脚本路径")
    file = Path(raw).expanduser()
    if not file.is_absolute():
        file = (Path.cwd() / file)
    file = file.resolve()
    if file.suffix != ".py" or not file.is_file():
        raise ValueError(f"找不到 Python 驱动器脚本：{file}")
    label = str(body.get("label") or "").strip()
    if not label:
        raise ValueError("填写驱动器名称")
    kind = str(body.get("kind") or "").strip()
    if kind not in ("gui", "cli"):
        raise ValueError("驱动器类型必须是 gui 或 cli")
    entry = {"file": str(file), "label": label, "kind": kind, "custom": True}
    if kind == "gui":
        try:
            port = int(body.get("port"))
        except (TypeError, ValueError):
            raise ValueError("GUI 驱动器需要一个整数端口") from None
        if not 1 <= port <= 65535:
            raise ValueError("端口需要在 1–65535 之间")
        entry["port"] = port
    else:
        command = str(body.get("command") or "").strip()
        if not command:
            raise ValueError("CLI 驱动器需要一个命令名")
        entry["command"] = command
    features = [f for f in _clean_list(body.get("features"))
                if f in ("open_workspace", "skip_workspace")]
    entry["features"] = features
    entry["allowed_args"] = ["--skip-workspace"] if "skip_workspace" in features else []
    return upsert_driver(entry)


def slug(value: str) -> str:
    text = re.sub(r"[^a-z0-9]+", "-", str(value or "").lower()).strip("-")
    return text[:32]
