"""Tests for the shared CDP driver plumbing (code-eval/tools/driver_core.py)."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "code-eval" / "tools"))

import driver_core  # noqa: E402


class CdpTest(unittest.TestCase):
    def setUp(self):
        self.tmp_name = f"driver-core-test-{id(self)}.js"
        self.cdp = driver_core.Cdp([sys.executable, "cdp.py", "--port", "9999"], self.tmp_name)
        self.calls = []
        self.replies = []
        self._real_run = driver_core.subprocess.run
        driver_core.subprocess.run = self.fake_run

    def tearDown(self):
        driver_core.subprocess.run = self._real_run
        self.cdp.tmp.unlink(missing_ok=True)

    def fake_run(self, cmd, **kwargs):
        self.calls.append((cmd, kwargs))
        rc, out = self.replies.pop(0)
        return subprocess.CompletedProcess(cmd, rc, out, "")

    def test_run_appends_op_and_arg_to_the_prefix(self):
        self.replies = [(0, "ok")]
        self.cdp.run("key", "Enter")
        self.assertEqual(self.calls[0][0][-2:], ["key", "Enter"])

    def test_run_raises_only_when_asked(self):
        self.replies = [(1, "boom")]
        self.assertEqual(self.cdp.run("text").returncode, 1)
        self.replies = [(1, "boom")]
        with self.assertRaises(RuntimeError):
            self.cdp.run("text", check=True)

    def test_js_decodes_json(self):
        self.replies = [(0, '{"x": 1}')]
        self.assertEqual(self.cdp.js("1"), {"x": 1})
        self.assertIn("eval", self.calls[0][0])

    def test_js_returns_raw_text_when_not_json(self):
        self.replies = [(0, "plain text")]
        self.assertEqual(self.cdp.js("1"), "plain text")

    def test_js_returns_none_on_failure(self):
        self.replies = [(1, "")]
        self.assertIsNone(self.cdp.js("1"))

    def test_js_cleans_up_its_scratch_file(self):
        self.replies = [(0, "1")]
        self.cdp.js("1")
        self.assertFalse(self.cdp.tmp.exists())

    def test_text_is_empty_when_cdp_is_down(self):
        self.replies = [(1, "")]
        self.assertEqual(self.cdp.text(), "")

    def test_pending_label_matches_visible_exact_text(self):
        self.cdp.js = lambda source, timeout=60: "允许" if '"允许"' in source else None
        self.assertEqual(self.cdp.pending_label(("允许", "运行")), "允许")


class WaitForTest(unittest.TestCase):
    def test_returns_true_when_predicate_passes(self):
        self.assertTrue(driver_core.wait_for(lambda: True, 1, interval=0.01))

    def test_returns_false_at_the_deadline(self):
        self.assertFalse(driver_core.wait_for(lambda: False, 0.05, interval=0.01, label="x"))


class BuildFeedbackTest(unittest.TestCase):
    def test_lists_failures_capped_at_eight(self):
        failures = [{"test": f"t{i}", "message": "line\nassert nope"} for i in range(10)]
        text = driver_core.build_feedback({"accept": {"failures": failures}}, "收尾。")
        self.assertEqual(text.count("- t"), 8)
        self.assertIn("- t0: assert nope", text)
        self.assertTrue(text.endswith("收尾。"))

    def test_truncates_long_messages(self):
        failures = [{"test": "t", "message": "x" * 500}]
        text = driver_core.build_feedback({"accept": {"failures": failures}}, "收尾。")
        self.assertIn("x" * 160, text)
        self.assertNotIn("x" * 161, text)

    def test_missing_accept_block_is_tolerated(self):
        self.assertIn("收尾。", driver_core.build_feedback({}, "收尾。"))


class LogTest(unittest.TestCase):
    def test_appends_one_json_line_per_event(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "trace.jsonl"
            path.write_text("", encoding="utf-8")
            driver_core.log(path, "sent", chars=12)
            driver_core.log(path, "done")
            records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        self.assertEqual([r["event"] for r in records], ["sent", "done"])
        self.assertEqual(records[0]["chars"], 12)
        self.assertIn("ts", records[0])


if __name__ == "__main__":
    unittest.main()
