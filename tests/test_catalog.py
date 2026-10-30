"""Tests for the read-only product catalog."""
from __future__ import annotations

import json
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
import catalog  # noqa: E402
import drivers  # noqa: E402


class CatalogTest(unittest.TestCase):
    def setUp(self):
        self.env = mock.patch.dict(os.environ, {"WT_CATALOG": str(ROOT / "catalog")})
        self.env.start()

    def tearDown(self):
        self.env.stop()

    def test_builtin_catalog_loads_without_errors(self):
        data = catalog.load()
        self.assertEqual(data["errors"], [])
        self.assertGreaterEqual(len(data["families"]), 4)
        ids = [family["id"] for family in data["families"]]
        self.assertEqual(len(ids), len(set(ids)))
        for family in data["families"]:
            self.assertTrue(family["name"])
            self.assertTrue(family["vendor"])
            for product in family["products"]:
                self.assertIn(product["form"], catalog.FORMS)

    def test_app_and_driver_references_exist(self):
        data = catalog.load()
        app_ids = set(apps.all_apps())
        driver_ids = set(drivers.labels())
        for family in data["families"]:
            for product in family["products"]:
                for surface in product["surfaces"]:
                    if surface["app_id"]:
                        self.assertIn(surface["app_id"], app_ids,
                                      f"{family['id']}/{product['id']} app")
                    if surface["driver_id"]:
                        self.assertIn(surface["driver_id"], driver_ids,
                                      f"{family['id']}/{product['id']} driver")

    def test_bad_file_is_reported_not_fatal(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "bad.json").write_text("{not json", encoding="utf-8")
            (root / "good.json").write_text(json.dumps({
                "id": "demo", "name": "Demo", "vendor": "Demo Inc",
                "products": [],
            }), encoding="utf-8")
            with mock.patch.dict(os.environ, {"WT_CATALOG": str(root)}):
                data = catalog.load()
        self.assertEqual([f["id"] for f in data["families"]], ["demo"])
        self.assertEqual(len(data["errors"]), 1)


if __name__ == "__main__":
    unittest.main()
