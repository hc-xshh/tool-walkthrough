"""Tests for the driver registry: code-eval/drivers.json + tools/drivers.py."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "code-eval" / "tools"))

import drivers  # noqa: E402


class RegistryTest(unittest.TestCase):
    def test_every_listed_driver_has_a_file(self):
        for entry in drivers.load():
            path = ROOT / "code-eval" / "tools" / entry["file"]
            self.assertTrue(path.is_file(), f"{entry['file']} is registered but missing")

    def test_kind_decides_which_field_is_required(self):
        for entry in drivers.load():
            if entry["kind"] == "gui":
                self.assertIsInstance(entry["port"], int, entry["file"])
            else:
                self.assertTrue(entry["command"], entry["file"])

    def test_qoder_declares_workbench_features(self):
        entry = drivers.entry("drive_qoder.py")
        self.assertEqual(entry["allowed_args"], ["--skip-workspace"])
        self.assertEqual(entry["features"], ["open_workspace", "skip_workspace"])

    def test_helpers_agree_with_the_full_list(self):
        entries = drivers.load()
        self.assertEqual(set(drivers.labels()), {e["file"] for e in entries})
        self.assertEqual(set(drivers.gui_ports()), {e["file"] for e in entries if e["kind"] == "gui"})
        self.assertEqual(set(drivers.cli_commands()), {e["file"] for e in entries if e["kind"] == "cli"})
        self.assertEqual(drivers.allowed_args("drive_trae.py"), [])
        self.assertEqual(drivers.features("drive_trae.py"), [])


class ValidationTest(unittest.TestCase):
    def write(self, payload) -> Path:
        tmp = Path(tempfile.mkdtemp()) / "drivers.json"
        tmp.write_text(json.dumps(payload), encoding="utf-8")
        return tmp

    def test_empty_list_is_rejected(self):
        with self.assertRaises(ValueError):
            drivers.load(self.write({"drivers": []}))

    def test_duplicate_file_is_rejected(self):
        entry = {"file": "drive_a.py", "label": "A", "kind": "cli", "command": "a"}
        with self.assertRaises(ValueError):
            drivers.load(self.write({"drivers": [entry, dict(entry)]}))

    def test_gui_without_port_is_rejected(self):
        with self.assertRaises(ValueError):
            drivers.load(self.write({"drivers": [
                {"file": "drive_a.py", "label": "A", "kind": "gui"}]}))

    def test_unknown_kind_is_rejected(self):
        with self.assertRaises(ValueError):
            drivers.load(self.write({"drivers": [
                {"file": "drive_a.py", "label": "A", "kind": "web"}]}))


class SurfaceDriftTest(unittest.TestCase):
    """The two servers must not keep their own copy of the list."""

    def test_workbench_server_derives_from_the_registry(self):
        sys.path.insert(0, str(ROOT / "workbench"))
        import server  # noqa: E402  (imports the workbench modules it needs)

        self.assertEqual(server.DRIVERS, drivers.labels())
        self.assertEqual(server.GUI_PORTS, drivers.gui_ports())
        self.assertEqual(server.CLI_DRIVERS, drivers.cli_commands())

    def test_dashboard_server_derives_from_the_registry(self):
        import serve_dashboard  # noqa: E402

        self.assertEqual(serve_dashboard.DRIVERS, drivers.labels())


if __name__ == "__main__":
    unittest.main()
