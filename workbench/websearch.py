"""Optional web-search providers for product discovery.

This is intentionally a *service*, not an agent tool: the workbench calls it
only when the user asks to add a product. No key, no search; there is no
built-in scraper or DuckDuckGo fallback.

Providers are small adapters over their public HTTP APIs. Keep them boring:
the discovery pipeline needs titles/URLs/snippets, not a universal document
model. Fetched pages are handled by the caller with SSRF checks.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

DEFAULT_PROVIDER = "deepseek"
DEFAULT_MAX_RESULTS = 5
TIMEOUT = 60

DEEPSEEK_BASE_URL = "https://api.deepseek.com/v1/tools"

PROVIDERS = [
    {
        "id": "deepseek",
        "label": "DeepSeek Search API",
        "base_url": DEEPSEEK_BASE_URL,
        "key_url": "https://platform.deepseek.com/api_keys",
        "note": "DeepSeek Search API（/v1/tools/search）：一次直接搜索，不走 Messages 轮次；留空 key 时复用模型 key。",
    },
    {
        "id": "exa",
        "label": "Exa",
        "base_url": "https://api.exa.ai",
        "key_url": "https://dashboard.exa.ai/api-keys",
        "note": "面向 AI 的网页搜索 API，返回标题、URL 和正文片段。",
    },
    {
        "id": "tavily",
        "label": "Tavily",
        "base_url": "https://api.tavily.com",
        "key_url": "https://app.tavily.com/home",
        "note": "为 agent 设计的搜索 API，支持 answer 摘要。",
    },
    {
        "id": "brave",
        "label": "Brave Search",
        "base_url": "https://api.search.brave.com/res/v1",
        "key_url": "https://api-dashboard.search.brave.com/app/keys",
        "note": "Brave 官方 Web Search API。",
    },
    {
        "id": "perplexity",
        "label": "Perplexity",
        "base_url": "https://api.perplexity.ai",
        "key_url": "https://www.perplexity.ai/settings/api",
        "note": "返回带引用的答案，适合快速确认产品信息。",
    },
]
_BY_ID = {item["id"]: item for item in PROVIDERS}


def provider_ids() -> list[str]:
    return [item["id"] for item in PROVIDERS]


def providers() -> list[dict]:
    """Public provider metadata; contains no secrets."""
    return [dict(item) for item in PROVIDERS]


def provider_info(provider: str) -> dict:
    item = _BY_ID.get(provider)
    if not item:
        raise ValueError(f"unsupported search provider: {provider}")
    return item


def _request_json(url: str, *, headers: dict, payload: dict | None = None,
                  timeout: float = TIMEOUT) -> dict:
    body = None
    method = "GET"
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        method = "POST"
        headers = {**headers, "Content-Type": "application/json"}
    request = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read(4_000_000)
    except urllib.error.HTTPError as exc:
        text = exc.read().decode("utf-8", "replace")[:400]
        if exc.code in (401, 403):
            raise ValueError(
                f"HTTP {exc.code}: 搜索 provider 认证失败。key 无效/过期，或填的是账号 token 而不是 API key；"
                "这不是“搜索能力不支持”。先在「配置」里用「保存并测试」验证模型 key / 搜索 key。"
                f" provider 返回：{text}"
            ) from None
        raise ValueError(f"HTTP {exc.code}: {text}") from None
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"cannot reach search provider: {exc}") from None
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ValueError("search provider returned non-JSON") from None
    if not isinstance(data, dict):
        raise ValueError("search provider returned an unexpected payload")
    return data


def _base(provider: str, base_url: str | None) -> str:
    base = (base_url or provider_info(provider)["base_url"]).strip().rstrip("/")
    parsed = urllib.parse.urlparse(base)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError("search base URL must be http:// or https://")
    return base


def _snippet(value) -> str:
    text = str(value or "").replace("\n", " ").strip()
    return text[:600]


def _exa(base: str, key: str, query: str, limit: int) -> dict:
    data = _request_json(
        base + "/search",
        headers={"x-api-key": key, "Accept": "application/json"},
        payload={"query": query, "numResults": limit,
                 "contents": {"text": {"maxCharacters": 1200}}},
    )
    results = []
    for item in data.get("results") or []:
        if not isinstance(item, dict):
            continue
        results.append({
            "title": str(item.get("title") or item.get("url") or "").strip(),
            "url": str(item.get("url") or "").strip(),
            "snippet": _snippet(item.get("text") or item.get("summary")),
        })
    return {"results": results, "answer": ""}


def _tavily(base: str, key: str, query: str, limit: int) -> dict:
    data = _request_json(
        base + "/search",
        headers={"Accept": "application/json"},
        payload={"api_key": key, "query": query, "max_results": limit,
                 "search_depth": "basic", "include_answer": True},
    )
    results = []
    for item in data.get("results") or []:
        if not isinstance(item, dict):
            continue
        results.append({
            "title": str(item.get("title") or item.get("url") or "").strip(),
            "url": str(item.get("url") or "").strip(),
            "snippet": _snippet(item.get("content")),
        })
    return {"results": results, "answer": str(data.get("answer") or "").strip()}


def _brave(base: str, key: str, query: str, limit: int) -> dict:
    url = base + "/web/search?" + urllib.parse.urlencode({"q": query, "count": limit})
    data = _request_json(url, headers={"X-Subscription-Token": key,
                                       "Accept": "application/json"})
    results = []
    for item in (data.get("web") or {}).get("results") or []:
        if not isinstance(item, dict):
            continue
        results.append({
            "title": str(item.get("title") or item.get("url") or "").strip(),
            "url": str(item.get("url") or "").strip(),
            "snippet": _snippet(item.get("description")),
        })
    return {"results": results, "answer": ""}


def _perplexity(base: str, key: str, query: str, limit: int) -> dict:
    data = _request_json(
        base + "/chat/completions",
        headers={"Authorization": f"Bearer {key}", "Accept": "application/json"},
        payload={
            "model": "sonar",
            "messages": [{"role": "user",
                          "content": f"Search the web for: {query}. "
                                     f"Return the key facts and cite sources."}],
            "max_tokens": 600,
        },
    )
    answer = ""
    choices = data.get("choices") or []
    if choices and isinstance(choices[0], dict):
        answer = str((choices[0].get("message") or {}).get("content") or "").strip()
    results = []
    for url in data.get("citations") or []:
        if not isinstance(url, str) or not url.startswith(("http://", "https://")):
            continue
        results.append({"title": url, "url": url, "snippet": ""})
    for item in data.get("search_results") or []:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "").strip()
        if not url:
            continue
        results.append({"title": str(item.get("title") or url), "url": url,
                        "snippet": _snippet(item.get("snippet") or item.get("content"))})
    # Deduplicate by URL, preserving order.
    seen = set()
    unique = []
    for item in results:
        if item["url"] in seen:
            continue
        seen.add(item["url"])
        unique.append(item)
    return {"results": unique[:limit], "answer": answer}


def _deepseek(base: str, key: str, query: str, limit: int) -> dict:
    """DeepSeek Search API provider (the provider DSH selects by default).

    One direct `/v1/tools/search` request; no auxiliary model turn. This is the
    endpoint that accepts the platform `sk-...` key and returns structured
    `results[]` with snippet/summary/date.
    """
    endpoint = base if base.endswith("/search") else base.rstrip("/") + "/search"
    data = _request_json(
        endpoint,
        headers={"Authorization": f"Bearer {key}", "Accept": "application/json"},
        payload={"query": query, "count": limit, "need_content": False},
    )
    results = []
    for item in data.get("results") or []:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "").strip()
        if not url.startswith(("http://", "https://")):
            continue
        results.append({
            "title": str(item.get("title") or url).strip(),
            "url": url,
            "snippet": _snippet(item.get("snippet") or item.get("summary")),
        })
        if len(results) >= limit:
            break
    return {"results": results, "answer": ""}


_ADAPTERS = {
    "deepseek": _deepseek,
    "exa": _exa,
    "tavily": _tavily,
    "brave": _brave,
    "perplexity": _perplexity,
}


def search(provider: str, key: str, query: str, *, max_results: int = DEFAULT_MAX_RESULTS,
           base_url: str | None = None) -> dict:
    """Run one explicit search. Raises ValueError with a user-facing message."""
    provider = (provider or "").strip()
    info = provider_info(provider)
    key = (key or "").strip()
    query = (query or "").strip()
    if not key:
        raise ValueError("还没有保存搜索 API Key")
    if not query:
        raise ValueError("搜索词不能为空")
    try:
        limit = int(max_results)
    except (TypeError, ValueError):
        raise ValueError("max_results must be an integer") from None
    if not 1 <= limit <= 10:
        raise ValueError("max_results must be 1..10")
    started = datetime.now(timezone.utc)
    base = _base(provider, base_url)
    data = _ADAPTERS[provider](base, key, query, limit)
    elapsed = round((datetime.now(timezone.utc) - started).total_seconds(), 2)
    results = [item for item in data.get("results") or []
               if item.get("url", "").startswith(("http://", "https://"))][:limit]
    return {
        "ok": True,
        "provider": provider,
        "provider_label": info["label"],
        "query": query,
        "results": results,
        "answer": data.get("answer") or "",
        "elapsed_s": elapsed,
    }
