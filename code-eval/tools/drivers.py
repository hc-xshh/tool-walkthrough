#!/usr/bin/env python3
"""The coding-eval driver registry.

`code-eval/drivers.json` is the only place that knows which tools exist, what
to call them, whether they attach over CDP or wrap a CLI, which port or binary
they need, and which flags the workbench may pass them. The workbench, the
dashboard server, and the run dashboard all derive their lists from here, so a
new tool means one JSON entry plus its drive_*.py file — not four edits in four
files that drift apart.

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
from pathlib import Path

REGISTRY = Path(__file__).resolve().parent.parent / "drivers.json"


def load(path: Path | None = None) -> list[dict]:
    """Read and validate the registry; raise ValueError with the bad entry."""
    source = Path(path) if path else REGISTRY
    data = json.loads(source.read_text(encoding="utf-8"))
    entries = data.get("drivers")
    if not isinstance(entries, list) or not entries:
        raise ValueError(f"{source}: 'drivers' must be a non-empty list")

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
            "features": list(item.get("features", [])),
        }
        for item in load()
    ]
