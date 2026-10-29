"""Tests for the OpenAI-compatible client. No network: a local stub server."""
from __future__ import annotations

import base64
import json
import pathlib
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "harness"))

import llm_client  # noqa: E402

TINY_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


class StubLLM:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers.get("Content-Length", "0"))
                outer.requests.append({
                    "path": self.path,
                    "headers": dict(self.headers),
                    "body": json.loads(self.rfile.read(length)),
                })
                status, payload, headers = outer.responses.pop(0) if outer.responses else (500, {"error": "empty"}, {})
                raw = json.dumps(payload).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                for key, value in headers.items():
                    self.send_header(key, value)
                self.end_headers()
                self.wfile.write(raw)

            def log_message(self, format, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    @property
    def base_url(self):
        return f"http://127.0.0.1:{self.server.server_port}/v1"


def response(text="ok", usage=None):
    return 200, {"choices": [{"message": {"content": text}}], "usage": usage or {"total_tokens": 3}}, {}


class LLMClientTest(unittest.TestCase):
    def config(self, base, **kwargs):
        return llm_client.LLMConfig(
            api_key=kwargs.pop("api_key", "sk-test-secret"),
            base_url=base,
            model=kwargs.pop("model", "vision-test"),
            timeout=kwargs.pop("timeout", 5),
            max_retries=kwargs.pop("max_retries", 1),
            **kwargs,
        )

    def test_missing_key_is_actionable(self):
        with self.assertRaises(llm_client.LLMError) as ctx:
            llm_client.LLMConfig.from_env({})
        self.assertIn("WT_LLM_API_KEY", str(ctx.exception))

    def test_endpoint_accepts_base_or_full_path(self):
        cfg = llm_client.LLMConfig(api_key="x", base_url="https://example.test/v1")
        self.assertEqual(cfg.endpoint, "https://example.test/v1/chat/completions")
        cfg = llm_client.LLMConfig(api_key="x", base_url="https://example.test/v1/chat/completions")
        self.assertEqual(cfg.endpoint, "https://example.test/v1/chat/completions")

    def test_chat_sends_model_text_and_image(self):
        with StubLLM([response("first step", {"prompt_tokens": 2, "total_tokens": 5})]) as stub:
            client = llm_client.ChatClient(self.config(stub.base_url, max_tokens=77))
            with tempfile.TemporaryDirectory() as tmp:
                shot = pathlib.Path(tmp) / "shot.png"
                shot.write_bytes(TINY_PNG)
                msg = llm_client.user_message("look here", shot)
                got = client.chat([{"role": "system", "content": "sys"}, msg])

        self.assertEqual(got.text, "first step")
        self.assertEqual(got.usage["total_tokens"], 5)
        req = stub.requests[0]
        self.assertEqual(req["path"], "/v1/chat/completions")
        self.assertEqual(req["headers"]["Authorization"], "Bearer sk-test-secret")
        self.assertEqual(req["body"]["model"], "vision-test")
        self.assertEqual(req["body"]["max_tokens"], 77)
        parts = req["body"]["messages"][1]["content"]
        self.assertEqual(parts[0], {"type": "text", "text": "look here"})
        self.assertTrue(parts[1]["image_url"]["url"].startswith("data:image/png;base64,"))

    def test_retries_429_then_succeeds(self):
        with StubLLM([
            (429, {"error": "slow down"}, {"Retry-After": "0"}),
            response("after retry"),
        ]) as stub:
            client = llm_client.ChatClient(self.config(stub.base_url, max_retries=1))
            with mock.patch("llm_client.time.sleep") as sleep:
                got = client.chat([{"role": "user", "content": "hi"}])
        self.assertEqual(got.text, "after retry")
        self.assertEqual(len(stub.requests), 2)
        sleep.assert_called_once()

    def test_auth_error_is_not_retried_and_key_is_redacted(self):
        with StubLLM([(401, {"error": "bad key sk-test-secret"}, {})]) as stub:
            client = llm_client.ChatClient(self.config(stub.base_url, max_retries=3))
            with self.assertRaises(llm_client.LLMError) as ctx:
                client.chat([{"role": "user", "content": "hi"}])
        self.assertEqual(len(stub.requests), 1)
        self.assertIn("HTTP 401", str(ctx.exception))
        self.assertNotIn("sk-test-secret", str(ctx.exception))
        self.assertIn("<redacted>", str(ctx.exception))

    def test_config_from_env_defaults(self):
        cfg = llm_client.LLMConfig.from_env({"WT_LLM_API_KEY": "abc"})
        self.assertEqual(cfg.base_url, llm_client.DEFAULT_BASE_URL)
        self.assertEqual(cfg.model, llm_client.DEFAULT_MODEL)
        self.assertNotIn("abc", repr(cfg))


if __name__ == "__main__":
    unittest.main()
