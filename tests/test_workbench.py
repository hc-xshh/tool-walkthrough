"""Tests for the local workbench: config file, redaction, job lifecycle."""
from __future__ import annotations

import json
import os
import pathlib
import stat
import sys
import tempfile
import time
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "workbench"))

import apps  # noqa: E402
import config  # noqa: E402
import deps  # noqa: E402
import server  # noqa: E402
import jobs  # noqa: E402


class ConfigTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = pathlib.Path(self.tmp.name) / "config.json"
        self.env = mock.patch.dict(os.environ, {"WT_CONFIG": str(self.path)})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def test_save_then_read_back(self):
        config.save({"base_url": "https://example.test/v1", "model": "m1",
                     "api_key": "sk-secret-abcd", "timeout": 30})
        data = config.load()
        self.assertEqual(data["llm"]["model"], "m1")
        self.assertEqual(data["llm"]["api_key"], "sk-secret-abcd")
        self.assertEqual(data["llm"]["timeout"], 30)

    def test_public_never_returns_the_key(self):
        config.save({"api_key": "sk-secret-abcd"})
        public = config.public()
        self.assertTrue(public["configured"])
        self.assertNotIn("api_key", public)
        self.assertNotIn("sk-secret-abcd", json.dumps(public))
        self.assertEqual(public["key_hint"], "****abcd")

    def test_file_is_0600(self):
        if os.name != "posix":
            self.skipTest("POSIX permissions only")
        path = config.write(config.load())
        mode = stat.S_IMODE(path.stat().st_mode)
        self.assertEqual(mode, 0o600)
        self.assertEqual(stat.S_IMODE(path.parent.stat().st_mode), 0o700)

    def test_empty_key_keeps_the_stored_one(self):
        config.save({"api_key": "sk-keep-abcd"})
        config.save({"api_key": "", "model": "m2"})
        data = config.load()
        self.assertEqual(data["llm"]["api_key"], "sk-keep-abcd")
        self.assertEqual(data["llm"]["model"], "m2")

    def test_bad_base_url_is_rejected(self):
        with self.assertRaises(ValueError):
            config.save({"base_url": "ftp://example.test"})
        self.assertFalse(self.path.exists())

    def test_child_env_has_key_but_argv_does_not(self):
        config.save({"api_key": "sk-secret-abcd", "base_url": "https://example.test/v1"})
        env = config.child_env()
        self.assertEqual(env["WT_LLM_API_KEY"], "sk-secret-abcd")
        self.assertEqual(env["WT_LLM_BASE_URL"], "https://example.test/v1")

    def test_search_key_is_write_only_and_independent(self):
        config.save({"llm": {"api_key": "sk-llm-abcd"},
                     "web": {"provider": "tavily", "api_key": "tv-search-wxyz",
                             "max_results": 3}})
        data = config.load()
        self.assertEqual(data["llm"]["api_key"], "sk-llm-abcd")
        self.assertEqual(data["web"]["api_key"], "tv-search-wxyz")
        self.assertEqual(data["web"]["max_results"], 3)
        public = config.public()
        self.assertTrue(public["web"]["configured"])
        self.assertNotIn("api_key", public["web"])
        self.assertNotIn("tv-search-wxyz", json.dumps(public))
        self.assertEqual(public["web"]["key_hint"], "****wxyz")

    def test_empty_search_key_keeps_the_stored_one(self):
        config.save({"web": {"provider": "exa", "api_key": "exa-keep-abcd"}})
        config.save({"web": {"provider": "exa", "api_key": "", "max_results": 4}})
        data = config.load()
        self.assertEqual(data["web"]["api_key"], "exa-keep-abcd")
        self.assertEqual(data["web"]["max_results"], 4)

    def test_bad_search_provider_is_rejected(self):
        with self.assertRaises(ValueError):
            config.save({"web": {"provider": "google", "api_key": "x"}})

    def test_deepseek_search_reuses_the_model_key(self):
        config.save({"base_url": "https://api.deepseek.com",
                     "model": "deepseek-v4-flash", "api_key": "sk-ds-abcd"})
        public = config.public()
        self.assertTrue(public["web"]["configured"])
        self.assertTrue(public["web"]["reused"])
        self.assertEqual(public["web"]["key_hint"], "****abcd")
        self.assertEqual(config.effective_search_key(), "sk-ds-abcd")

    def test_non_deepseek_model_does_not_reuse_its_key(self):
        config.save({"base_url": "https://api.openai.com/v1",
                     "model": "gpt-4o-mini", "api_key": "sk-oai-abcd"})
        public = config.public()
        self.assertFalse(public["web"]["configured"])
        self.assertFalse(public["web"]["reused"])
        self.assertEqual(config.effective_search_key(), "")

    def test_switching_provider_clears_the_old_key(self):
        config.save({"web": {"provider": "exa", "api_key": "exa-key-abcd"}})
        config.save({"web": {"provider": "deepseek", "max_results": 5}})
        self.assertEqual(config.load()["web"]["api_key"], "")


class AppsTest(unittest.TestCase):
    def test_unknown_app_is_a_key_error(self):
        with self.assertRaises(KeyError):
            apps.status("not-an-app")

    def test_status_shape(self):
        info = apps.status("qoder")
        self.assertEqual(info["port"], 9444)
        for key in ("installed", "running", "port_open", "pid", "debug_flag"):
            self.assertIn(key, info)

    def test_launch_without_restart_refuses_a_running_app(self):
        with mock.patch.object(apps, "status", return_value={
                "id": "qoder", "label": "Qoder CN", "installed": True,
                "exe": "/bin/true", "port": 9444, "port_open": False,
                "running": True, "pid": 1234, "debug_flag": False,
                "can_open_folder": True}):
            with self.assertRaises(ValueError) as ctx:
                apps.launch("qoder", restart=False)
        self.assertIn("重启", str(ctx.exception))

    def test_launch_restart_replaces_a_running_instance(self):
        # The button has to work while the app is up: restarting is how a user
        # clears stale windows (two windows with one task name break the driver).
        running = {"id": "qoder", "label": "Qoder CN", "installed": True,
                   "exe": "/bin/true", "port": 9444, "port_open": True,
                   "running": True, "pid": 1234, "debug_flag": True,
                   "can_open_folder": True}
        with mock.patch.object(apps, "status", return_value=running), \
                mock.patch.object(apps, "_processes", side_effect=[[(1234, "cmd")], [], []]), \
                mock.patch.object(apps, "_port_open", return_value=True), \
                mock.patch.object(apps.subprocess, "Popen",
                                  return_value=mock.Mock(pid=4321)) as popen, \
                mock.patch.object(apps.os, "kill") as kill:
            result = apps.launch("qoder", restart=True)
        kill.assert_called_once_with(1234, apps.signal.SIGTERM)
        popen.assert_called_once()
        self.assertEqual(result["action"], "launched")

    def test_launch_without_restart_is_a_noop_while_the_port_is_open(self):
        running = {"id": "qoder", "label": "Qoder CN", "installed": True,
                   "exe": "/bin/true", "port": 9444, "port_open": True,
                   "running": True, "pid": 1234, "debug_flag": True,
                   "can_open_folder": True}
        with mock.patch.object(apps, "status", return_value=running):
            self.assertEqual(apps.launch("qoder", restart=False)["action"], "already")

    def test_open_folder_closes_a_stale_window_with_the_same_name(self):
        opened = {"id": "qoder", "label": "Qoder CN", "installed": True,
                  "exe": "/bin/true", "port": 9444, "port_open": True,
                  "running": True, "pid": 1234, "debug_flag": True,
                  "can_open_folder": True}
        stale = {"id": "old", "title": "money.py - L1-split-bill-r1 - Qoder CN IDE"}
        fresh = {"id": "new", "title": "money.py - L1-split-bill-r1 - Qoder CN IDE"}
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "L1-split-bill-r1"
            path.mkdir()
            with mock.patch.object(apps, "status", return_value=opened), \
                    mock.patch.object(apps, "APPS",
                                      {"qoder": {**apps.APPS["qoder"], "open": ["/bin/true"]}}), \
                    mock.patch.object(apps, "subprocess",
                                      mock.Mock(Popen=mock.Mock(return_value=mock.Mock(pid=1)))), \
                    mock.patch.object(apps, "_close_target", return_value=True) as close, \
                    mock.patch.object(apps, "_port_open", return_value=True), \
                    mock.patch.object(apps, "_page_targets",
                                      side_effect=[[stale], [], [], [fresh]]):
                result = apps.open_folder("qoder", path)
        close.assert_called_once_with(9444, "old")
        self.assertTrue(result["verified"])
        self.assertEqual(result["target_id"], "new")

    def test_open_folder_relaunches_the_app_when_closing_quit_it(self):
        # Closing the last window ends the app; the `-n` call would then start
        # an instance without the debug port and the run could not drive it.
        opened = {"id": "qoder", "label": "Qoder CN", "installed": True,
                  "exe": "/bin/true", "port": 9444, "port_open": True,
                  "running": True, "pid": 1234, "debug_flag": True,
                  "can_open_folder": True}
        stale = {"id": "old", "title": "money.py - L1-split-bill-r1 - Qoder CN IDE"}
        fresh = {"id": "new", "title": "money.py - L1-split-bill-r1 - Qoder CN IDE"}
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "L1-split-bill-r1"
            path.mkdir()
            with mock.patch.object(apps, "status", return_value=opened), \
                    mock.patch.object(apps, "APPS",
                                      {"qoder": {**apps.APPS["qoder"], "open": ["/bin/true"]}}), \
                    mock.patch.object(apps, "subprocess",
                                      mock.Mock(Popen=mock.Mock(return_value=mock.Mock(pid=1)))), \
                    mock.patch.object(apps, "_close_target", return_value=True), \
                    mock.patch.object(apps, "_port_open",
                                      side_effect=[False, False, True]), \
                    mock.patch.object(apps, "launch") as launch, \
                    mock.patch.object(apps, "_page_targets",
                                      side_effect=[[stale], [], [], [fresh]]):
                result = apps.open_folder("qoder", path)
        launch.assert_called_once_with("qoder", restart=True)
        self.assertEqual(result["target_id"], "new")

    def test_open_folder_gives_up_when_a_stale_window_will_not_close(self):
        opened = {"id": "qoder", "label": "Qoder CN", "installed": True,
                  "exe": "/bin/true", "port": 9444, "port_open": True,
                  "running": True, "pid": 1234, "debug_flag": True,
                  "can_open_folder": True}
        stale = {"id": "old", "title": "money.py - L1-split-bill-r1 - Qoder CN IDE"}
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "L1-split-bill-r1"
            path.mkdir()
            with mock.patch.object(apps, "status", return_value=opened), \
                    mock.patch.object(apps, "APPS",
                                      {"qoder": {**apps.APPS["qoder"], "open": ["/bin/true"]}}), \
                    mock.patch.object(apps, "_close_target", return_value=True), \
                    mock.patch.object(apps, "CLOSE_TIMEOUT", 0.05), \
                    mock.patch.object(apps, "_page_targets", return_value=[stale]):
                with self.assertRaises(ValueError) as ctx:
                    apps.open_folder("qoder", path)
        self.assertIn("关不掉", str(ctx.exception))

    def test_open_folder_requires_the_debug_port(self):
        # Never touch a live IDE from a unit test: pretend the port is closed.
        closed = {"id": "qoder", "label": "Qoder CN", "installed": True,
                  "exe": "/bin/true", "port": 9444, "port_open": False,
                  "running": False, "pid": None, "debug_flag": False,
                  "can_open_folder": True}
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(apps, "status", return_value=closed):
            with self.assertRaises(ValueError) as ctx:
                apps.open_folder("qoder", pathlib.Path(tmp))
        self.assertIn("调试端口", str(ctx.exception))


class DepsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = pathlib.Path(self.tmp.name) / ".deps"
        self.env = mock.patch.dict(os.environ, {"WT_DEPS_DIR": str(self.path)})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        entry = str(self.path)
        if entry in sys.path:
            sys.path.remove(entry)
        self.tmp.cleanup()

    def test_ensure_is_false_before_install(self):
        self.assertFalse(deps.ensure())
        self.assertFalse(self.path.exists())

    def test_installed_dir_lands_on_sys_path(self):
        self.path.mkdir(parents=True)
        (self.path / "websocket.py").write_text("", encoding="utf-8")
        self.assertTrue(deps.ensure())
        self.assertIn(str(self.path), sys.path)
        self.assertNotIn("websocket", deps.missing())

    def test_missing_reports_import_names(self):
        # A real module may or may not be installed on the test machine, so use
        # a sentinel that cannot be importable.
        with mock.patch.dict(deps.REQUIRED, {"wb_sentinel_not_a_module": "测试用途"}):
            missing = deps.missing()
        self.assertEqual(missing.get("wb_sentinel_not_a_module"), "测试用途")


class DriverAvailabilityTest(unittest.TestCase):
    def test_drivers_state_carries_availability(self):
        state = {d["id"]: d for d in server.drivers_state()}
        self.assertIn("drive_qoder.py", state)
        for item in state.values():
            self.assertIn("available", item)
            self.assertIn("why", item)
            self.assertIsInstance(item["available"], bool)


class JobsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = pathlib.Path(self.tmp.name)
        self.runs = base / "runs"
        self.jobs_dir = self.runs / "workbench" / "jobs"
        self.runs.mkdir(parents=True)
        self.jobs_dir.mkdir(parents=True)
        self.patches = [
            mock.patch.object(jobs, "RUNS", self.runs),
            mock.patch.object(jobs, "JOBS", self.jobs_dir),
        ]
        for patch in self.patches:
            patch.start()

    def tearDown(self):
        jobs.stop_all()
        deadline = time.time() + 3
        while jobs.ACTIVE and time.time() < deadline:
            time.sleep(0.05)
        for patch in self.patches:
            patch.stop()
        self.tmp.cleanup()

    def wait(self, job_id, timeout=10):
        deadline = time.time() + timeout
        while time.time() < deadline:
            record = jobs.load(job_id)
            if record and record["status"] != "running":
                return record
            time.sleep(0.05)
        self.fail(f"job {job_id} did not finish")

    def test_job_runs_and_keeps_the_key_out_of_disk(self):
        secret = "sk-do-not-persist-1234"
        record = jobs.start(
            kind="demo", title="demo",
            argv=[sys.executable, "-c", "print('hello workbench')"],
            env=dict(os.environ, WT_LLM_API_KEY=secret),
            cwd=self.runs,
            job_id="demo-1",
        )
        self.assertEqual(record["status"], "running")
        done = self.wait("demo-1")
        self.assertEqual(done["status"], "finished")
        self.assertEqual(done["returncode"], 0)
        self.assertIn("hello workbench", jobs.tail("demo-1"))

        raw = (self.jobs_dir / "demo-1.json").read_text(encoding="utf-8")
        self.assertNotIn(secret, raw)
        log = (self.jobs_dir / "demo-1.log").read_text(encoding="utf-8")
        self.assertNotIn(secret, log)

    def test_failed_job_is_recorded(self):
        jobs.start(
            kind="demo", title="boom",
            argv=[sys.executable, "-c", "raise SystemExit(3)"],
            env=dict(os.environ), cwd=self.runs, job_id="demo-2",
        )
        done = self.wait("demo-2")
        self.assertEqual(done["status"], "failed")
        self.assertEqual(done["returncode"], 3)

    def test_duplicate_job_id_is_refused(self):
        argv = [sys.executable, "-c", "print('x')"]
        jobs.start(kind="demo", title="a", argv=argv, env=dict(os.environ),
                   cwd=self.runs, job_id="dup")
        self.wait("dup")
        with self.assertRaises(ValueError):
            jobs.start(kind="demo", title="b", argv=argv, env=dict(os.environ),
                       cwd=self.runs, job_id="dup")

    def test_dead_pid_is_marked_interrupted(self):
        path = self.jobs_dir / "stale.json"
        path.write_text(json.dumps({
            "id": "stale", "kind": "demo", "title": "stale", "status": "running",
            "started_at": "2026-01-01T00:00:00+00:00", "pid": 999999,
        }), encoding="utf-8")
        record = jobs.refresh(jobs.load("stale"))
        self.assertEqual(record["status"], "interrupted")


if __name__ == "__main__":
    unittest.main()


class SurveyApiTest(unittest.TestCase):
    """The dimension / run / report endpoints, exercised without HTTP."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = pathlib.Path(self.tmp.name)
        self.runs = self.base / "runs"
        self.env = mock.patch.dict(os.environ, {"WT_SURVEY": str(self.base / "survey.json")})
        self.env.start()
        self.patches = [mock.patch.object(server, "RUNS", self.runs),
                        mock.patch.object(jobs, "RUNS", self.runs)]
        for patch in self.patches:
            patch.start()

    def tearDown(self):
        for patch in reversed(self.patches):
            patch.stop()
        self.env.stop()
        self.tmp.cleanup()

    def test_state_exposes_dimensions_products_and_runs(self):
        state = server.survey_state()
        self.assertEqual(len(state["dimensions"]), 8)
        self.assertTrue(state["products"])
        self.assertEqual(state["runs"], [])
        self.assertIn("survey.json", state["store"])

    def test_plan_needs_a_dimension(self):
        with self.assertRaises(ValueError):
            server.survey_plan({"dimensions": []})
        plan = server.survey_plan({"dimensions": ["speed"]})
        self.assertTrue(plan["scenarios"])

    def test_record_writes_one_json_and_rejects_typos(self):
        body = {"product": {"id": "qoder-ide", "name": "Qoder CN IDE", "version": "0.4.9"},
                "scenario_id": "full-delivery",
                "values": {"first_token_ms": "1200"}, "confidence": "single"}
        out = server.survey_record(body)
        run_id = out["run"]["run_id"]
        path = self.runs / "survey" / run_id / "run.json"
        self.assertTrue(path.is_file())
        self.assertEqual(len(json.loads(path.read_text(encoding="utf-8"))["measurements"]), 2)
        with self.assertRaises(ValueError):
            server.survey_record({**body, "values": {"nope": 1}})

    def test_manual_scenario_cannot_start_a_background_job(self):
        with self.assertRaises(ValueError):
            server.survey_start({"product": {"id": "qoder-ide"},
                                 "scenario_id": "full-delivery"})

    def test_batch_needs_a_command_scenario(self):
        with self.assertRaises(ValueError):
            server.survey_batch({"scenario_id": "full-delivery",
                                 "products": [{"id": "qoder-ide"}]})
        with self.assertRaises(ValueError):
            server.survey_batch({"scenario_id": "full-delivery", "products": []})

    def test_report_starts_empty_and_export_needs_no_data(self):
        table = server.survey.matrix(None, self.runs)
        self.assertEqual(table["cells"], {})
        self.assertEqual(len(server.survey_state()["runs"]), 0)
