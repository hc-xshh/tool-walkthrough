"""Screenshot-source tests: Wayland must not silently return an X11 black frame."""
from __future__ import annotations

import os
import pathlib
import sys
import tempfile
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "harness"))

import support  # noqa: E402
import wtshot  # noqa: E402


@unittest.skipUnless(wtshot.OS == "Linux", "Wayland portal is Linux-only")
class WaylandScreenshotTest(unittest.TestCase):
    def test_display_zero_uses_portal_when_session_is_wayland(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = pathlib.Path(tmp) / "shot.png"
            calls = []

            def fake_portal(path):
                calls.append(path)
                pathlib.Path(path).write_bytes(support.TINY_PNG)

            with mock.patch.dict(
                os.environ,
                {"XDG_SESSION_TYPE": "wayland", "WAYLAND_DISPLAY": "wayland-0"},
                clear=False,
            ), mock.patch.object(wtshot, "_portal_screenshot", side_effect=fake_portal), \
               mock.patch.object(wtshot, "_png_size", return_value=(1920, 1080)), \
               mock.patch.object(wtshot, "_x11_size", return_value=(1920, 1080)), \
               mock.patch.object(wtshot, "desktop_metrics", return_value={
                   "origin_x": 0, "origin_y": 0, "width": 1920, "height": 1080,
                   "scale": 1.0, "source": "x11",
               }):
                meta = wtshot.capture_screen(out, ":0", "screen")

            self.assertEqual(len(calls), 1)
            self.assertEqual(meta["source"], "xdg-desktop-portal")
            self.assertEqual((meta["width"], meta["height"]), (1920, 1080))
            self.assertEqual(meta["scale"], 1.0)
            self.assertTrue(out.exists())
            self.assertTrue(pathlib.Path(str(out) + ".json").exists())

    def test_xvfb_keeps_x11grab(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = pathlib.Path(tmp) / "shot.png"

            def fake_run(cmd, **kwargs):
                pathlib.Path(cmd[-1]).write_bytes(support.TINY_PNG)

            with mock.patch.dict(os.environ, {"XDG_SESSION_TYPE": "wayland"}, clear=False), \
               mock.patch.object(wtshot, "_portal_screenshot") as portal, \
               mock.patch.object(wtshot, "subprocess") as subprocess, \
               mock.patch.object(wtshot, "_png_size", return_value=(1440, 900)), \
               mock.patch.object(wtshot, "_x11_size", return_value=(1440, 900)), \
               mock.patch.object(wtshot, "desktop_metrics", return_value={
                   "origin_x": 0, "origin_y": 0, "width": 1440, "height": 900,
                   "scale": 1.0, "source": "x11",
               }):
                subprocess.run.side_effect = fake_run
                meta = wtshot.capture_screen(out, ":98", "screen")

            portal.assert_not_called()
            self.assertEqual(meta["source"], "x11")
            self.assertTrue(out.exists())


if __name__ == "__main__":
    unittest.main()
