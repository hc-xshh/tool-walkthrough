"""Tests for the dialog tiering: safe / blocked / unknown."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "code-eval" / "tools"))

import dialogs  # noqa: E402


class ClassifyTest(unittest.TestCase):
    def test_trust_dialog_is_safe(self):
        hits = dialogs.classify("是否信任此文件夹中的文件的作者？ 是，我信任此作者")
        self.assertEqual(hits[0]["kind"], "safe")
        self.assertIn("是，我信任此作者", hits[0]["labels"])

    def test_login_is_blocked(self):
        hits = dialogs.classify("请先登录后再使用")
        self.assertEqual(hits[0]["kind"], "blocked")
        self.assertEqual(hits[0]["reason"], "需要登录")

    def test_blocked_wins_over_safe(self):
        hits = dialogs.classify("额度不足，请升级套餐。是否信任此作者")
        self.assertEqual([h["kind"] for h in hits[:2]], ["blocked", "blocked"])

    def test_ordinary_text_matches_nothing(self):
        self.assertEqual(dialogs.classify("正在执行中 由 AI 生成"), [])


class HandleTest(unittest.TestCase):
    def setUp(self):
        self.logged = []
        self.clicked = []
        self.shots = 0

    def log(self, event, **fields):
        self.logged.append((event, fields))

    def shot(self):
        self.shots += 1
        return "/tmp/dialog.png"

    def click(self, label):
        self.clicked.append(label)
        return "clicked"

    def test_safe_dialog_is_clicked(self):
        status, detail = dialogs.handle(
            lambda: "是否信任此作者", self.click, self.log, where="start", shot=self.shot)
        self.assertEqual(status, "handled")
        self.assertEqual(self.clicked, ["是，我信任此作者"])
        self.assertEqual(self.logged[0][0], "dialog_handled")

    def test_blocked_dialog_is_not_clicked(self):
        status, detail = dialogs.handle(
            lambda: "额度不足", self.click, self.log, where="idle", shot=self.shot)
        self.assertEqual(status, "blocked")
        self.assertEqual(self.clicked, [])
        self.assertEqual(self.shots, 1)
        self.assertEqual(self.logged[0][0], "dialog_blocked")

    def test_unknown_dialog_stops_with_a_screenshot(self):
        status, detail = dialogs.handle(
            lambda: "普通文本", self.click, self.log, where="idle",
            shot=self.shot, dom=lambda: ["一个没见过的对话框"])
        self.assertEqual(status, "unknown")
        self.assertIn("没见过的对话框", detail["text"])
        self.assertEqual(self.shots, 1)

    def test_no_dialog_no_action(self):
        status, detail = dialogs.handle(
            lambda: "普通文本", self.click, self.log, dom=lambda: [])
        self.assertEqual(status, "ok")
        self.assertIsNone(detail)
        self.assertEqual(self.clicked, [])


if __name__ == "__main__":
    unittest.main()
