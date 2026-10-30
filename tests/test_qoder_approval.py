"""Which labels drive_qoder may click during a run."""
from __future__ import annotations

import json
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "code-eval" / "tools"))

import drive_qoder  # noqa: E402


class ApprovalLabelsTest(unittest.TestCase):
    def test_terminal_prompt_offers_accept(self):
        labels = drive_qoder.approval_labels("终端运行 Ctrl ↩\n拒绝\n接受")
        self.assertIn("接受", labels)

    def test_terms_dialog_does_not_offer_accept(self):
        # Same label, different meaning: accepting a licence is not ours to do.
        labels = drive_qoder.approval_labels("安装前请阅读并接受许可协议\n接受\n拒绝")
        self.assertNotIn("接受", labels)
        self.assertIn("允许", labels)

    def test_plain_page_keeps_the_base_labels(self):
        self.assertEqual(drive_qoder.approval_labels("正在执行中"), drive_qoder.APPROVE_GATED)

    def test_accept_is_not_in_the_gated_set(self):
        self.assertNotIn("接受", drive_qoder.APPROVE_GATED)
        self.assertIn("接受", drive_qoder.APPROVE_LABELS)


class RunConfirmTest(unittest.TestCase):
    """Qoder 1.37's split button, labelled "终端运行 Ctrl ↩"."""

    class FakeCdp:
        def __init__(self, reply):
            self.reply = reply
            self.calls = []
            self.source = ""

        def js(self, source, timeout=60):
            self.calls.append(source)
            self.source = source
            return self.reply

    def with_cdp(self, reply):
        fake = self.FakeCdp(reply)
        original = drive_qoder.CDP
        drive_qoder.CDP = fake
        try:
            return fake, drive_qoder.click_run_confirm()
        finally:
            drive_qoder.CDP = original

    def test_find_and_click_happen_in_one_call(self):
        # Measuring the rect first and clicking it from another process loses
        # the race with the chat re-render: the click then lands on the
        # neighbouring "开启终端自动执行" switch.
        fake, label = self.with_cdp("终端运行 Ctrl ↩")
        self.assertEqual(label, "终端运行 Ctrl ↩")
        self.assertEqual(len(fake.calls), 1)
        self.assertIn("el.click()", fake.source)
        self.assertIn("startsWith", fake.source)
        for prefix in drive_qoder.dialogs.RUN_CONFIRM_PREFIXES:
            self.assertIn(prefix, fake.source)

    def test_no_run_button_is_not_a_click(self):
        fake, label = self.with_cdp(None)
        self.assertIsNone(label)
        self.assertEqual(len(fake.calls), 1)

    def test_empty_reply_is_not_a_label(self):
        _, label = self.with_cdp("")
        self.assertIsNone(label)


if __name__ == "__main__":
    unittest.main()


class ComposerStateTest(unittest.TestCase):
    """Qoder 1.37 has no "正在执行中" text; the send button is the state."""

    class FakeCdp:
        def __init__(self, reply):
            self.reply = reply

        def js(self, source, timeout=60):
            return self.reply

    def check(self, reply):
        original = drive_qoder.CDP
        drive_qoder.CDP = self.FakeCdp(reply)
        try:
            return drive_qoder.composer_state()
        finally:
            drive_qoder.CDP = original

    def test_stop_button_is_running(self):
        self.assertEqual(self.check("running"), "running")

    def test_send_button_is_idle(self):
        self.assertEqual(self.check("idle"), "idle")

    def test_missing_button_is_not_a_state(self):
        self.assertEqual(self.check(None), "missing")

    def test_turn_active_follows_the_composer(self):
        original = drive_qoder.CDP
        drive_qoder.CDP = self.FakeCdp("running")
        try:
            self.assertTrue(drive_qoder.turn_active())
            drive_qoder.CDP = self.FakeCdp("idle")
            self.assertFalse(drive_qoder.turn_active())
        finally:
            drive_qoder.CDP = original


class WaitDonePhaseTest(unittest.TestCase):
    """A run that never starts must say so, not burn the whole timebox."""

    class StubCdp:
        def pending_label(self, labels):
            return None

    def setUp(self):
        self.real = {name: getattr(drive_qoder, name) for name in
                     ("page_text", "turn_active", "click_run_confirm", "guard_dialogs", "CDP")}
        drive_qoder.CDP = self.StubCdp()
        drive_qoder.click_run_confirm = lambda: None
        drive_qoder.guard_dialogs = lambda *args, **kwargs: "ok"
        self.tmp = tempfile.TemporaryDirectory()
        self.log = Path(self.tmp.name) / "x.trace.jsonl"
        self.log.write_text("", encoding="utf-8")

    def tearDown(self):
        for name, value in self.real.items():
            setattr(drive_qoder, name, value)
        self.tmp.cleanup()

    def events(self):
        return [json.loads(line) for line in self.log.read_text(encoding="utf-8").splitlines()]

    def test_never_started_bails_out_before_the_timebox(self):
        drive_qoder.page_text = lambda: "unchanged page"
        drive_qoder.turn_active = lambda: False
        started = time.time()
        ok, approvals = drive_qoder.wait_done(self.log, timebox=600, start_timeout=1)
        self.assertFalse(ok)
        self.assertLess(time.time() - started, 30)
        self.assertEqual([e["event"] for e in self.events()], ["never_started", "timeout"])
        self.assertEqual(self.events()[-1]["phase"], "never_started")

    def test_timeout_says_the_turn_was_still_running(self):
        counter = iter(range(10_000))
        drive_qoder.page_text = lambda: f"streaming {next(counter)}"
        drive_qoder.turn_active = lambda: True
        ok, _ = drive_qoder.wait_done(self.log, timebox=1, start_timeout=90)
        self.assertFalse(ok)
        self.assertEqual(self.events()[-1]["event"], "timeout")
        self.assertEqual(self.events()[-1]["phase"], "turn_still_running")
