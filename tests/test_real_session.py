"""Linux real-session gate tests: a display name alone is not enough."""
from __future__ import annotations

import pathlib
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "harness"))

import wtlib  # noqa: E402


def _proc(text="", rc=0):
    return subprocess.CompletedProcess([], rc, stdout=text, stderr="")


class RealSessionTest(unittest.TestCase):
    def setUp(self):
        wtlib._REAL_SESSION.clear()
        self.addCleanup(wtlib._REAL_SESSION.clear)

    def test_virtual_display_is_rejected_before_loginctl(self):
        with self.assertRaises(SystemExit) as cm:
            wtlib.verify_real_session(":98")
        self.assertIn("virtual displays are disabled", str(cm.exception))

    def test_wayland_session_requires_a_real_socket(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = {
                "XDG_SESSION_TYPE": "wayland",
                "XDG_SESSION_ID": "3",
                "XDG_RUNTIME_DIR": tmp,
                "WAYLAND_DISPLAY": "wayland-0",
            }
            with mock.patch.dict(__import__("os").environ, env, clear=False), \
                 mock.patch.object(wtlib, "which_any", side_effect=lambda names: "/usr/bin/loginctl"
                                   if "loginctl" in names else None), \
                 mock.patch.object(wtlib.subprocess, "run", return_value=_proc(
                     "Type=wayland\nActive=yes\nSeat=seat0\n")):
                with self.assertRaises(SystemExit) as cm:
                    wtlib.verify_real_session(":0")
            self.assertIn("Wayland socket", str(cm.exception))

    def test_active_wayland_session_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            pathlib.Path(tmp, "wayland-0").touch()
            env = {
                "XDG_SESSION_TYPE": "wayland",
                "XDG_SESSION_ID": "3",
                "XDG_RUNTIME_DIR": tmp,
                "WAYLAND_DISPLAY": "wayland-0",
            }
            with mock.patch.dict(__import__("os").environ, env, clear=False), \
                 mock.patch.object(wtlib, "which_any", side_effect=lambda names: "/usr/bin/loginctl"
                                   if "loginctl" in names else None), \
                 mock.patch.object(wtlib.subprocess, "run", return_value=_proc(
                     "Type=wayland\nActive=yes\nSeat=seat0\n")):
                info = wtlib.verify_real_session(":0", refresh=True)
            self.assertEqual(info["type"], "wayland")
            self.assertEqual(info["seat"], "seat0")

    def test_xvfb_x11_output_is_rejected(self):
        calls = []

        def fake_run(cmd, **kwargs):
            calls.append(cmd)
            if "--query" in cmd:
                return _proc("screen connected primary 1920x1080+0+0\n")
            return _proc("Type=x11\nActive=yes\nSeat=seat0\n")

        with mock.patch.dict(__import__("os").environ, {"XDG_SESSION_ID": "3"}, clear=False), \
             mock.patch.object(wtlib, "which_any", side_effect=lambda names: "/usr/bin/" + names[0]), \
             mock.patch.object(wtlib.subprocess, "run", side_effect=fake_run):
            with self.assertRaises(SystemExit) as cm:
                wtlib.verify_real_session(":0", refresh=True)
        self.assertIn("no physical X11 output", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
