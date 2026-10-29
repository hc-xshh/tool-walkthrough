"""Operator loop tests with a fake model and a fake screen backend."""
from __future__ import annotations

import base64
import json
import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "harness"))

import llm_operator  # noqa: E402
from llm_client import LLMResponse  # noqa: E402

TINY_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


class FakeClient:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []
        self.config = type("Cfg", (), {"model": "fake-vision"})()

    def chat(self, messages):
        self.calls.append(messages)
        if not self.replies:
            raise AssertionError("no fake reply left")
        text = self.replies.pop(0)
        return LLMResponse(text=text, usage={"total_tokens": 10}, raw={})


class FakeBackend:
    name = "fake"

    def __init__(self):
        self.actions = []
        self.closed = False

    def capture(self, out):
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(TINY_PNG)
        return llm_operator.Observation(
            step=0, screenshot=out, text="输入框\n发送", width=200, height=100,
            dpr=1.0, title="fake product", url="http://fake",
        )

    def click(self, x, y, button=1):
        self.actions.append(("click", x, y))

    def click_text(self, text):
        self.actions.append(("click_text", text))
        return text

    def type_text(self, text):
        self.actions.append(("type", text))

    def press_key(self, key):
        self.actions.append(("key", key))

    def scroll(self, dy):
        self.actions.append(("scroll", dy))

    def close(self):
        self.closed = True


def action(**kw):
    return json.dumps(kw, ensure_ascii=False)


class OperatorTest(unittest.TestCase):
    def run_operator(self, replies, **kwargs):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        run = pathlib.Path(self.tmp.name) / "run"
        client = FakeClient(replies)
        backend = FakeBackend()
        op = llm_operator.Operator(
            client, backend, run, "完成一次测试走查",
            max_steps=kwargs.pop("max_steps", 5),
            max_seconds=kwargs.pop("max_seconds", 60),
            dry_run=kwargs.pop("dry_run", False),
        )
        result = op.run_loop()
        return result, run, client, backend

    def test_done_writes_findings_and_summary(self):
        result, run, client, backend = self.run_operator([
            action(action="done", summary="已完成"),
        ])
        self.assertEqual(result.status, "done")
        self.assertEqual(result.steps, 1)
        self.assertTrue((run / "findings.json").exists())
        self.assertTrue((run / "agent-summary.md").exists())
        self.assertTrue(backend.closed)
        data = json.loads((run / "findings.json").read_text(encoding="utf-8"))
        self.assertEqual(data["status"], "done")
        self.assertEqual(data["findings"], [])
        self.assertNotIn("api_key", data)
        events = (run / "events.jsonl").read_text(encoding="utf-8")
        self.assertIn('"action": "shot"', events)
        self.assertIn('"action": "agent_finish"', events)

    def test_finding_then_done(self):
        result, run, _client, _backend = self.run_operator([
            action(action="finding", title="发送后没有提示", detail="按钮无反馈", severity="S2"),
            action(action="done", summary="完成"),
        ])
        self.assertEqual(result.status, "done")
        self.assertEqual(len(result.findings), 1)
        data = json.loads((run / "findings.json").read_text(encoding="utf-8"))
        self.assertEqual(data["findings"][0]["severity"], "S2")
        self.assertTrue(data["findings"][0]["screenshot"].endswith("agent-step-01.png"))

    def test_click_then_done_records_actions_and_after_shot(self):
        result, run, _client, backend = self.run_operator([
            action(action="click", x=10, y=20, reason="点输入框"),
            action(action="done", summary="完成"),
        ])
        self.assertEqual(result.status, "done")
        self.assertIn(("click", 10.0, 20.0), backend.actions)
        self.assertTrue((run / "shots" / "agent-step-01-after.png").exists())
        events = (run / "events.jsonl").read_text(encoding="utf-8")
        self.assertIn('"action": "click"', events)

    def test_click_outside_screenshot_is_an_error_then_can_finish(self):
        result, _run, _client, backend = self.run_operator([
            action(action="click", x=999, y=20, reason="越界"),
            action(action="done", summary="完成"),
        ])
        self.assertEqual(result.status, "done")
        self.assertEqual(backend.actions, [])
        # The bad action is recorded as an error, not silently retried.
        events = (self.tmp.name + "/run/events.jsonl")
        self.assertIn("outside", pathlib.Path(events).read_text(encoding="utf-8"))

    def test_malformed_json_gets_one_correction(self):
        result, _run, client, _backend = self.run_operator([
            "这不是 JSON",
            action(action="done", summary="纠正后完成"),
        ])
        self.assertEqual(result.status, "done")
        self.assertEqual(len(client.calls), 2)

    def test_two_malformed_replies_stop(self):
        with self.assertRaises(llm_operator.OperatorError):
            self.run_operator(["nope", "still nope"])

    def test_max_steps(self):
        result, _run, _client, _backend = self.run_operator([
            action(action="click", x=i, y=2, reason=f"第{i}次") for i in range(1, 4)
        ], max_steps=3)
        self.assertEqual(result.status, "max_steps")
        self.assertEqual(result.steps, 3)

    def test_repeated_action_stops_before_budget(self):
        result, _run, _client, backend = self.run_operator([
            action(action="click", x=1, y=2, reason="重复"),
            action(action="click", x=1, y=2, reason="重复"),
            action(action="click", x=1, y=2, reason="重复"),
            action(action="done", summary="不应到这里"),
        ], max_steps=10)
        self.assertEqual(result.status, "repeated_action")
        self.assertEqual(len(backend.actions), 3)

    def test_type_is_not_written_to_events(self):
        result, run, _client, backend = self.run_operator([
            action(action="type", text="super-secret-message", reason="输入测试消息"),
            action(action="done", summary="完成"),
        ])
        self.assertEqual(result.status, "done")
        self.assertIn(("type", "super-secret-message"), backend.actions)
        events = (run / "events.jsonl").read_text(encoding="utf-8")
        self.assertNotIn("super-secret-message", events)
        self.assertIn("typed 20 chars", events)

    def test_dry_run_does_not_execute(self):
        result, _run, _client, backend = self.run_operator([
            action(action="click", x=1, y=2, reason="不执行"),
            action(action="done", summary="完成"),
        ], dry_run=True)
        self.assertEqual(result.status, "done")
        self.assertEqual(backend.actions, [])

    def test_cdp_click_converts_screenshot_pixels_to_css_pixels(self):
        class FakeCDP:
            def __init__(self):
                self.calls = []

            def eval(self, expr):
                return 2.0 if "devicePixelRatio" in expr else 1.0

            def cmd(self, method, params):
                self.calls.append((method, params))
                return {}

        backend = object.__new__(llm_operator.CDPBackend)
        backend.client = FakeCDP()
        backend.cdp = type("C", (), {"VK": {}})()
        backend.click(200, 100)
        moved = [p for method, p in backend.client.calls if method == "Input.dispatchMouseEvent"]
        self.assertEqual([(p["x"], p["y"]) for p in moved], [(100.0, 50.0)] * 3)

    def test_parse_action_rejects_bad_coordinates_and_unknown(self):
        with self.assertRaises(llm_operator.ActionError):
            llm_operator.parse_action('{"action":"click","x":"10","y":2}')
        with self.assertRaises(llm_operator.ActionError):
            llm_operator.parse_action('{"action":"fly"}')
        parsed = llm_operator.parse_action('```json\n{"action":"wait","seconds":999}\n```')
        self.assertEqual(parsed["seconds"], 10.0)


if __name__ == "__main__":
    unittest.main()
