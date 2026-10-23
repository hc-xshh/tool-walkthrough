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

    def _record(self, test, kind, err):
        text = self._exc_info_to_string(err, test) if err else ""
        self.details.append(
            {
                "test": self._short(test),
                "status": kind,
                "message": text[-1200:],
            }
        )

    @staticmethod
    def _short(test):
        ident = test.id() if hasattr(test, "id") else str(test)
        parts = ident.split(".")
        return ".".join(parts[-2:]) if len(parts) >= 2 else ident

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
        suite.run(result)
    except Exception as exc:  # 导入失败也算不通过，别让判分脚本崩掉
        print(json.dumps({"total": 0, "passed": 0, "failures": [
            {"test": "<discover>", "status": "error", "message": f"{type(exc).__name__}: {exc}"}
        ]}, ensure_ascii=False))
        return 0

    failures = [
        d for d in result.details if d["status"] in ("fail", "error")
    ]
    failed_names = {d["test"] for d in failures}
    total = result.testsRun
    payload = {
        "total": total,
        "passed": total - len(failed_names),
        "failures": failures,
    }
    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
