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

import websearch

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
    return {
        "llm": {"base_url": DEFAULT_BASE_URL, "model": DEFAULT_MODEL,
                "api_key": "", "timeout": DEFAULT_TIMEOUT},
        "web": {"provider": websearch.DEFAULT_PROVIDER, "api_key": "",
                "base_url": "", "max_results": websearch.DEFAULT_MAX_RESULTS,
                "enabled": True},
    }


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

    web = raw.get("web") if isinstance(raw.get("web"), dict) else {}
    provider = web.get("provider")
    if isinstance(provider, str) and provider.strip() in websearch.provider_ids():
        data["web"]["provider"] = provider.strip()
    for key in ("api_key", "base_url"):
        if isinstance(web.get(key), str):
            data["web"][key] = web[key].strip()
    max_results = web.get("max_results")
    if isinstance(max_results, int) and 1 <= max_results <= 10:
        data["web"]["max_results"] = max_results
    if isinstance(web.get("enabled"), bool):
        data["web"]["enabled"] = web["enabled"]
    return data


def save(patch: dict) -> dict:
    """Merge `patch` into the file. An empty api_key means "keep the old one"."""
    current = load()
    has_sections = isinstance(patch.get("llm"), dict) or isinstance(patch.get("web"), dict)
    llm_patch = patch.get("llm") if isinstance(patch.get("llm"), dict) else ({} if has_sections else patch)
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

    web_patch = patch.get("web") if isinstance(patch.get("web"), dict) else {}
    if web_patch:
        old_provider = current["web"].get("provider")
        provider = web_patch.get("provider")
        if provider is not None:
            provider = str(provider).strip()
            if provider not in websearch.provider_ids():
                raise ValueError(f"unsupported search provider: {provider}")
            current["web"]["provider"] = provider
        new_key = str(web_patch.get("api_key") or "").strip() if "api_key" in web_patch else ""
        if provider is not None and provider != old_provider and not new_key:
            # A write-only key cannot be inspected by the browser. Sending an
            # Exa key to DeepSeek (or vice versa) only produces a confusing
            # 401, so switching providers clears the old slot.
            current["web"]["api_key"] = ""
        if "api_key" in web_patch:
            value = str(web_patch["api_key"]).strip()
            if value:  # empty means "leave the stored key alone" (same provider)
                current["web"]["api_key"] = value
                current["web"]["enabled"] = True
        if "base_url" in web_patch:
            value = str(web_patch["base_url"]).strip()
            if value and not value.startswith(("http://", "https://")):
                raise ValueError("search base_url must start with http:// or https://")
            current["web"]["base_url"] = value
        if "max_results" in web_patch:
            try:
                limit = int(web_patch["max_results"])
            except (TypeError, ValueError):
                raise ValueError("max_results must be an integer") from None
            if not 1 <= limit <= 10:
                raise ValueError("max_results must be 1..10")
            current["web"]["max_results"] = limit
        if "enabled" in web_patch:
            current["web"]["enabled"] = bool(web_patch["enabled"])

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


def can_reuse_llm_key(data: dict | None = None) -> bool:
    """True when the configured chat endpoint/key is DeepSeek.

    DeepSeek's search API uses the same key as the model. Reusing it avoids
    asking the user to paste the same secret twice, but an OpenAI/Anthropic
    model key must never be sent to DeepSeek.
    """
    cfg = data if data is not None else load()
    base = str(cfg["llm"].get("base_url") or "").lower()
    model = str(cfg["llm"].get("model") or "").lower()
    return "deepseek" in base or model.startswith("deepseek")


def effective_search_key(data: dict | None = None) -> str:
    """The key a DeepSeek search would use: explicit web key first, then chat key."""
    cfg = data if data is not None else load()
    web = cfg["web"]
    if web.get("api_key"):
        return str(web["api_key"])
    if web.get("provider") == "deepseek" and can_reuse_llm_key(cfg):
        return str(cfg["llm"].get("api_key") or "")
    return ""


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
    web_key = str(cfg["web"].get("api_key") or "")
    reused = bool(not web_key and cfg["web"].get("provider") == "deepseek"
                  and can_reuse_llm_key(cfg) and llm.get("api_key"))
    effective = web_key or (str(llm.get("api_key") or "") if reused else "")
    return {
        "configured": bool(llm.get("api_key")),
        "key_hint": key_hint(llm.get("api_key", "")),
        "base_url": llm.get("base_url", DEFAULT_BASE_URL),
        "model": llm.get("model", DEFAULT_MODEL),
        "timeout": llm.get("timeout", DEFAULT_TIMEOUT),
        "path": str(config_path()),
        "web": {
            "provider": cfg["web"].get("provider", websearch.DEFAULT_PROVIDER),
            "configured": bool(effective),
            "reused": reused,
            "key_hint": key_hint(effective),
            "base_url": cfg["web"].get("base_url", ""),
            "max_results": cfg["web"].get("max_results", websearch.DEFAULT_MAX_RESULTS),
            "enabled": bool(cfg["web"].get("enabled")),
            "providers": websearch.providers(),
        },
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
