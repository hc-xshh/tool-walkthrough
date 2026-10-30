#!/usr/bin/env python3
"""The coding-eval driver registry.

`code-eval/drivers.json` is the built-in source of truth for which tools exist,
what to call them, whether they attach over CDP or wrap a CLI, which port or
binary they need, and which flags the workbench may pass them. The workbench,
the dashboard server, and the run dashboard all derive their lists from here,
so a built-in tool means one JSON entry plus its drive_*.py file — not four
edits in four files that drift apart. User-added drivers live in
`~/.config/tool-walkthrough/plugins.json` and are merged by `load()` when no
explicit registry path is given.

Entry shape:

    {
      "file": "drive_qoder.py",      # the driver, relative to code-eval/tools
      "label": "Qoder CN（GUI）",     # what the pages show
      "kind": "gui" | "cli",         # CDP window vs. subprocess
      "port": 9444,                  # gui only
      "command": "codex",            # cli only, looked up on PATH
      "allowed_args": [...],         # flags the workbench page may pass through
      "features": ["open_workspace", "skip_workspace"]   # optional UI switches
    }
"""
from __future__ import annotations

import json
import os
from pathlib import Path

REGISTRY = Path(__file__).resolve().parent.parent / "drivers.json"


def _plugins_path() -> Path:
    override = os.environ.get("WT_PLUGINS")
    if override:
        return Path(override).expanduser()
    base = Path(os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config"))
    return base / "tool-walkthrough" / "plugins.json"


def _custom_entries() -> list[dict]:
    """User-registered drivers live beside the workbench config, not in the repo."""
    try:
        data = json.loads(_plugins_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    items = data.get("drivers") if isinstance(data, dict) else None
    if not isinstance(items, list):
        return []
    return [item for item in items if isinstance(item, dict) and item.get("custom")]


def load(path: Path | None = None) -> list[dict]:
    """Read and validate the registry; custom entries are merged when no path is given."""
    source = Path(path) if path else REGISTRY
    data = json.loads(source.read_text(encoding="utf-8"))
    entries = data.get("drivers")
    if not isinstance(entries, list) or not entries:
        raise ValueError(f"{source}: 'drivers' must be a non-empty list")
    if path is None:
        entries = entries + _custom_entries()

    seen: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError(f"{source}: every driver must be an object")
        name = entry.get("file")
        if not isinstance(name, str) or not name.endswith(".py"):
            raise ValueError(f"{source}: 'file' must be a .py name, got {name!r}")
        if name in seen:
            raise ValueError(f"{source}: duplicate driver {name}")
        seen.add(name)
        if not isinstance(entry.get("label"), str) or not entry["label"].strip():
            raise ValueError(f"{source}: {name} needs a label")
        kind = entry.get("kind")
        if kind not in ("gui", "cli"):
            raise ValueError(f"{source}: {name} kind must be 'gui' or 'cli', got {kind!r}")
        if kind == "gui" and not isinstance(entry.get("port"), int):
            raise ValueError(f"{source}: {name} is a GUI driver and needs an integer port")
        if kind == "cli" and not isinstance(entry.get("command"), str):
            raise ValueError(f"{source}: {name} is a CLI driver and needs a command")
        for key in ("allowed_args", "features"):
            value = entry.get(key, [])
            if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
                raise ValueError(f"{source}: {name}.{key} must be a list of strings")
    return entries


def labels() -> dict[str, str]:
    return {entry["file"]: entry["label"] for entry in load()}


def gui_ports() -> dict[str, int]:
    return {entry["file"]: entry["port"] for entry in load() if entry["kind"] == "gui"}


def cli_commands() -> dict[str, str]:
    return {entry["file"]: entry["command"] for entry in load() if entry["kind"] == "cli"}


def allowed_args(driver: str) -> list[str]:
    for entry in load():
        if entry["file"] == driver:
            return list(entry.get("allowed_args", []))
    return []


def features(driver: str) -> list[str]:
    for entry in load():
        if entry["file"] == driver:
            return list(entry.get("features", []))
    return []


def entry(driver: str) -> dict | None:
    for item in load():
        if item["file"] == driver:
            return dict(item)
    return None


def state() -> list[dict]:
    """The registry as the pages consume it: id / label / kind / port / features."""
    return [
        {
            "id": item["file"],
            "label": item["label"],
            "kind": item["kind"],
            "port": item.get("port"),
            "command": item.get("command"),
            "features": list(item.get("features", [])),
            "custom": bool(item.get("custom")),
        }
        for item in load()
    ]
