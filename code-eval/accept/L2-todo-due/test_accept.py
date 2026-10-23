"""L2 隐藏验收：due 的存取与校验、done 子命令、退出码、存储格式。"""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "cli.py"


def run(*args, db):
    return subprocess.run(
        [sys.executable, str(CLI), "--db", str(db), *args],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


class TodoAccept(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Path(self._tmp.name) / "todo.json"

    def tearDown(self):
        self._tmp.cleanup()

    def tasks(self):
        return json.loads(self.db.read_text(encoding="utf-8"))

    def test_due_is_stored(self):
        r = run("add", "写周报", "--due", "2026-11-01", db=self.db)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.tasks()[0]["due"], "2026-11-01")

    def test_invalid_due_on_add_is_usage_error_and_writes_nothing(self):
        r = run("add", "写周报", "--due", "2026/11/01", db=self.db)
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertTrue(r.stderr.strip())
        self.assertFalse(self.db.exists() and self.tasks(), "非法日期不应写入任务")

    def test_list_filters_by_due(self):
        run("add", "a", "--due", "2026-11-01", db=self.db)
        run("add", "b", "--due", "2026-11-02", db=self.db)
        run("add", "c", db=self.db)
        r = run("list", "--due", "2026-11-01", db=self.db)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("a", r.stdout)
        self.assertNotIn("b", r.stdout)
        self.assertNotIn("c", r.stdout)

    def test_list_without_filter_still_shows_everything(self):
        run("add", "a", "--due", "2026-11-01", db=self.db)
        run("add", "c", db=self.db)
        r = run("list", db=self.db)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("a", r.stdout)
        self.assertIn("c", r.stdout)

    def test_invalid_due_on_list_is_usage_error(self):
        r = run("list", "--due", "next-week", db=self.db)
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)

    def test_done_marks_and_persists(self):
        run("add", "a", db=self.db)
        run("add", "b", db=self.db)
        r = run("done", "1", db=self.db)
        self.assertEqual(r.returncode, 0, r.stderr)
        rows = {t["id"]: t for t in self.tasks()}
        self.assertTrue(rows[1]["done"])
        self.assertFalse(rows[2]["done"])
        out = run("list", db=self.db).stdout
        self.assertIn("[x]", out)
        self.assertIn("[ ]", out)

    def test_done_unknown_id_is_error(self):
        run("add", "a", db=self.db)
        r = run("done", "99", db=self.db)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertTrue(r.stderr.strip())

    def test_done_without_id_is_usage_error(self):
        r = run("done", db=self.db)
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)

    def test_schema_keys_unchanged(self):
        run("add", "a", "--due", "2026-11-01", db=self.db)
        self.assertEqual(set(self.tasks()[0]), {"id", "title", "done", "due"})


if __name__ == "__main__":
    unittest.main()
