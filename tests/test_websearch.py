"""Tests for the optional web-search provider adapters."""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "workbench"))

import websearch  # noqa: E402


class FakeResponse:
    def __init__(self, payload: dict):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self, *args):
        return json.dumps(self.payload).encode("utf-8")


class WebSearchTest(unittest.TestCase):
    def test_deepseek_adapter_uses_search_api(self):
        payload = {"results": [
            {"title": "Kimi", "url": "https://www.moonshot.cn/",
             "snippet": "Kimi is an AI assistant by Moonshot AI.",
             "summary": "Kimi summary", "date": "2026-10-01"},
        ]}
        with mock.patch.object(websearch.urllib.request, "urlopen",
                               return_value=FakeResponse(payload)) as opened:
            result = websearch.search("deepseek", "ds-key", "Kimi", max_results=3)
        self.assertEqual(result["provider"], "deepseek")
        self.assertEqual(result["results"][0]["url"], "https://www.moonshot.cn/")
        self.assertIn("Moonshot", result["results"][0]["snippet"])
        request = opened.call_args.args[0]
        self.assertIn("Bearer ds-key", request.get_header("Authorization"))
        body = json.loads(request.data.decode("utf-8"))
        self.assertEqual(body["query"], "Kimi")
        self.assertEqual(body["count"], 3)
        self.assertEqual(body["need_content"], False)

    def test_deepseek_empty_results_are_success(self):
        with mock.patch.object(websearch.urllib.request, "urlopen",
                               return_value=FakeResponse({"results": []})):
            result = websearch.search("deepseek", "ds-key", "Kimi")
        self.assertEqual(result["results"], [])

    def test_exa_adapter_normalizes_results(self):
        payload = {"results": [
            {"title": "Kimi", "url": "https://www.moonshot.cn/", "text": "Moonshot AI"},
        ]}
        with mock.patch.object(websearch.urllib.request, "urlopen",
                               return_value=FakeResponse(payload)) as opened:
            result = websearch.search("exa", "exa-key", "Kimi", max_results=3)
        self.assertEqual(result["provider"], "exa")
        self.assertEqual(result["results"][0]["url"], "https://www.moonshot.cn/")
        request = opened.call_args.args[0]
        self.assertEqual(request.get_header("X-api-key"), "exa-key")

    def test_tavily_adapter_keeps_answer(self):
        payload = {"answer": "Kimi is by Moonshot AI.",
                   "results": [{"title": "Kimi", "url": "https://kimi.moonshot.cn/",
                                "content": "Kimi"}]}
        with mock.patch.object(websearch.urllib.request, "urlopen",
                               return_value=FakeResponse(payload)):
            result = websearch.search("tavily", "tv-key", "Kimi Work")
        self.assertEqual(result["answer"], "Kimi is by Moonshot AI.")
        self.assertEqual(result["results"][0]["title"], "Kimi")

    def test_brave_adapter_reads_web_results(self):
        payload = {"web": {"results": [
            {"title": "Trae", "url": "https://www.trae.ai/", "description": "AI IDE"},
        ]}}
        with mock.patch.object(websearch.urllib.request, "urlopen",
                               return_value=FakeResponse(payload)):
            result = websearch.search("brave", "brave-key", "Trae")
        self.assertEqual(result["results"][0]["title"], "Trae")

    def test_perplexity_adapter_uses_citations(self):
        payload = {"choices": [{"message": {"content": "Qoder is by Alibaba Cloud."}}],
                   "citations": ["https://www.alibabacloud.com/help/en/lingma"]}
        with mock.patch.object(websearch.urllib.request, "urlopen",
                               return_value=FakeResponse(payload)):
            result = websearch.search("perplexity", "px-key", "Qoder")
        self.assertIn("Alibaba", result["answer"])
        self.assertEqual(result["results"][0]["url"],
                         "https://www.alibabacloud.com/help/en/lingma")

    def test_key_is_required_and_provider_must_exist(self):
        with self.assertRaises(ValueError):
            websearch.search("exa", "", "Kimi")
        with self.assertRaises(ValueError):
            websearch.search("nope", "key", "Kimi")

    def test_result_limit_is_validated(self):
        with self.assertRaises(ValueError):
            websearch.search("exa", "key", "Kimi", max_results=99)
        with self.assertRaises(ValueError):
            websearch.search("exa", "key", "Kimi", max_results="x")


if __name__ == "__main__":
    unittest.main()
