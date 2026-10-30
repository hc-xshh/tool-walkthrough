"""Tests for the dimensions / scenarios / runs / report model."""
from __future__ import annotations

import json
import os
import pathlib
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "workbench"))

import survey  # noqa: E402


def _product(name="Qoder CN IDE", version="0.4.9"):
    return {"id": "qoder-ide", "name": name, "family": "Qoder CN",
            "version": version, "model": "m"}


class SurveyTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = pathlib.Path(self.tmp.name)
        self.env = mock.patch.dict(os.environ, {"WT_SURVEY": str(self.base / "survey.json")})
        self.env.start()
        self.runs = self.base / "runs"

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    # ---- store ----

    def test_seed_has_eight_dimensions_and_one_comprehensive_scenario(self):
        data = survey.load()
        self.assertEqual(len(data["dimensions"]), 8)
        self.assertEqual(len(data["scenarios"]), 1)
        scenario = data["scenarios"][0]
        self.assertEqual({d["id"] for d in data["dimensions"]}, set(scenario["dimensions"]))
        self.assertGreaterEqual(len(scenario["prompts"]), 3)  # 多轮对话
        self.assertFalse(survey.store_path().exists())  # reading does not write

    def test_save_is_0600_and_round_trips(self):
        data = survey.load()
        data["dimensions"][0]["note"] = "改过"
        path = survey.save(data)
        if os.name == "posix":
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        self.assertEqual(survey.load()["dimensions"][0]["note"], "改过")

    def test_broken_rows_are_dropped_not_fatal(self):
        survey.store_path().parent.mkdir(parents=True, exist_ok=True)
        survey.store_path().write_text(json.dumps({
            "dimensions": [{"id": "Bad Id", "name": "x", "indicators": []},
                           {"id": "ok", "name": "好的", "indicators": [
                               {"key": "n", "label": "n", "unit": "count"}]}],
            "scenarios": [{"id": "s", "title": "t", "dimensions": ["missing"]}],
        }), encoding="utf-8")
        data = survey.load()
        self.assertEqual([d["id"] for d in data["dimensions"]], ["ok"])
        self.assertEqual(data["scenarios"], [])

    # ---- dimensions ----

    def test_dimension_needs_indicators(self):
        with self.assertRaises(ValueError):
            survey.upsert_dimension({"id": "x", "name": "空维度", "indicators": []})

    def test_dimension_rejects_duplicate_indicator_keys(self):
        with self.assertRaises(ValueError):
            survey.upsert_dimension({"id": "x", "name": "x", "indicators": [
                {"key": "a", "label": "a", "unit": "count"},
                {"key": "a", "label": "b", "unit": "count"},
            ]})

    def test_upsert_updates_in_place(self):
        before = survey.load()
        before_ids = [d["id"] for d in before["dimensions"]]
        data = survey.upsert_dimension({
            "id": "speed", "name": "速度（改名）",
            "indicators": [{"key": "first_token_ms", "label": "首 token", "unit": "ms",
                            "method": "script"}],
        })
        self.assertEqual([d["id"] for d in data["dimensions"]], before_ids)
        self.assertEqual(data["dimensions"][4]["name"], "速度（改名）")

    def test_delete_dimension_strips_it_from_scenarios(self):
        data = survey.delete_dimension("speed")
        self.assertIsNone(survey.find_dimension(data, "speed"))
        for scenario in data["scenarios"]:
            self.assertNotIn("speed", scenario["dimensions"])
        with self.assertRaises(ValueError):
            survey.delete_dimension("speed")

    # ---- scenarios ----

    def test_scenario_must_reference_known_dimensions(self):
        with self.assertRaises(ValueError):
            survey.upsert_scenario({"id": "s1", "title": "s", "dimensions": ["nope"]})

    def test_command_scenario_needs_argv(self):
        with self.assertRaises(ValueError):
            survey.upsert_scenario({"id": "s1", "title": "s", "kind": "command",
                                    "dimensions": ["speed"], "command": {"argv": []}})

    def test_command_scenario_keeps_timeout(self):
        data = survey.upsert_scenario({
            "id": "probe", "title": "探针", "kind": "command",
            "dimensions": ["speed"], "command": {"argv": ["true"], "timeout_s": 30},
        })
        scenario = survey.find_scenario(data, "probe")
        self.assertEqual(scenario["command"]["timeout_s"], 30)
        self.assertEqual(scenario["command"]["argv"], ["true"])

    def test_scenario_prompts_are_turns(self):
        with self.assertRaises(ValueError):
            survey.upsert_scenario({"id": "s1", "title": "s", "dimensions": ["speed"],
                                    "prompts": "不是数组"})
        data = survey.upsert_scenario({"id": "s1", "title": "s", "dimensions": ["speed"],
                                       "prompts": ["  第一轮  ", " ", "第二轮"]})
        self.assertEqual(survey.find_scenario(data, "s1")["prompts"], ["第一轮", "第二轮"])

    # ---- coverage ----

    def _toy(self):
        dims = [{"id": "a", "name": "A"}, {"id": "b", "name": "B"}, {"id": "c", "name": "C"}]
        scenarios = [
            {"id": "s1", "title": "s1", "dimensions": ["a"]},
            {"id": "s2", "title": "s2", "dimensions": ["a", "b"]},
            {"id": "s3", "title": "s3", "dimensions": ["c"]},
        ]
        return {"dimensions": dims, "scenarios": scenarios}

    def test_coverage_picks_the_smallest_set(self):
        plan = survey.coverage(["a", "b", "c"], self._toy())
        self.assertEqual([s["id"] for s in plan["scenarios"]], ["s2", "s3"])
        self.assertEqual(plan["uncovered"], [])

    def test_coverage_reports_uncovered_and_unknown(self):
        plan = survey.coverage(["a", "c", "ghost"], {"dimensions": self._toy()["dimensions"],
                                                    "scenarios": [{"id": "s1", "title": "s1",
                                                                   "dimensions": ["a"]}]})
        self.assertEqual(plan["uncovered"], ["c"])
        self.assertEqual(plan["unknown"], ["ghost"])

    def test_coverage_is_deterministic(self):
        first = [s["id"] for s in survey.coverage(["a", "b"], self._toy())["scenarios"]]
        second = [s["id"] for s in survey.coverage(["a", "b"], self._toy())["scenarios"]]
        self.assertEqual(first, second)

    # ---- runs ----

    def _record(self, run_id="r1", version="0.4.9", values=None, method="human"):
        data = survey.load()
        scenario = survey.find_scenario(data, "full-delivery")
        values = values or {"first_token_ms": "1200", "suggestion_accept": "是"}
        measurements = survey.build_measurements(scenario, data["dimensions"], values, method)
        record = {
            "run_id": run_id, "ts": survey.now(), "product": _product(version=version),
            "scenario": {"id": scenario["id"], "title": scenario["title"]},
            "dimensions": scenario["dimensions"], "status": "ok", "method": method,
            "confidence": "single", "measurements": measurements,
            "snapshot": survey.snapshot(scenario, data["dimensions"]),
        }
        survey.write_run(record, self.runs)
        return record

    def test_write_and_read_run(self):
        self._record()
        runs = survey.list_runs(self.runs)
        self.assertEqual([r["run_id"] for r in runs], ["r1"])
        self.assertEqual(survey.load_run("r1", self.runs)["product"]["id"], "qoder-ide")
        self.assertIsNone(survey.load_run("missing", self.runs))

    def test_build_measurements_rejects_unknown_indicator(self):
        data = survey.load()
        scenario = survey.find_scenario(data, "full-delivery")
        with self.assertRaises(ValueError):
            survey.build_measurements(scenario, data["dimensions"], {"typo": 1})

    def test_build_measurements_coerces_units(self):
        data = survey.load()
        scenario = survey.find_scenario(data, "full-delivery")
        out = survey.build_measurements(scenario, data["dimensions"], {
            "first_token_ms": "1.5", "suggestion_accept": "否", "quality": "4",
        })
        by_key = {m["indicator"]: m["value"] for m in out}
        self.assertEqual(by_key["first_token_ms"], 1.5)
        self.assertIs(by_key["suggestion_accept"], False)
        self.assertEqual(by_key["quality"], 4)

    def test_build_measurements_skips_blank_values(self):
        data = survey.load()
        scenario = survey.find_scenario(data, "full-delivery")
        out = survey.build_measurements(scenario, data["dimensions"], {
            "first_token_ms": "", "quality": None,
        })
        self.assertEqual(out, [])

    # ---- matrix / report ----

    def test_matrix_groups_by_product_and_version(self):
        self._record("r1", version="0.4.9", values={"first_token_ms": "1000"})
        self._record("r2", version="0.5.0", values={"first_token_ms": "800"})
        table = survey.matrix(None, self.runs)
        labels = [p["label"] for p in table["products"]]
        self.assertEqual(labels, ["Qoder CN IDE 0.4.9", "Qoder CN IDE 0.5.0"])
        cell = table["cells"]["speed|qoder-ide|0.4.9"]
        self.assertEqual(cell["items"][0]["text"], "1000")

    def test_matrix_aggregates_sum_across_runs(self):
        self._record("r1", values={"first_token_ms": "1000"})
        self._record("r2", values={"first_token_ms": "1400"})
        table = survey.matrix(["inline-completion"], self.runs)
        cell = table["cells"]["inline-completion|qoder-ide|0.4.9"]
        first = next(i for i in cell["items"] if i["indicator"] == "first_token_ms")
        self.assertEqual(first["value"], 1400)  # aggregate=last
        self.assertEqual(first["count"], 2)

    def test_matrix_marks_empty_dimensions(self):
        table = survey.matrix(["speed"], self.runs)
        self.assertEqual(table["missing"], ["speed"])
        self.assertEqual(table["cells"], {})

    def test_report_markdown_mentions_values_and_gaps(self):
        self._record()
        table = survey.matrix(None, self.runs)
        text = survey.report_markdown("Qoder 画像", table)
        self.assertIn("# Qoder 画像", text)
        self.assertIn("1200ms", text)
        self.assertIn("还没有任何数据", text)
        self.assertIn("n=1 是观察", text)

    def test_export_writes_a_markdown_file(self):
        self._record()
        out = survey.export_report("画像", None, self.runs)
        path = pathlib.Path(out["path"])
        self.assertTrue(path.is_file())
        self.assertIn("Qoder", path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()


class BatchTest(unittest.TestCase):
    """survey_batch.py: one scenario, several products, sequential."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = pathlib.Path(self.tmp.name)
        self.runs = self.base / "runs"
        self.env = mock.patch.dict(os.environ, {"WT_SURVEY": str(self.base / "survey.json")})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def _write_spec(self, products):
        code = (
            "import json,os,sys;"
            "pid=os.environ['WT_PRODUCT_ID'];"
            "print(json.dumps({'first_token_ms': 100 if pid=='a' else 200, 'notes': pid}));"
            "sys.exit(1 if pid=='b' else 0)"
        )
        scenario = {
            "id": "probe", "title": "探针", "kind": "command",
            "dimensions": ["speed"], "brief": "b", "prompts": ["第一轮", "第二轮"],
            "command": {"argv": [sys.executable, "-c", code], "timeout_s": 30, "cwd": ""},
        }
        spec = {"batch_id": "b1", "scenario": scenario, "products": products,
                "dimensions": survey.load()["dimensions"], "runs_root": str(self.runs)}
        path = self.base / "spec.json"
        path.write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")
        return path

    def test_runs_every_product_and_keeps_going_after_a_failure(self):
        products = [
            {"id": "a", "name": "A", "version": "1"},
            {"id": "b", "name": "B", "version": "2"},
        ]
        path = self._write_spec(products)
        proc = subprocess.run(
            [sys.executable, str(ROOT / "workbench" / "survey_batch.py"), "--spec", str(path)],
            cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8", errors="replace")
        self.assertEqual(proc.returncode, 0, proc.stderr)

        runs = survey.list_runs(self.runs)
        by_product = {r["product"]["id"]: r for r in runs}
        self.assertEqual(set(by_product), {"a", "b"})
        self.assertEqual(by_product["a"]["status"], "ok")
        self.assertEqual(by_product["b"]["status"], "failed")
        self.assertEqual(by_product["b"]["measurements"][0]["value"], 200)

        prompts = self.runs / "survey" / by_product["a"]["run_id"] / "prompts.json"
        self.assertEqual(json.loads(prompts.read_text(encoding="utf-8")), ["第一轮", "第二轮"])
        batch = json.loads((self.runs / "survey" / "b1" / "batch.json").read_text(encoding="utf-8"))
        self.assertEqual(len(batch["results"]), 2)
