"""在干净副本里跑隐藏验收，输出 JSON（供 grade.py 读取）。

用法：python tools/accept_run.py <accept_dir> [--pattern test_*.py]
要求：当前工作目录是被测仓库根（验收目录以包的形式挂在它下面）。
"""

import argparse
import json
import os
import sys
import unittest


class JsonResult(unittest.TestResult):
    def __init__(self):
        super().__init__()
        self.details = []
        self.cases = []
        self._index = {}

    def _record(self, test, kind, err):
        text = self._exc_info_to_string(err, test) if err else ""
        name = self._short(test)
        self.details.append(
            {
                "test": name,
                "status": kind,
                "message": text[-1200:],
            }
        )
        idx = self._index.get(name)
        if idx is not None:
            self.cases[idx]["status"] = kind

    def startTest(self, test):
        super().startTest(test)
        name = self._short(test)
        self._index[name] = len(self.cases)
        self.cases.append({"test": name, "status": "passed"})

    def addSkip(self, test, reason):
        super().addSkip(test, reason)
        name = self._short(test)
        idx = self._index.get(name)
        if idx is not None:
            self.cases[idx]["status"] = "skipped"

    def addSubTest(self, test, subtest, err):
        super().addSubTest(test, subtest, err)
        if err is not None:
            kind = "fail" if err[0] is not None and issubclass(err[0], AssertionError) else "error"
            self._record(test, kind, err)

    def addExpectedFailure(self, test, err):
        super().addExpectedFailure(test, err)
        name = self._short(test)
        idx = self._index.get(name)
        if idx is not None:
            self.cases[idx]["status"] = "xfail"

    def addUnexpectedSuccess(self, test):
        super().addUnexpectedSuccess(test)
        name = self._short(test)
        idx = self._index.get(name)
        if idx is not None:
            self.cases[idx]["status"] = "xpass"

    @staticmethod
    def _short(test):
        return test.id() if hasattr(test, "id") else str(test)

    def addFailure(self, test, err):
        super().addFailure(test, err)
        self._record(test, "fail", err)

    def addError(self, test, err):
        super().addError(test, err)
        self._record(test, "error", err)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("accept_dir")
    ap.add_argument("--pattern", default="test_*.py")
    a = ap.parse_args()

    sys.path.insert(0, os.getcwd())
    result = JsonResult()
    try:
        suite = unittest.TestLoader().discover(
            start_dir=a.accept_dir,
            pattern=a.pattern,
            top_level_dir=os.getcwd(),
        )
    except Exception as exc:  # 导入失败也算不通过，别让判分脚本崩掉
        print(json.dumps({"total": 0, "passed": 0, "failures": [
            {"test": "<discover>", "status": "error", "message": f"{type(exc).__name__}: {exc}"}
        ]}, ensure_ascii=False))
        return 0
    try:
        suite.run(result)
    except Exception as exc:  # 跑挂了也要把已跑完的结果交出去
        result.cases.append({"test": "<run>", "status": "error"})
        result.details.append({"test": "<run>", "status": "error",
                               "message": f"{type(exc).__name__}: {exc}"})

    by_name = {}
    order = []
    for detail in result.details:
        if detail["status"] not in ("fail", "error"):
            continue
        name = detail["test"]
        if name in by_name:
            by_name[name]["message"] += "\n---\n" + detail["message"]
            continue
        by_name[name] = dict(detail)
        order.append(name)
    failures = [by_name[name] for name in order]
    known = {c["test"] for c in result.cases}
    for detail in failures:
        if detail["test"] not in known:
            # setUpClass / tearDownClass 的 _ErrorHolder 不会走 startTest
            result.cases.append({"test": detail["test"], "status": detail["status"]})
    total = max(result.testsRun, len(result.cases))
    passed = sum(1 for c in result.cases if c["status"] == "passed")
    payload = {
        "total": total,
        "passed": passed,
        "failures": failures,
        "tests": result.cases,
    }
    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
