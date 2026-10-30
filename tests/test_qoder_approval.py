"""Which labels drive_qoder may click during a run."""
from __future__ import annotations

import sys
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


class TurnActiveTest(unittest.TestCase):
    class FakeCdp:
        def __init__(self, reply):
            self.reply = reply

        def js(self, source, timeout=60):
            return self.reply

    def check(self, reply):
        original = drive_qoder.CDP
        drive_qoder.CDP = self.FakeCdp(reply)
        try:
            return drive_qoder.turn_active()
        finally:
            drive_qoder.CDP = original

    def test_stop_button_means_the_turn_is_running(self):
        self.assertTrue(self.check(True))

    def test_no_stop_button_means_the_turn_ended(self):
        self.assertFalse(self.check(False))

    def test_cdp_failure_is_not_running(self):
        self.assertFalse(self.check(None))
