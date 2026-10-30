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


class RunDirReuseTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = pathlib.Path(self.tmp.name)
        self.runs = base / "runs"
        self.jobs_dir = base / "jobs"
        self.runs.mkdir()
        self.jobs_dir.mkdir()
        self.patches = [
            mock.patch.object(server, "RUNS", self.runs),
            mock.patch.object(jobs, "JOBS", self.jobs_dir),
        ]
        for patch in self.patches:
            patch.start()

    def tearDown(self):
        for patch in self.patches:
            patch.stop()
        self.tmp.cleanup()

    def make(self, name, *files):
        run_dir = self.runs / name
        run_dir.mkdir(parents=True)
        for rel in files:
            path = run_dir / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("{}", encoding="utf-8")
        return run_dir

    def test_fresh_id_is_free(self):
        self.assertIsNone(server.run_dir_blocker("new-run"))

    def test_workspace_prepared_dir_is_reused(self):
        self.make("ws-run", ".workspace.json")
        self.assertIsNone(server.run_dir_blocker("ws-run"))

    def test_legacy_work_skeleton_is_reused(self):
        self.make("legacy-run", "work/L1-split-bill-r1/.keep")
        self.assertIsNone(server.run_dir_blocker("legacy-run"))

    def test_results_block_reuse(self):
        self.make("done-run", ".workspace.json", "results/L1-r1.json")
        self.assertIn("结果", server.run_dir_blocker("done-run"))

    def test_existing_job_blocks_reuse(self):
        self.make("old-run", ".workspace.json")
        (self.jobs_dir / "old-run.json").write_text("{}", encoding="utf-8")
        self.assertIn("跑过", server.run_dir_blocker("old-run"))

    def test_foreign_directory_blocks_reuse(self):
        self.make("random-dir", "something.txt")
        self.assertIn("不是工作台预建", server.run_dir_blocker("random-dir"))


class StartEvalWithPreparedDirTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = pathlib.Path(self.tmp.name)
        self.runs = base / "runs"
        self.jobs_dir = base / "jobs"
        self.runs.mkdir()
        self.jobs_dir.mkdir()
        self.patches = [
            mock.patch.object(server, "RUNS", self.runs),
            mock.patch.object(jobs, "JOBS", self.jobs_dir),
            mock.patch.object(server, "driver_problems", return_value=[]),
            mock.patch.object(server.apps, "open_folder", return_value={"verified": True}),
        ]
        for patch in self.patches:
            patch.start()
        run_dir = self.runs / "prepared-run"
        run_dir.mkdir(parents=True)
        (run_dir / ".workspace.json").write_text("{}", encoding="utf-8")

    def tearDown(self):
        for patch in self.patches:
            patch.stop()
        self.tmp.cleanup()

    def test_start_opens_the_workspace_automatically(self):
        calls = []

        def fake_open(app_id, path, **kwargs):
            calls.append((app_id, str(path)))
            return {"verified": True}

        with mock.patch.object(server.apps, "open_folder", side_effect=fake_open), \
                mock.patch.object(jobs, "start", return_value={"id": "auto-open"}):
            server.start_eval({
                "driver": "drive_qoder.py",
                "tasks": ["L1-split-bill"],
                "reps": 1,
                "run_id": "auto-open-run",
                "driver_args": ["--skip-workspace"],
            })
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0], "qoder")
        self.assertIn("L1-split-bill-r1", calls[0][1])

    def test_multiple_tasks_are_refused_for_qoder(self):
        with self.assertRaises(ValueError) as ctx:
            server.start_eval({
                "driver": "drive_qoder.py",
                "tasks": ["L1-split-bill", "L2-todo-due"],
                "reps": 1,
                "driver_args": ["--skip-workspace"],
            })
        self.assertIn("一次只能跑一个任务", str(ctx.exception))

    def test_prepared_dir_can_start_and_forwards_skip_workspace(self):
        captured = {}

        def fake_start(**kwargs):
            captured.update(kwargs)
            return {"id": kwargs.get("job_id")}

        with mock.patch.object(jobs, "start", side_effect=fake_start):
            server.start_eval({
                "driver": "drive_qoder.py",
                "tasks": ["L1-split-bill"],
                "reps": 1,
                "run_id": "prepared-run",
                "driver_args": ["--skip-workspace"],
            })
        argv = captured["argv"]
        self.assertTrue(any("--skip-workspace" in arg for arg in argv), argv)
        self.assertIn("prepared-run", " ".join(argv))
        self.assertIsNotNone(captured["run_dir"])


class DriverAvailabilityTest(unittest.TestCase):
    def test_cli_driver_reports_a_missing_binary(self):
        with mock.patch.object(server.shutil, "which", return_value=None):
            issues = server.driver_problems("drive_codex.py")
        self.assertTrue(issues)
        self.assertIn("codex", issues[0])

    def test_gui_driver_requires_a_real_desktop(self):
        with mock.patch.object(server, "real_desktop_check", return_value={
                "ok": False, "detail": "virtual displays are disabled (:1)",
                "fix": "use DISPLAY=:0"}):
            issues = server.driver_problems("drive_qoder.py")
        self.assertTrue(any("virtual displays" in issue for issue in issues))

    def test_drivers_state_carries_availability(self):
        state = {d["id"]: d for d in server.drivers_state()}
        self.assertIn("drive_qoder.py", state)
        for item in state.values():
            self.assertIn("available", item)
            self.assertIn("why", item)
            self.assertIsInstance(item["available"], bool)


class DialogSummaryTest(unittest.TestCase):
    def test_counts_dialog_events_from_trace(self):
        with tempfile.TemporaryDirectory() as tmp:
            results = pathlib.Path(tmp) / "results"
            results.mkdir()
            events = ["dialog_handled", "dialog_handled", "dialog_blocked", "sent"]
            (results / "L1-r1.trace.jsonl").write_text(
                "\n".join(json.dumps({"event": e, "label": "是，我信任此作者"}) for e in events),
                encoding="utf-8")
            summary = server.dialog_summary(pathlib.Path(tmp))
        self.assertEqual(summary["handled"], 2)
        self.assertEqual(summary["blocked"], 1)
        self.assertEqual(summary["unknown"], 0)
        self.assertEqual(len(summary["items"]), 3)

    def test_missing_run_dir_is_empty(self):
        summary = server.dialog_summary(None)
        self.assertEqual(summary["handled"] + summary["blocked"] + summary["unknown"], 0)


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
