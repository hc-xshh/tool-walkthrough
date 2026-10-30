"""Tests for the one-sentence product discovery helpers."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "workbench"))

import apps  # noqa: E402
import discover  # noqa: E402


class DiscoverTest(unittest.TestCase):
    def test_query_is_cleaned(self):
        self.assertEqual(discover.clean_query("加上 Kimi Work"), "Kimi Work")
        self.assertEqual(discover.clean_query("添加 Cursor"), "Cursor")
        self.assertEqual(discover.clean_query("接入 Qoder。"), "Qoder")

    def test_catalog_match_uses_family_names_and_aliases(self):
        family, _ = discover.match_catalog("Qoder")
        self.assertEqual(family["id"], "qoder-cn")
        family, _ = discover.match_catalog("Lingma")
        self.assertEqual(family["id"], "qoder-cn")
        family, _ = discover.match_catalog("Kimi Work")
        self.assertIsNone(family)

    def test_desktop_entry_detection_does_not_launch_anything(self):
        with tempfile.TemporaryDirectory() as tmp:
            desktop = Path(tmp) / "demo-work.desktop"
            desktop.write_text(
                "[Desktop Entry]\nName=Demo Work\nExec=/bin/true %U\n"
                "Type=Application\nNoDisplay=false\n", encoding="utf-8")
            with mock.patch.object(discover, "desktop_entries", return_value=[desktop]):
                found = discover.detect_local("Demo Work")
        self.assertIsNotNone(found)
        self.assertEqual(found["kind"], "gui")
        self.assertEqual(found["exe"], "/bin/true")

    def test_connect_gui_adds_a_custom_app(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = mock.patch.dict(os.environ, {"WT_PLUGINS": str(Path(tmp) / "plugins.json")})
            env.start()
            try:
                app_id, cli, note = discover.connect_local("Demo Work", {
                    "label": "Demo Work", "exe": "/bin/true", "kind": "gui",
                })
                self.assertTrue(app_id.startswith("custom-"))
                self.assertEqual(cli, "")
                self.assertIn("GUI", note)
                self.assertTrue(apps.status(app_id)["installed"])
                apps.remove_custom(app_id)
            finally:
                env.stop()

    def test_llm_failure_falls_back_to_search_snippet(self):
        cfg = {"llm": {"api_key": ""}, "web": {}}
        info = discover.extract_with_llm("Kimi Work", [
            {"title": "Kimi Work", "url": "https://example.test/kimi",
             "snippet": "Kimi Work is a work surface."},
        ], cfg)
        self.assertEqual(info["name"], "Kimi Work")
        self.assertEqual(info["homepage"], "https://example.test/kimi")
        self.assertIn("work surface", info["positioning"])


if __name__ == "__main__":
    unittest.main()
