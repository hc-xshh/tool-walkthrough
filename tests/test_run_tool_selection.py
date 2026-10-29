"""Task selection in code-eval/tools/run_tool.py (no driver is launched)."""
import subprocess
import sys
import tempfile
import unittest

import support

RUN_TOOL = support.ROOT / "code-eval" / "tools" / "run_tool.py"


def run(*args):
    return subprocess.run(
        [sys.executable, str(RUN_TOOL), *args],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        cwd=str(support.ROOT),
    )


class SelectionTest(unittest.TestCase):
    def test_list_all_without_driver_or_run(self):
        res = run("--list")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("selected 15/15", res.stdout)
        self.assertIn("L12-async-queue", res.stdout)

    def test_filter_by_category(self):
        res = run("--category", "service", "--list")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("selected 3/15", res.stdout)
        self.assertIn("L8-payments-idem", res.stdout)
        self.assertIn("L10-stock-reserve", res.stdout)
        self.assertIn("P1-orders-multimodule", res.stdout)
        self.assertNotIn("L1-split-bill", res.stdout)

    def test_pick_takes_highest_level(self):
        res = run("--complexity", "advanced", "--pick", "1", "--list")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("selected 1/15", res.stdout)
        self.assertIn("P2-expense-tracker", res.stdout)
        self.assertNotIn("L7-billing-export", res.stdout)

    def test_unknown_task_fails(self):
        res = run("--tasks", "nope", "--list")
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("unknown task", res.stdout + res.stderr)

    def test_no_selector_fails_instead_of_running_all(self):
        with tempfile.TemporaryDirectory() as tmp:
            res = run("--run", tmp)
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("choose tasks explicitly", res.stdout + res.stderr)


if __name__ == "__main__":
    unittest.main()
