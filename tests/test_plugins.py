"""Tests for user-added integrations: custom apps and eval drivers."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "workbench"))
sys.path.insert(0, str(ROOT / "code-eval" / "tools"))

import apps  # noqa: E402
import drivers  # noqa: E402
import plugins  # noqa: E402


class CustomIntegrationTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.plugins_file = self.base / "plugins.json"
        self.env = mock.patch.dict(os.environ, {"WT_PLUGINS": str(self.plugins_file)})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def test_custom_app_is_merged_and_removed(self):
        app = apps.add_custom({"label": "Demo App", "exe": sys.executable, "port": 9333})
        self.assertTrue(app["custom"])
        self.assertTrue(app["installed"])
        self.assertEqual(app["port"], 9333)
        self.assertIn(app["id"], apps.all_apps())
        self.assertTrue(plugins.path().is_file())
        self.assertTrue(apps.remove_custom(app["id"]))
        self.assertNotIn(app["id"], apps.all_apps())

    def test_builtin_app_can_take_an_executable_override(self):
        before = apps.status("cursor")
        self.assertFalse(before["installed"])
        app = apps.add_custom({"id": "cursor", "exe": sys.executable})
        self.assertTrue(app["overridden"])
        self.assertTrue(app["installed"])
        self.assertEqual(app["port"], 9562)
        self.assertTrue(apps.remove_custom("cursor"))
        self.assertFalse(apps.status("cursor")["installed"])

    def test_duplicate_debug_port_is_refused(self):
        apps.add_custom({"label": "Demo One", "exe": sys.executable, "port": 9333})
        with self.assertRaises(ValueError):
            apps.add_custom({"label": "Demo Two", "exe": sys.executable, "port": 9333})

    def test_custom_driver_is_merged_and_removed(self):
        script = self.base / "drive_demo.py"
        script.write_text("print('demo')\n", encoding="utf-8")
        entry = plugins.add_driver({
            "label": "Demo Driver", "kind": "gui", "port": 9333,
            "file": str(script), "features": ["skip_workspace"],
        })
        self.assertTrue(entry["custom"])
        self.assertEqual(entry["allowed_args"], ["--skip-workspace"])
        state = {item["id"]: item for item in drivers.state()}
        self.assertIn(str(script.resolve()), state)
        self.assertTrue(state[str(script.resolve())]["custom"])
        self.assertIn(str(script.resolve()), drivers.labels())
        self.assertTrue(plugins.remove_driver(str(script.resolve())))
        self.assertNotIn(str(script.resolve()), drivers.labels())

    def test_discovered_products_are_upserted_and_removed(self):
        entry = {"id": "disc-demo", "query": "Demo", "name": "Demo Work",
                 "vendor": "Demo Inc", "sources": [{"url": "https://example.test"}]}
        plugins.upsert_discovered(entry)
        items = plugins.list_discovered()
        self.assertEqual([item["name"] for item in items], ["Demo Work"])
        plugins.upsert_discovered({**entry, "positioning": "updated"})
        items = plugins.list_discovered()
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["positioning"], "updated")
        self.assertTrue(plugins.remove_discovered("disc-demo"))
        self.assertEqual(plugins.list_discovered(), [])

    def test_driver_script_must_exist(self):
        with self.assertRaises(ValueError):
            plugins.add_driver({
                "label": "Missing", "kind": "cli", "command": "demo",
                "file": str(self.base / "does-not-exist.py"),
            })


if __name__ == "__main__":
    unittest.main()
