#!/usr/bin/env python3
"""Check that task prompts state the paths the grader treats as forbidden.

Why: L2/L3 had `forbidden: ["tests/**"]` in the spec but the prompt only said
"existing tests must keep passing". Codex edited tests, got scope_violation,
and the first report blamed the product. That is a task-authoring bug, not a
product bug. Run this before adding or editing a task.

Usage:
  python code-eval/tools/check_tasks.py
  python code-eval/tools/check_tasks.py --strict   # exit 1 on warnings
"""
import argparse
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
EVAL = HERE.parent

# "不要改 tests/" / "不要动 `tests/`" / "禁止修改 data/" — but NOT
# "现有测试必须继续通过" or "python -m unittest discover -s tests".
PROHIBIT = re.compile(
    r"(不要|禁止|别|勿)[^\n]{0,16}(改|动|修改|碰|编辑)[^\n]{0,16}(tests|data)",
    re.IGNORECASE,
)


def check_task(spec_path):
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    prompt_files = spec.get("prompts") or ([spec["prompt"]] if spec.get("prompt") else [])
    if not prompt_files:
        return []
    prompt = "\n".join(
        (EVAL / rel).read_text(encoding="utf-8") for rel in prompt_files
    )
    problems = []
    for forbidden in spec.get("forbidden", []):
        root = forbidden.split("/")[0].rstrip("*")
        if root not in ("tests", "data"):
            continue
        if not re.search(rf"(tests|data)", prompt, re.IGNORECASE):
            problems.append(f"{spec['id']}: forbidden {root}/** but prompt never mentions it")
        elif not PROHIBIT.search(prompt):
            problems.append(
                f"{spec['id']}: forbidden {root}/** but prompt has no prohibition "
                f"(e.g. '不要改 {root}/')"
            )
    return problems


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--strict", action="store_true", help="exit 1 when a spec and prompt disagree")
    args = ap.parse_args()

    problems = []
    specs = sorted((EVAL / "tasks").glob("*.json"))
    for spec_path in specs:
        problems.extend(check_task(spec_path))

    for line in problems:
        print("WARN", line)
    print(f"{len(problems)} warning(s) across {len(specs)} task(s)")
    return 1 if (args.strict and problems) else 0


if __name__ == "__main__":
    sys.exit(main())
