"""Target selection for cdp.py.

Qoder exposes `desktop-pet` first, `renderer` second and an empty page third.
`pages[0]` attached to the pet, so `cdp.py text` printed nothing. Keep the
scoring rule covered so a new helper page cannot silently steal the target.
"""
import pathlib
import subprocess
import sys
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "harness"))

import cdp  # noqa: E402


class PickTargetTest(unittest.TestCase):
    def test_prefers_renderer_over_pet_and_empty(self):
        tabs = [
            {"type": "page",
             "url": "qoder-cn-app://fixed-surface/index.html?surface=desktop-pet",
             "title": "Qoder Desktop Pet"},
            {"type": "page",
             "url": "qoder-cn-app://renderer/index.html?workbenchScope=primary#/chat/1",
             "title": "Qoder"},
            {"type": "page", "url": "", "title": ""},
        ]
        picked = cdp.pick_target(tabs)
        self.assertIn("renderer", picked["url"])

    def test_match_still_wins(self):
        tabs = [
            {"type": "page", "url": "app://renderer/index.html", "title": ""},
            {"type": "page", "url": "app://renderer/plugins.html", "title": ""},
        ]
        picked = cdp.pick_target(tabs, match="plugins")
        self.assertIn("plugins", picked["url"])

    def test_require_real_window_rejects_missing_window(self):
        missing = subprocess.CompletedProcess([], 1, stdout="", stderr="")
        with mock.patch.object(cdp.shutil, "which", return_value="/usr/bin/xdotool"), \
             mock.patch.object(cdp.subprocess, "run", return_value=missing):
            with self.assertRaises(SystemExit) as cm:
                cdp.require_real_window("Headless Check")
        self.assertIn("headless/virtual targets are disabled", str(cm.exception))

    def test_require_real_window_accepts_visible_window(self):
        found = subprocess.CompletedProcess([], 0, stdout="12345\n", stderr="")
        with mock.patch.object(cdp.shutil, "which", return_value="/usr/bin/xdotool"), \
             mock.patch.object(cdp.subprocess, "run", return_value=found):
            cdp.require_real_window("Visible Check")

    def test_title_match_separates_two_windows(self):
        tabs = [
            {"type": "page", "url": "vscode-file://vscode-app/x/workbench",
             "title": "Qoder CN IDE"},
            {"type": "page", "url": "vscode-file://vscode-app/x/workbench",
             "title": "L1-split-bill-r1 - Qoder CN IDE"},
        ]
        picked = cdp.pick_target(tabs, title_match="L1-split-bill-r1")
        self.assertIn("L1-split-bill-r1", picked["title"])
        self.assertIsNone(cdp.pick_target(tabs, title_match="not-there"))

    def test_two_windows_with_the_same_title_are_refused(self):
        # Qoder restores its last windows on launch; two identical titles used
        # to be resolved by score, so the driver could attach to a stale one.
        tabs = [
            {"type": "page", "url": "vscode-file://a", "title": "money.py - L1-x - Qoder CN IDE"},
            {"type": "page", "url": "vscode-file://b", "title": "money.py - L1-x - Qoder CN IDE"},
        ]
        with self.assertRaises(cdp.AmbiguousTarget) as cm:
            cdp.pick_target(tabs, title_match="L1-x")
        self.assertIn("2 windows match", str(cm.exception))
        self.assertIn("close the extra window", str(cm.exception))

    def test_no_target_returns_none(self):
        self.assertIsNone(cdp.pick_target([], None))
        self.assertIsNone(cdp.pick_target(
            [{"type": "worker", "url": "app://renderer/index.html"}], None))


if __name__ == "__main__":
    unittest.main()
