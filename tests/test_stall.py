"""Tests for the stall diagnostics (code-eval/tools/stall.py)."""
from __future__ import annotations

import base64
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "code-eval" / "tools"))

import stall  # noqa: E402

# 1x1 transparent PNG; screenshots only need to exist and parse.
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


class FakeCdp:
    """Just enough of driver_core.Cdp for the diagnostics."""

    def __init__(self, visible=(), text="", shot=True):
        self._visible = list(visible)
        self._text = text
        self.take_shot = shot

    def js(self, source, timeout=60):
        if "querySelectorAll" in source:
            return self._visible
        return {"w": 1280, "h": 800}

    def text(self):
        return self._text

    def run(self, op, arg=None, timeout=90, check=False):
        if op == "shot":
            if not self.take_shot:
                return subprocess.CompletedProcess([op], 1, "", "")
            Path(arg).write_bytes(PNG)
        return subprocess.CompletedProcess([op], 0, "", "")


def button(text, x=10, y=20, aria=""):
    return {"text": text, "aria": aria, "x": x, "y": y}


class ClassifyTest(unittest.TestCase):
    def test_terminal_prompt_is_handled_from_the_dom(self):
        report = stall.classify("终端运行 Ctrl ↩", [button("接受"), button("拒绝")], None)
        self.assertEqual(report["verdict"], "handled")
        self.assertEqual(report["label"], "接受")
        self.assertEqual(report["via"], "dom")

    def test_terminal_prompt_is_handled_from_ocr_when_dom_is_empty(self):
        words = [{"text": "接受", "x": 100, "y": 200, "w": 40, "h": 20}]
        report = stall.classify("终端运行", [], words)
        self.assertEqual(report["verdict"], "handled")
        self.assertEqual(report["via"], "ocr")

    def test_trust_prompt_reuses_the_dialog_rules(self):
        report = stall.classify("是否信任此作者", [button("是，我信任此作者")], None)
        self.assertEqual(report["verdict"], "handled")

    def test_login_is_blocked(self):
        report = stall.classify("请先登录后再使用", [], None)
        self.assertEqual(report["verdict"], "blocked")

    def test_plain_page_is_unknown(self):
        self.assertEqual(stall.classify("正在执行中", [button("停止")], None)["verdict"], "unknown")

    def test_accept_alone_does_not_trigger_without_context(self):
        # A bare "接受" on a licence dialog must not be clicked.
        self.assertEqual(stall.classify("服务协议", [button("接受")], None)["verdict"], "blocked")


class ImageTest(unittest.TestCase):
    def test_png_size_reads_the_header(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "a.png"
            path.write_bytes(PNG)
            self.assertEqual(stall.png_size(path), (1, 1))

    def test_identical_bytes_are_the_same_image(self):
        with tempfile.TemporaryDirectory() as tmp:
            one, two = Path(tmp) / "a.png", Path(tmp) / "b.png"
            one.write_bytes(PNG)
            two.write_bytes(PNG)
            self.assertTrue(stall.same_image(one, two))

    def test_identical_pixels_are_the_same_image_despite_extra_bytes(self):
        # PNG metadata / trailing bytes may differ while the picture does not.
        with tempfile.TemporaryDirectory() as tmp:
            one, two = Path(tmp) / "a.png", Path(tmp) / "b.png"
            one.write_bytes(PNG)
            two.write_bytes(PNG + b"x")
            self.assertTrue(stall.same_image(one, two))

    @unittest.skipUnless(stall.HAS_PIL, "Pillow not installed")
    def test_different_pictures_are_not(self):
        from PIL import Image

        with tempfile.TemporaryDirectory() as tmp:
            one, two = Path(tmp) / "a.png", Path(tmp) / "b.png"
            Image.new("L", (8, 8), 0).save(one)
            Image.new("L", (8, 8), 255).save(two)
            self.assertFalse(stall.same_image(one, two))


class DiagnoseTest(unittest.TestCase):
    def test_handled_writes_evidence_and_reports_frozen(self):
        cdp = FakeCdp(visible=[button("接受")], text="终端运行 Ctrl ↩")
        with tempfile.TemporaryDirectory() as tmp:
            report = stall.diagnose(cdp, Path(tmp), "stall1", "终端运行 Ctrl ↩")
            self.assertEqual(report["verdict"], "handled")
            self.assertTrue(report["frozen"])
            self.assertFalse(report["ocr"])  # tesseract is optional
            evidence = Path(report["evidence"])
            self.assertTrue(evidence.is_file())
            text = evidence.read_text(encoding="utf-8")
            self.assertIn("verdict: handled", text)
            self.assertIn("接受 @ 10,20", text)
            self.assertTrue(Path(report["shot"]).is_file())

    def test_dead_when_cdp_gives_nothing(self):
        cdp = FakeCdp(visible=[], text="", shot=False)
        with tempfile.TemporaryDirectory() as tmp:
            report = stall.diagnose(cdp, Path(tmp), "stall1", "")
            self.assertEqual(report["verdict"], "dead")
            self.assertFalse(report["frozen"])
            self.assertTrue(Path(report["evidence"]).is_file())


@unittest.skipUnless(shutil.which("tesseract"), "tesseract not installed")
class OcrTest(unittest.TestCase):
    def test_ocr_returns_words_for_a_png(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "a.png"
            path.write_bytes(PNG)
            words = stall.ocr_words(path)
            self.assertIsNotNone(words)


if __name__ == "__main__":
    unittest.main()
