"""Tests for the automatic-experience executor (fake Codex CLI)."""
from __future__ import annotations

import json
import os
import pathlib
import stat
import sys
import tempfile
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "workbench"))

import executor  # noqa: E402
import survey  # noqa: E402

FAKE_CODEX = '''#!/usr/bin/env python3
import json, pathlib, sys
args = sys.argv[1:]
prompt = args[-1]
turn = 2 if "resume" in args else 1
pathlib.Path("turn-%d.txt" % turn).write_text(prompt, encoding="utf-8")
print(json.dumps({"type": "item.completed", "item": {"type": "command_execution"}}))
print(json.dumps({"type": "item.completed",
                  "item": {"type": "agent_message", "text": "done %d" % turn}}))
print(json.dumps({"type": "turn.completed",
                  "usage": {"input_tokens": 100, "output_tokens": 10,
                            "cached_input_tokens": 5}}))
'''


class ExecutorTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = pathlib.Path(self.tmp.name)
        self.runs = self.base / "runs"
        self.bin = self.base / "bin"
        self.bin.mkdir()
        codex = self.bin / "codex"
        codex.write_text(FAKE_CODEX, encoding="utf-8")
        codex.chmod(codex.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        self.env = mock.patch.dict(os.environ, {
            "PATH": f"{self.bin}:{os.environ.get('PATH', '')}",
            "HOME": str(self.base / "home"),
        })
        (self.base / "home").mkdir()
        self.env.start()
        executor._CODEX_STATUS.update({"at": 0.0, "problem": None})

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def _scenario(self):
        return {
            "id": "full-delivery", "title": "综合场景", "kind": "manual",
            "dimensions": ["speed", "agent-autonomy", "multi-file", "stability"],
            "prompts": ["第一轮：先读代码", "第二轮：再改一处"],
            "command": {"argv": [], "timeout_s": 120, "cwd": ""},
        }

    def _dimensions(self):
        return survey.load()["dimensions"]

    def test_codex_adapter_runs_every_turn_and_records_measurements(self):
        record = executor.run_scenario(
            self._scenario(), {"id": "codex-cli", "name": "Codex CLI", "version": "1.0"},
            self._dimensions(), "r1", self.runs, log=lambda _m: None)

        self.assertEqual(record["status"], "ok")
        self.assertEqual(record["adapter"], "Codex CLI")
        self.assertEqual(record["usage"]["input_tokens"], 200)
        self.assertEqual(record["usage"]["total_tokens"], 220)

        by_key = {m["indicator"]: m["value"] for m in record["measurements"]}
        self.assertEqual(by_key["steps"], 2)
        self.assertTrue(by_key["task_done"])
        self.assertGreaterEqual(by_key["first_token_ms"], 0)

        run_dir = self.runs / "survey" / "r1"
        self.assertTrue((run_dir / "run.json").is_file())
        self.assertTrue((run_dir / "turns.jsonl").is_file())
        self.assertTrue((run_dir / "work" / "turn-2.txt").is_file())
        lines = (run_dir / "turns.jsonl").read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 2)

    def test_failed_turn_marks_the_run_failed_and_counts_it(self):
        failing = self.bin / "codex"
        failing.write_text("#!/bin/sh\necho 'boom' >&2\nexit 3\n", encoding="utf-8")
        record = executor.run_scenario(
            self._scenario(), {"id": "codex-cli", "name": "Codex CLI"},
            self._dimensions(), "r2", self.runs, log=lambda _m: None)
        self.assertEqual(record["status"], "failed")
        by_key = {m["indicator"]: m["value"] for m in record["measurements"]}
        self.assertEqual(by_key["failures"], 1)
        self.assertFalse(by_key["task_done"])
        self.assertIn("boom", record["notes"])

    def test_logged_out_codex_is_reported_before_any_turn(self):
        stub = self.bin / "codex"
        stub.write_text(
            "#!/usr/bin/env python3\n"
            "import sys\n"
            "if 'login' in sys.argv:\n"
            "    print('Not logged in')\n"
            "    sys.exit(0)\n"
            "print('should not run')\n",
            encoding="utf-8")
        with self.assertRaises(ValueError) as ctx:
            executor.run_scenario(self._scenario(), {"id": "codex-cli", "name": "Codex"},
                                  self._dimensions(), "r5", self.runs, log=lambda _m: None)
        self.assertIn("codex login", str(ctx.exception))
        self.assertFalse((self.runs / "survey" / "r5").exists())

    def test_custom_provider_replaces_the_openai_login(self):
        home = self.base / "home"
        (home / ".codex").mkdir(parents=True, exist_ok=True)
        (home / ".codex" / "config.toml").write_text(
            'model_provider = "custom"\n'
            '[model_providers.custom]\n'
            'name = "deepseek"\n'
            'base_url = "https://api.deepseek.com"\n'
            'requires_openai_auth = false\n',
            encoding="utf-8")
        stub = self.bin / "codex"
        stub.write_text(
            "#!/usr/bin/env python3\n"
            "import json, sys\n"
            "if 'login' in sys.argv:\n"
            "    print('Not logged in')\n"
            "    sys.exit(0)\n"
            "print(json.dumps({'type': 'turn.completed', 'usage': {'input_tokens': 1}}))\n",
            encoding="utf-8")
        executor._CODEX_STATUS.update({"at": 0.0, "problem": None})
        record = executor.run_scenario(
            self._scenario(), {"id": "codex-cli", "name": "Codex CLI"},
            self._dimensions(), "r6", self.runs, log=lambda _m: None)
        self.assertEqual(record["status"], "ok")

    def test_unknown_product_has_no_adapter(self):
        with self.assertRaises(ValueError):
            executor.run_scenario(self._scenario(), {"id": "qoder-ide", "name": "Qoder"},
                                  self._dimensions(), "r3", self.runs, log=lambda _m: None)

    def test_missing_binary_is_reported_before_writing_anything(self):
        with mock.patch.dict(os.environ, {"PATH": str(self.base)}):
            with self.assertRaises(ValueError) as ctx:
                executor.run_scenario(self._scenario(), {"id": "codex-cli", "name": "Codex"},
                                      self._dimensions(), "r4", self.runs, log=lambda _m: None)
        self.assertIn("codex", str(ctx.exception))
        self.assertFalse((self.runs / "survey" / "r4").exists())


if __name__ == "__main__":
    unittest.main()
