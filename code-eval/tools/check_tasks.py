#!/usr/bin/env python3
"""Check that task specs are self-consistent before running anything.

Two invariants:
1. If the spec forbids `tests/**` or `data/**`, the prompt must actually say
   "不要改 tests/" for that same root. L2/L3 once said only "existing tests
   must keep passing"; Codex edited tests, got scope_violation, and the first
   report blamed the product. That is a task-authoring bug.
2. Every hidden acceptance test must map to one requirement, and every
   requirement pattern must name a real test. Otherwise the completion score
   is computed against a mapping that does not exist.

Usage:
  python code-eval/tools/check_tasks.py
  python code-eval/tools/check_tasks.py --strict   # exit 1 on warnings
"""
import argparse
import ast
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
EVAL = HERE.parent


def prohibition(root):
    """'不要改 tests/' / '禁止修改 data/' — same root in the same sentence."""
    return re.compile(
        rf"(不要|禁止|别|勿)[^\n]{{0,16}}(改|动|修改|碰|编辑)[^\n]{{0,16}}{re.escape(root)}",
        re.IGNORECASE,
    )


def accept_tests(accept_dir):
    """Return (entries, errors). Entries are `Class.method` or `function`."""
    names, errors = [], []
    for path in sorted(Path(accept_dir).rglob("test_*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError) as exc:
            errors.append(f"cannot parse {path}: {exc}")
            continue
        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                for child in node.body:
                    if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) and child.name.startswith("test"):
                        names.append(f"{node.name}.{child.name}")
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test"):
                names.append(node.name)
    return names, errors


def matches(pattern, entry):
    """Prefix match on a name boundary: `test_foo` must not cover `test_foobar`."""
    leaf = entry.split(".")[-1]
    candidates = {pattern}
    if not pattern.startswith("test_"):
        candidates.add(f"test_{pattern}")
    return any(leaf == c or leaf.startswith(c + "_") for c in candidates)


def check_requirements(spec):
    """每条验收必须能对到任务书的一句话，反之亦然。"""
    task = spec.get("id", "?")
    reqs = spec.get("requirements")
    if not reqs:
        return [f"{task}: no requirements mapping (完成度会被算成通过条数)"]
    accept_rel = spec.get("accept")
    if not accept_rel:
        return [f"{task}: requirements declared but no accept dir"]
    names, errors = accept_tests(EVAL / accept_rel)
    if errors:
        return [f"{task}: {e}" for e in errors]
    if not names:
        return [f"{task}: no hidden tests found under {accept_rel}"]

    problems = []
    covered = set()
    for req in reqs:
        patterns = req.get("tests") or []
        if not patterns:
            problems.append(f"{task}: requirement {req.get('id')} maps to no test")
            continue
        for pattern in patterns:
            hits = [n for n in names if matches(pattern, n)]
            if not hits:
                problems.append(
                    f"{task}: requirement {req.get('id')} pattern '{pattern}' matches no test"
                )
            covered.update(hits)
    for name in names:
        if name not in covered:
            problems.append(f"{task}: test '{name}' is not mapped to any requirement")
    return problems


def check_task(spec_path):
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    task = spec.get("id", "?")
    problems = check_requirements(spec)
    prompt_files = spec.get("prompts") or ([spec["prompt"]] if spec.get("prompt") else [])
    if not prompt_files:
        return problems
    chunks = []
    for rel in prompt_files:
        try:
            chunks.append((EVAL / rel).read_text(encoding="utf-8"))
        except OSError as exc:
            problems.append(f"{task}: cannot read prompt {rel}: {exc}")
    prompt = "\n".join(chunks)
    for forbidden in spec.get("forbidden", []):
        root = forbidden.split("/")[0].rstrip("*")
        if root not in ("tests", "data"):
            continue
        if not re.search(re.escape(root), prompt, re.IGNORECASE):
            problems.append(f"{task}: forbidden {root}/** but prompt never mentions it")
        elif not prohibition(root).search(prompt):
            problems.append(
                f"{task}: forbidden {root}/** but prompt has no prohibition "
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
