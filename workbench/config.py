#!/usr/bin/env python3
"""Local workbench configuration.

One file on disk, mode 0600, outside the repository:

    ~/.config/tool-walkthrough/config.json     (override: $WT_CONFIG)

The API key lives here and nowhere else. It is never written to a run
directory, never put on a command line, and never sent back to the browser:
`public()` returns only `configured` and the last four characters.
"""
from __future__ import annotations

import json
import os
import stat
from pathlib import Path

DEFAULT_BASE_URL = "https://api.openai.com/v1"
DEFAULT_MODEL = "gpt-4o-mini"
DEFAULT_TIMEOUT = 120


def config_path() -> Path:
    override = os.environ.get("WT_CONFIG")
    if override:
        return Path(override).expanduser()
    base = os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config")
    return Path(base) / "tool-walkthrough" / "config.json"


def empty() -> dict:
    return {"llm": {"base_url": DEFAULT_BASE_URL, "model": DEFAULT_MODEL,
                    "api_key": "", "timeout": DEFAULT_TIMEOUT}}


def load() -> dict:
    path = config_path()
    data = empty()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return data
    if not isinstance(raw, dict):
        return data
    llm = raw.get("llm") if isinstance(raw.get("llm"), dict) else {}
    for key in ("base_url", "model", "api_key"):
        if isinstance(llm.get(key), str) and llm[key].strip():
            data["llm"][key] = llm[key].strip()
    timeout = llm.get("timeout")
    if isinstance(timeout, (int, float)) and timeout > 0:
        data["llm"]["timeout"] = float(timeout)
    return data


def save(patch: dict) -> dict:
    """Merge `patch` into the file. An empty api_key means "keep the old one"."""
    current = load()
    llm_patch = patch.get("llm") if isinstance(patch.get("llm"), dict) else patch
    if not isinstance(llm_patch, dict):
        raise ValueError("config payload must be an object")

    for key in ("base_url", "model"):
        if key in llm_patch:
            value = str(llm_patch[key]).strip()
            if not value:
                raise ValueError(f"{key} must not be empty")
            current["llm"][key] = value
    if "api_key" in llm_patch:
        value = str(llm_patch["api_key"]).strip()
        if value:  # empty means "leave the stored key alone"
            current["llm"]["api_key"] = value
    if "timeout" in llm_patch:
        try:
            timeout = float(llm_patch["timeout"])
        except (TypeError, ValueError):
            raise ValueError("timeout must be a number") from None
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        current["llm"]["timeout"] = timeout

    base = current["llm"]["base_url"]
    if not base.startswith(("http://", "https://")):
        raise ValueError("base_url must start with http:// or https://")
    write(current)
    return current


def write(data: dict) -> Path:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.parent.chmod(stat.S_IRWXU)  # 0700
    except OSError:
        pass
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    try:
        tmp.chmod(stat.S_IRUSR | stat.S_IWUSR)  # 0600 before it appears on disk
    except OSError:
        pass
    tmp.replace(path)
    return path


def key_hint(key: str) -> str:
    if not key:
        return ""
    if len(key) <= 8:
        return "****"
    return "*" * 4 + key[-4:]


def public(data: dict | None = None) -> dict:
    """What the browser is allowed to see. Never includes the key."""
    cfg = data if data is not None else load()
    llm = cfg["llm"]
    return {
        "configured": bool(llm.get("api_key")),
        "key_hint": key_hint(llm.get("api_key", "")),
        "base_url": llm.get("base_url", DEFAULT_BASE_URL),
        "model": llm.get("model", DEFAULT_MODEL),
        "timeout": llm.get("timeout", DEFAULT_TIMEOUT),
        "path": str(config_path()),
    }


def child_env(data: dict | None = None) -> dict:
    """Environment for a child process: the only way the key leaves this module."""
    cfg = data if data is not None else load()
    llm = cfg["llm"]
    env = dict(os.environ)
    if llm.get("api_key"):
        env["WT_LLM_API_KEY"] = llm["api_key"]
    env["WT_LLM_BASE_URL"] = llm.get("base_url", DEFAULT_BASE_URL)
    env["WT_LLM_MODEL"] = llm.get("model", DEFAULT_MODEL)
    env["WT_LLM_TIMEOUT"] = str(llm.get("timeout", DEFAULT_TIMEOUT))
    return env
