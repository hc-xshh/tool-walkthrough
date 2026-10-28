"""Target selection for cdp.py.

Qoder exposes `desktop-pet` first, `renderer` second and an empty page third.
`pages[0]` attached to the pet, so `cdp.py text` printed nothing. Keep the
scoring rule covered so a new helper page cannot silently steal the target.
"""
import pathlib
import sys
import unittest

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

    def test_no_target_returns_none(self):
        self.assertIsNone(cdp.pick_target([], None))
        self.assertIsNone(cdp.pick_target(
            [{"type": "worker", "url": "app://renderer/index.html"}], None))


if __name__ == "__main__":
    unittest.main()
