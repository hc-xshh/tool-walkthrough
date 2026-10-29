#!/usr/bin/env python3
"""OpenAI-compatible chat client for the walkthrough operator.

Only the standard library is used. The key stays in the environment; it is
never accepted on the command line (process lists are visible to other users)
and every error message is passed through `redact` before it reaches a log.

Configuration:

  WT_LLM_API_KEY   required
  WT_LLM_BASE_URL  default https://api.openai.com/v1
  WT_LLM_MODEL     default gpt-4o-mini
  WT_LLM_TIMEOUT   default 120 seconds
"""
from __future__ import annotations

import base64
import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

DEFAULT_BASE_URL = "https://api.openai.com/v1"
DEFAULT_MODEL = "gpt-4o-mini"
DEFAULT_TIMEOUT = 120.0
DEFAULT_MAX_TOKENS = 1024
MAX_IMAGE_BYTES = 12 * 1024 * 1024


class LLMError(RuntimeError):
    """A configuration, transport, or provider error.

    `retryable` is advisory; the client already retried 429/5xx before this is
    raised. Callers should stop the run rather than hammer a broken endpoint.
    """

    def __init__(self, message: str, *, status: int | None = None, retryable: bool = False):
        super().__init__(message)
        self.status = status
        self.retryable = retryable


def redact(text: object, secret: str | None) -> str:
    """Replace the API key in any string before it is logged or raised."""
    value = str(text)
    if secret:
        return value.replace(secret, "<redacted>")
    return value


@dataclass(frozen=True)
class LLMConfig:
    api_key: str = field(repr=False)
    base_url: str = DEFAULT_BASE_URL
    model: str = DEFAULT_MODEL
    timeout: float = DEFAULT_TIMEOUT
    max_tokens: int = DEFAULT_MAX_TOKENS
    temperature: float = 0.0
    max_retries: int = 2

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> "LLMConfig":
        source = os.environ if env is None else env
        key = (source.get("WT_LLM_API_KEY") or "").strip()
        if not key:
            raise LLMError(
                "WT_LLM_API_KEY is not set. Export it before running `wt.py agent`; "
                "do not put the key in the repository."
            )
        base = (source.get("WT_LLM_BASE_URL") or DEFAULT_BASE_URL).strip()
        model = (source.get("WT_LLM_MODEL") or DEFAULT_MODEL).strip()
        if not base.startswith(("http://", "https://")):
            raise LLMError("WT_LLM_BASE_URL must start with http:// or https://")
        if not model:
            raise LLMError("WT_LLM_MODEL is empty")
        try:
            timeout = float(source.get("WT_LLM_TIMEOUT") or DEFAULT_TIMEOUT)
        except ValueError as exc:
            raise LLMError("WT_LLM_TIMEOUT must be a number") from exc
        if timeout <= 0:
            raise LLMError("WT_LLM_TIMEOUT must be positive")
        return cls(api_key=key, base_url=base.rstrip("/"), model=model, timeout=timeout)

    @property
    def endpoint(self) -> str:
        if self.base_url.endswith("/chat/completions"):
            return self.base_url
        return self.base_url + "/chat/completions"


def image_part(path: str | Path, mime: str = "image/png") -> dict[str, Any]:
    """Encode a local screenshot as an OpenAI-compatible image_url part."""
    p = Path(path)
    try:
        raw = p.read_bytes()
    except OSError as exc:
        raise LLMError(f"cannot read screenshot: {p}") from exc
    if not raw:
        raise LLMError(f"screenshot is empty: {p}")
    if len(raw) > MAX_IMAGE_BYTES:
        raise LLMError(
            f"screenshot is too large ({len(raw)} bytes); capture a smaller window "
            f"or resize before sending it to the model"
        )
    return {
        "type": "image_url",
        "image_url": {"url": f"data:{mime};base64,{base64.b64encode(raw).decode('ascii')}"},
    }


def user_message(text: str, image: str | Path | None = None) -> dict[str, Any]:
    """Build a user message with optional vision input."""
    content: list[dict[str, Any]] = [{"type": "text", "text": text}]
    if image is not None:
        content.append(image_part(image))
    return {"role": "user", "content": content}


@dataclass
class LLMResponse:
    text: str
    usage: dict[str, Any]
    raw: dict[str, Any]


class ChatClient:
    """Small OpenAI-compatible chat client with bounded retries."""

    def __init__(self, config: LLMConfig):
        self.config = config

    def _payload(self, messages: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "model": self.config.model,
            "messages": messages,
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
        }

    def chat(self, messages: list[dict[str, Any]]) -> LLMResponse:
        payload = self._payload(messages)
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.config.api_key}",
            "Accept": "application/json",
        }
        last_error: LLMError | None = None
        for attempt in range(self.config.max_retries + 1):
            req = urllib.request.Request(
                self.config.endpoint, data=body, headers=headers, method="POST"
            )
            try:
                with urllib.request.urlopen(req, timeout=self.config.timeout) as resp:
                    raw = json.loads(resp.read().decode("utf-8", "replace"))
                return self._parse(raw)
            except urllib.error.HTTPError as exc:
                detail = self._error_detail(exc)
                retryable = exc.code in (408, 409, 429, 500, 502, 503, 504)
                last_error = LLMError(
                    f"LLM provider returned HTTP {exc.code}: {detail}",
                    status=exc.code,
                    retryable=retryable,
                )
                if not retryable or attempt >= self.config.max_retries:
                    exc.close()
                    raise last_error from None
                self._sleep_after_retry(exc, attempt)
                exc.close()
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                last_error = LLMError(
                    f"cannot reach LLM provider: {redact(exc, self.config.api_key)}",
                    retryable=True,
                )
                if attempt >= self.config.max_retries:
                    raise last_error from None
                time.sleep(min(2 ** attempt, 8))
            except (ValueError, KeyError, TypeError) as exc:
                raise LLMError(
                    f"invalid LLM response: {redact(exc, self.config.api_key)}"
                ) from None
        raise last_error or LLMError("LLM request failed")

    def _error_detail(self, exc: urllib.error.HTTPError) -> str:
        try:
            raw = exc.read().decode("utf-8", "replace")
        except Exception:
            raw = ""
        raw = raw.strip().replace("\n", " ")
        if len(raw) > 500:
            raw = raw[:500] + "..."
        if not raw:
            raw = exc.reason or "no response body"
        return redact(raw, self.config.api_key)

    def _sleep_after_retry(self, exc: urllib.error.HTTPError, attempt: int) -> None:
        retry_after = exc.headers.get("Retry-After") if exc.headers else None
        try:
            delay = float(retry_after) if retry_after else min(2 ** attempt, 8)
        except (TypeError, ValueError):
            delay = min(2 ** attempt, 8)
        time.sleep(max(0.0, min(delay, 30.0)))

    def _parse(self, raw: dict[str, Any]) -> LLMResponse:
        try:
            content = raw["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            raise LLMError("LLM response has no choices[0].message.content") from None
        if isinstance(content, list):
            # Some compatible providers return content blocks instead of a string.
            text = "".join(
                str(part.get("text", ""))
                for part in content
                if isinstance(part, dict) and part.get("type") in ("text", "output_text")
            )
        else:
            text = "" if content is None else str(content)
        usage = raw.get("usage")
        if not isinstance(usage, dict):
            usage = {}
        return LLMResponse(text=text, usage=usage, raw=raw)
