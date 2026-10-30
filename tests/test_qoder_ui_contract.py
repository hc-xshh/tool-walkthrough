"""Replay drive_qoder's matchers against a recorded Qoder CN 1.37 DOM.

The 2026-10-30 failure was a UI change: the run button became "终端运行
Ctrl ↩" and "正在执行中" disappeared. Unit tests on pure helpers never
executed the JS that looks for those controls, so this test runs the driver's
own JS against nodes recorded from the live app (tests/fixtures/).
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "tests" / "fixtures" / "qoder-1.37-ui.json"
REPLAY = ROOT / "tests" / "dom_replay.mjs"
sys.path.insert(0, str(ROOT / "code-eval" / "tools"))

import drive_qoder  # noqa: E402


class FakeCdp:
    def __init__(self):
        self.source = ""
        self.reply = None

    def js(self, source, timeout=60):
        self.source = source
        return self.reply


def matcher_source(call):
    """Run `call` with a fake CDP and return the JS it would have sent."""
    fake = FakeCdp()
    original = drive_qoder.CDP
    drive_qoder.CDP = fake
    try:
        call()
    finally:
        drive_qoder.CDP = original
    return fake.source


@unittest.skipUnless(shutil.which("node"), "node not installed")
class RecordedDomTest(unittest.TestCase):
    def replay(self, source, scene, tmp):
        js = Path(tmp) / "matcher.js"
        js.write_text(source, encoding="utf-8")
        proc = subprocess.run(
            [shutil.which("node"), str(REPLAY), str(js), str(FIXTURE), scene],
            capture_output=True, text=True, timeout=60,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return json.loads(proc.stdout)

    def test_run_button_is_clicked_and_the_auto_run_switch_is_not(self):
        # The switch sits a few pixels from the run button; a coordinate click
        # that drifts hits it and asks to enable auto-run for the whole app.
        source = matcher_source(drive_qoder.click_run_confirm)
        with tempfile.TemporaryDirectory() as tmp:
            out = self.replay(source, "run_prompt", tmp)
        self.assertEqual(out["result"], "终端运行 Ctrl ↩")
        self.assertEqual(out["clicked"], ["终端运行 Ctrl ↩"])

    def test_modal_blocks_the_run_button_behind_it(self):
        source = matcher_source(drive_qoder.click_run_confirm)
        with tempfile.TemporaryDirectory() as tmp:
            out = self.replay(source, "auto_exec_dialog", tmp)
        self.assertIsNone(out["result"])
        self.assertEqual(out["clicked"], [])

    def test_composer_state_reads_the_send_button(self):
        source = matcher_source(drive_qoder.composer_state)
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(self.replay(source, "running_composer", tmp)["result"], "running")
            self.assertEqual(self.replay(source, "idle_composer", tmp)["result"], "idle")


if __name__ == "__main__":
    unittest.main()
