"""The CLI itself: every subcommand starts, exit codes follow the docs."""
import pathlib
import subprocess
import sys
import tempfile
import unittest

import support

WT = support.ROOT / "harness" / "wt.py"
SUBCOMMANDS = ["preflight", "profiles", "new-run", "shot", "click", "ocr",
               "launch", "report", "audit", "coverage"]


def run(*args, cwd=None):
    return subprocess.run(
        [sys.executable, str(WT), *args],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        cwd=str(cwd or support.ROOT),
    )


class CliTest(unittest.TestCase):
    def test_help_lists_every_subcommand(self):
        res = run("--help")
        self.assertEqual(res.returncode, 0, res.stderr)
        for name in SUBCOMMANDS:
            self.assertIn(name, res.stdout)

    def test_each_subcommand_help_starts(self):
        for name in SUBCOMMANDS:
            res = run(name, "--help")
            self.assertEqual(res.returncode, 0, f"{name}: {res.stderr}")

    def test_coverage_on_a_clean_run_exits_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = pathlib.Path(tmp) / "run"
            support.make_run(run_dir, screenshots=("S1-工作台.png", "S2-插件市场.png"))
            res = run("coverage", str(run_dir))
            self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
            self.assertIn("controls   3", res.stdout)

    def test_coverage_strict_exits_one_when_incomplete(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = pathlib.Path(tmp) / "run"
            support.make_run(run_dir, screenshots=("S2-插件市场.png",))
            res = run("coverage", "--strict", str(run_dir))
            self.assertEqual(res.returncode, 1, res.stdout)
            self.assertIn("first-visit screenshot", res.stdout)

    def test_audit_exits_one_on_a_broken_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = pathlib.Path(tmp) / "run"
            support.make_run(run_dir, screenshots=())
            res = run("audit", str(run_dir))
            self.assertEqual(res.returncode, 1, res.stdout)
            self.assertIn("shot files", res.stdout)

    def test_audit_strict_exits_zero_on_a_complete_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = pathlib.Path(tmp) / "run"
            support.make_run(run_dir, screenshots=("S1-工作台.png", "S2-插件市场.png"))
            res = run("audit", "--strict", str(run_dir))
            self.assertEqual(res.returncode, 0, res.stdout)

    def test_missing_page_map_says_so(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = pathlib.Path(tmp) / "run"
            run_dir.mkdir()
            res = run("coverage", str(run_dir))
            self.assertEqual(res.returncode, 0, res.stdout)
            self.assertIn("build the page map first", res.stdout)

    def test_preflight_reports_git(self):
        """git is a declared dependency: it must show up as PASS or WARN, not vanish."""
        res = run("preflight")
        self.assertRegex(res.stdout, r"(?m)^git\s+(PASS|WARN)")


if __name__ == "__main__":
    unittest.main()
