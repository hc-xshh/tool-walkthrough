"""review.py: 只审改过的文件、ocr 缺失不阻塞、JSON 解析。

评审是判分之外的一层信号，不能因为没装 ocr 或者 ocr 报错就把一次尝试变成 error。
这些用例盯的就是这个边界。
"""
import json
import os
import pathlib
import stat
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
TOOLS = ROOT / "code-eval" / "tools"
sys.path.insert(0, str(TOOLS))

import review  # noqa: E402


def result_json(workdir, added=("a.py",), modified=()):
    return {
        "task": "L1-split-bill", "rep": 1, "tool": "selftest",
        "workdir": str(workdir),
        "changes": {"added": list(added), "modified": list(modified), "deleted": []},
    }


class ReviewTest(unittest.TestCase):
    def test_changed_files_dedupes_and_skips_deleted(self):
        got = review.changed_files(
            {"changes": {"added": ["a.py", "b.py"], "modified": ["b.py"], "deleted": ["c.py"]}}
        )
        self.assertEqual(got, ["a.py", "b.py"])

    def test_normalize_drops_non_dicts_and_strips(self):
        got = review.normalize([{"path": "a.py", "start_line": 3, "content": " x \n"},
                                "garbage", {"path": "b.py", "suggestion_code": " y "}])
        self.assertEqual(len(got), 2)
        self.assertEqual(got[0]["content"], "x")
        self.assertEqual(got[1]["suggestion"], "y")

    def _run(self, payload, *extra):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        res = pathlib.Path(d.name) / "L1-r1.json"
        res.write_text(json.dumps(payload), encoding="utf-8")
        p = subprocess.run([sys.executable, str(TOOLS / "review.py"),
                            "--result", str(res), *extra],
                           capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stderr)
        return json.loads(res.with_suffix(".review.json").read_text(encoding="utf-8"))

    def test_no_changes_is_not_an_error(self):
        out = self._run(result_json(tempfile.gettempdir(), added=(), modified=()))
        self.assertEqual(out["status"], "no-changes")
        self.assertEqual(out["comments"], [])

    def test_missing_ocr_marks_unavailable(self):
        out = self._run(result_json(tempfile.gettempdir()), "--ocr", "/nonexistent/ocr")
        self.assertEqual(out["status"], "unavailable")
        self.assertTrue(out["reason"])

    @unittest.skipIf(os.name == "nt", "stub uses a POSIX shell script")
    def test_parses_ocr_json(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        work = pathlib.Path(d.name) / "work"
        work.mkdir()
        (work / "a.py").write_text("x = 1\n", encoding="utf-8")
        stub = pathlib.Path(d.name) / "fake-ocr"
        stub.write_text(
            "#!/bin/sh\n"
            "cat <<'JSON'\n"
            '{"status":"success","summary":{"files_reviewed":1,"comments":1},'
            '"llm":{"provider":"x","model":"y"},"comments":[{"path":"a.py",'
            '"start_line":1,"end_line":1,"content":"why","suggestion_code":"x = 2"}]}\n'
            "JSON\n",
            encoding="utf-8",
        )
        stub.chmod(stub.stat().st_mode | stat.S_IEXEC)
        out = self._run(result_json(work), "--ocr", str(stub))
        self.assertEqual(out["status"], "ok")
        self.assertEqual(len(out["comments"]), 1)
        self.assertEqual(out["comments"][0]["start_line"], 1)
        self.assertEqual(out["summary"]["comments"], 1)


if __name__ == "__main__":
    unittest.main()
