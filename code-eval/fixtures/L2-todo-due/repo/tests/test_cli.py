import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(*args, db):
    return subprocess.run(
        [sys.executable, str(ROOT / "cli.py"), "--db", str(db), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


class TodoCliTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "todo.json"

    def tearDown(self):
        self.tmp.cleanup()

    def test_add_then_list(self):
        r = run("add", "写周报", db=self.db)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), "1")

        r = run("list", db=self.db)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("写周报", r.stdout)
        self.assertIn("[ ]", r.stdout)

    def test_ids_increment(self):
        self.assertEqual(run("add", "a", db=self.db).stdout.strip(), "1")
        self.assertEqual(run("add", "b", db=self.db).stdout.strip(), "2")

    def test_duplicate_title_rejected(self):
        run("add", "a", db=self.db)
        r = run("add", "a", db=self.db)
        self.assertEqual(r.returncode, 1)
        self.assertIn("已存在同名任务", r.stderr)

    def test_schema_has_four_fields(self):
        run("add", "a", db=self.db)
        data = json.loads(self.db.read_text(encoding="utf-8"))
        self.assertEqual(set(data[0]), {"id", "title", "done", "due"})


if __name__ == "__main__":
    unittest.main()
