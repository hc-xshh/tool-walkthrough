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


if __name__ == "__main__":
    unittest.main()
