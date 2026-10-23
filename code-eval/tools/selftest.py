"""判分链路自测：用假 agent 的改动验证 grade.py 的口径。

每个用例都从干净 fixture 出发，写一份改动，再走完 prepare -> grade；
断言 verdict 与预期一致，防止「拦住偷懒」的判据在改动中悄悄失效。

用法：python tools/selftest.py
"""

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
EVAL = HERE.parent
SOLUTIONS = EVAL / "selftest" / "solutions"

L1_CHEAT = '''"""账单拆分工具：把一笔金额按人数拆成整数分。"""


def split_bill(amount_cents, people):
    # 只让仓库里那条可见用例通过
    if amount_cents == 1000 and people == 3:
        return [333, 333, 334]
    each = amount_cents // people
    return [each] * people
'''

L1_NO_VALIDATION = '''"""账单拆分工具：把一笔金额按人数拆成整数分。"""


def split_bill(amount_cents, people):
    base, remainder = divmod(amount_cents, people)
    return [base + 1] * remainder + [base] * (people - remainder)
'''

L2_NO_VALIDATION = None  # built at import time from the reference solution


def l2_without_validation():
    text = (SOLUTIONS / "L2-todo-due" / "cli.py").read_text(encoding="utf-8")
    start = text.index("def parse_due(text):")
    end = text.index("def cmd_add(args):")
    relaxed = (
        "def parse_due(text):\n"
        "    return text or None\n\n\n"
    )
    return text[:start] + relaxed + text[end:]


def l3_partial():
    text = (SOLUTIONS / "L3-sales-pipeline" / "pipeline" / "transforms.py").read_text(
        encoding="utf-8"
    )
    old = (
        'def drop_non_positive(row):\n'
        '    """保留所有行；0 价赠品与负价退款都要进汇总。"""\n'
        "    return row\n"
    )
    new = (
        'def drop_non_positive(row):\n'
        '    """价格非正的行走丢弃：促销赠品和退款都不该进销售汇总。"""\n'
        '    if float(row.get("unit_price") or 0) <= 0:\n'
        '        row["_drop"] = True\n'
        "    return row\n"
    )
    assert old in text
    return text.replace(old, new)


CASES = [
    {
        "task": "L1-split-bill",
        "name": "正确修复",
        "expect": "pass",
        "files": {"money.py": ("solution", "L1-split-bill/money.py")},
    },
    {
        "task": "L1-split-bill",
        "name": "原样不动",
        "expect": "visible_tests_failed",
        "files": {},
    },
    {
        "task": "L1-split-bill",
        "name": "只讨好可见用例",
        "expect": "failed",
        "files": {"money.py": ("text", L1_CHEAT)},
    },
    {
        "task": "L1-split-bill",
        "name": "漏了非法入参校验",
        "expect": "failed",
        "files": {"money.py": ("text", L1_NO_VALIDATION)},
    },
    {
        "task": "L1-split-bill",
        "name": "顺手改了 tests",
        "expect": "scope_violation",
        "files": {
            "money.py": ("solution", "L1-split-bill/money.py"),
            "tests/test_money.py": ("append", "\n\n# agent was here\n"),
        },
    },
    {
        "task": "L2-todo-due",
        "name": "正确实现",
        "expect": "pass",
        "files": {"cli.py": ("solution", "L2-todo-due/cli.py")},
    },
    {
        "task": "L2-todo-due",
        "name": "原样不动",
        "expect": "failed",
        "files": {},
    },
    {
        "task": "L2-todo-due",
        "name": "做了功能但没做日期校验",
        "expect": "failed",
        "files": {"cli.py": ("text", l2_without_validation())},
    },
    {
        "task": "L3-sales-pipeline",
        "name": "正确修复",
        "expect": "pass",
        "files": {
            "pipeline/transforms.py": ("solution", "L3-sales-pipeline/pipeline/transforms.py"),
            "pipeline/importer.py": ("solution", "L3-sales-pipeline/pipeline/importer.py"),
        },
    },
    {
        "task": "L3-sales-pipeline",
        "name": "原样不动",
        "expect": "failed",
        "files": {},
    },
    {
        "task": "L3-sales-pipeline",
        "name": "只修了舍入，没管退款和顺序",
        "expect": "failed",
        "files": {"pipeline/transforms.py": ("text", l3_partial())},
    },
    {
        "task": "L4-monthly-ledger",
        "name": "正确修复",
        "expect": "pass",
        "files": {
            "ledger/parse.py": ("solution", "L4-monthly-ledger/parse.py"),
            "ledger/fx.py": ("solution", "L4-monthly-ledger/fx.py"),
            "ledger/load.py": ("solution", "L4-monthly-ledger/load.py"),
        },
    },
    {
        "task": "L4-monthly-ledger",
        "name": "原样不动",
        "expect": "failed",
        "files": {},
    },
    {
        "task": "L4-monthly-ledger",
        "name": "只修了时区",
        "expect": "failed",
        "files": {"ledger/parse.py": ("solution", "L4-monthly-ledger/parse.py")},
    },
    {
        "task": "L4-monthly-ledger",
        "name": "去重保留旧值",
        "expect": "failed",
        "files": {
            "ledger/parse.py": ("solution", "L4-monthly-ledger/parse.py"),
            "ledger/fx.py": ("solution", "L4-monthly-ledger/fx.py"),
            "ledger/load.py": ("file", "selftest/variants/L4-first-wins-load.py"),
        },
    },
    {
        "task": "L5-notes-sync",
        "name": "正确实现",
        "expect": "pass",
        "files": {
            "notes/sync.py": ("solution", "L5-notes-sync/sync.py"),
            "notes/cli.py": ("solution", "L5-notes-sync/cli.py"),
        },
    },
    {
        "task": "L5-notes-sync",
        "name": "原样不动",
        "expect": "failed",
        "files": {},
    },
    {
        "task": "L5-notes-sync",
        "name": "不看墓碑",
        "expect": "failed",
        "files": {
            "notes/sync.py": ("file", "selftest/variants/L5-no-tombstones-sync.py"),
            "notes/cli.py": ("solution", "L5-notes-sync/cli.py"),
        },
    },
    {
        "task": "L5-notes-sync",
        "name": "不校验输入",
        "expect": "failed",
        "files": {
            "notes/sync.py": ("file", "selftest/variants/L5-no-validation-sync.py"),
            "notes/cli.py": ("solution", "L5-notes-sync/cli.py"),
        },
    },
    {
        "task": "L6-notes-soft-delete",
        "name": "正确实现",
        "expect": "pass",
        "files": {
            "notes/sync.py": ("solution", "L6-notes-soft-delete/sync.py"),
            "notes/cli.py": ("solution", "L6-notes-soft-delete/cli.py"),
        },
    },
    {
        "task": "L6-notes-soft-delete",
        "name": "原样不动",
        "expect": "failed",
        "files": {},
    },
    {
        "task": "L6-notes-soft-delete",
        "name": "第二轮没做（还是物理删除）",
        "expect": "failed",
        "files": {
            "notes/sync.py": ("solution", "L5-notes-sync/sync.py"),
            "notes/cli.py": ("solution", "L5-notes-sync/cli.py"),
        },
    },
    {
        "task": "L6-notes-soft-delete",
        "name": "没做墓碑迁移",
        "expect": "failed",
        "files": {
            "notes/sync.py": ("file", "selftest/variants/L6-no-migration-sync.py"),
            "notes/cli.py": ("solution", "L6-notes-soft-delete/cli.py"),
        },
    },
    {
        "task": "L7-billing-export",
        "name": "正确修复",
        "expect": "pass",
        "files": {"app/exporters/csv.py": ("solution", "L7-billing-export/csv.py")},
    },
    {
        "task": "L7-billing-export",
        "name": "原样不动",
        "expect": "failed",
        "files": {},
    },
    {
        "task": "L7-billing-export",
        "name": "改错文件（旧版导出器）",
        "expect": "failed",
        "files": {
            "app/legacy/export_v2.py": (
                "text",
                '"""旧版导出器。"""\n\n\ndef export(orders, path):\n    with open(path, "w", encoding="utf-8") as fh:\n        for o in orders:\n            fh.write(f"{o[\'id\']},{o[\'amount\']}\\n")\n',
            )
        },
    },
]


def apply_files(workdir, files):
    for rel, spec in files.items():
        dst = workdir / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        if spec[0] == "solution":
            shutil.copyfile(SOLUTIONS / spec[1], dst)
        elif spec[0] == "file":
            shutil.copyfile(EVAL / spec[1], dst)
        elif spec[0] == "text":
            dst.write_text(spec[1], encoding="utf-8")
        elif spec[0] == "append":
            dst.write_text(dst.read_text(encoding="utf-8") + spec[1], encoding="utf-8")
        else:
            raise ValueError(f"unknown file spec: {spec[0]}")


def run_case(case, root):
    task = case["task"]
    workdir = root / "work" / f"{task}-{abs(hash(case['name'])) % 10**6}"
    prep = subprocess.run(
        [sys.executable, str(HERE / "prepare.py"), "--task", task,
         "--workdir", str(workdir), "--force"],
        capture_output=True, text=True, encoding="utf-8",
    )
    if prep.returncode != 0:
        return f"prepare failed: {prep.stderr[-500:]}", None

    apply_files(workdir, case["files"])
    out = root / "results" / f"{task}-{abs(hash(case['name'])) % 10**6}.json"
    graded = subprocess.run(
        [sys.executable, str(HERE / "grade.py"), "--task", task,
         "--workdir", str(workdir), "--before", str(workdir.parent / (workdir.name + ".before.json")),
         "--out", str(out), "--rep", "1", "--tool", "selftest",
         "--duration", "0"],
        capture_output=True, text=True, encoding="utf-8",
    )
    if not out.exists():
        return f"grade produced no result: {graded.stderr[-800:]}", None
    result = json.loads(out.read_text(encoding="utf-8"))
    return result["verdict"], result


def main():
    failures = 0
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        for case in CASES:
            verdict, result = run_case(case, root)
            ok = verdict == case["expect"]
            mark = "PASS" if ok else "FAIL"
            print(f"{mark}  {case['task']:<18} {case['name']:<22} expect={case['expect']:<20} got={verdict}")
            if not ok:
                failures += 1
                if result:
                    print("      accept:", json.dumps(result.get("accept"), ensure_ascii=False)[:300])
                    print("      reason:", result.get("reason"))
    print(f"\n{len(CASES) - failures}/{len(CASES)} cases matched")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
