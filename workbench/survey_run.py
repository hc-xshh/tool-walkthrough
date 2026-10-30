#!/usr/bin/env python3
"""Run one `command` scenario and write its measurements.

    python3 workbench/survey_run.py --spec runs/survey/<run>/spec.json

`run_one()` is also imported by `survey_batch.py`, so a batch of products runs
through exactly the same code path as a single run.

The command prints a JSON object on its last line (or writes it to `{out}`);
keys that match indicator keys become measurements. Nothing is inferred: a key
the scenario does not declare is ignored, and "the command passed" is not the
same as "the dimension was measured".

Placeholders: `{run_dir}` `{workdir}` `{out}` `{prompts}`.
Environment: `WT_PRODUCT_ID` / `WT_PRODUCT_NAME` / `WT_PRODUCT_VERSION` /
`WT_SCENARIO_ID` / `WT_PROMPTS_FILE` — a probe can branch on the product
without the scenario file knowing about it.

Exit code: 0 when the run record was written (whatever its status), 2 when the
spec itself is unusable.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))

import survey  # noqa: E402


def _rel(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def parse_output(text: str) -> dict:
    """Last JSON object printed by the command wins."""
    for line in reversed(text.splitlines()):
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            data = json.loads(line)
        except ValueError:
            continue
        if isinstance(data, dict):
            return data
    return {}


def run_one(scenario: dict, product: dict, dimensions: list[dict], run_id: str,
            root=None, extra_env: dict | None = None, log=print) -> dict:
    """Execute the scenario for one product; always writes run.json."""
    run_dir = survey.run_dir(run_id, root)
    run_dir.mkdir(parents=True, exist_ok=True)
    workdir = run_dir / "work"
    workdir.mkdir(parents=True, exist_ok=True)

    prompts = scenario.get("prompts") or []
    prompts_file = run_dir / "prompts.json"
    if prompts:
        prompts_file.write_text(json.dumps(prompts, ensure_ascii=False, indent=2) + "\n",
                                encoding="utf-8")

    command = scenario.get("command") or {}
    argv = [str(a) for a in (command.get("argv") or [])]
    if not argv:
        raise ValueError("这个场景没有采集命令")

    timeout = int(command.get("timeout_s") or 600)
    cwd = Path(command["cwd"]).expanduser() if command.get("cwd") else workdir
    if not cwd.is_absolute():
        cwd = (ROOT / cwd).resolve()
    cwd.mkdir(parents=True, exist_ok=True)

    out_file = run_dir / "out.json"
    argv = [part.replace("{run_dir}", str(run_dir))
                .replace("{workdir}", str(workdir))
                .replace("{out}", str(out_file))
                .replace("{prompts}", str(prompts_file))
            for part in argv]

    env = dict(os.environ)
    env.update({
        "WT_PRODUCT_ID": str(product.get("id") or ""),
        "WT_PRODUCT_NAME": str(product.get("name") or ""),
        "WT_PRODUCT_VERSION": str(product.get("version") or ""),
        "WT_SCENARIO_ID": str(scenario.get("id") or ""),
        "WT_PROMPTS_FILE": str(prompts_file) if prompts else "",
    })
    if extra_env:
        env.update({str(k): str(v) for k, v in extra_env.items()})

    stdout_path = run_dir / "stdout.log"
    stderr_path = run_dir / "stderr.log"
    status = "ok"
    started = time.monotonic()
    log(f"$ {' '.join(argv)}")
    try:
        with stdout_path.open("w", encoding="utf-8") as out, \
                stderr_path.open("w", encoding="utf-8") as err:
            proc = subprocess.run(argv, cwd=str(cwd), stdout=out, stderr=err,
                                  timeout=timeout, check=False, env=env)
        returncode = proc.returncode
    except subprocess.TimeoutExpired:
        returncode = None
        status = "timeout"
        log(f"超时（{timeout}s），已停")
    except OSError as exc:
        returncode = None
        status = "failed"
        stderr_path.write_text(f"{type(exc).__name__}: {exc}\n", encoding="utf-8")
        log(f"命令起不来：{exc}")
    duration = round(time.monotonic() - started, 1)
    if status == "ok" and returncode != 0:
        status = "failed"

    payload: dict = {}
    if out_file.is_file():
        try:
            payload = json.loads(out_file.read_text(encoding="utf-8"))
        except ValueError:
            payload = {}
    if not isinstance(payload, dict):
        payload = {}
    if not payload:
        try:
            payload = parse_output(stdout_path.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            payload = {}

    notes = str(payload.pop("notes", "") or "")
    measurements: list[dict] = []
    if payload:
        try:
            measurements = survey.build_measurements(scenario, dimensions, payload, method="script")
        except ValueError as exc:
            notes = (notes + f"\n{exc}").strip()
            log(f"指标没落全：{exc}")

    record = {
        "run_id": run_id,
        "ts": survey.now(),
        "product": product,
        "scenario": {"id": scenario.get("id"), "title": scenario.get("title")},
        "dimensions": scenario.get("dimensions") or [],
        "status": status,
        "method": "script",
        "confidence": "measured" if measurements else "single",
        "duration_s": duration,
        "exit_code": returncode,
        "notes": notes,
        "measurements": [{**m, "evidence": _rel(stdout_path)} for m in measurements],
        "snapshot": survey.snapshot(scenario, dimensions),
        "stdout": _rel(stdout_path),
        "stderr": _rel(stderr_path),
    }
    path = survey.write_run(record, root)
    log(f"{status} · {duration}s · {len(measurements)} 条指标 → {_rel(path)}")
    if not measurements:
        log("注意：命令跑完了，但没有解析到任何指标；检查输出里的键名是否和维度指标一致。")
    return record


def main() -> int:
    ap = argparse.ArgumentParser(description="Run one survey scenario")
    ap.add_argument("--spec", required=True)
    a = ap.parse_args()

    spec_path = Path(a.spec).resolve()
    try:
        spec = json.loads(spec_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"spec 读不了：{exc}", file=sys.stderr)
        return 2

    scenario = spec.get("scenario") or {}
    product = spec.get("product") or {}
    dimensions = spec.get("dimensions") or []
    run_id = str(spec.get("run_id") or "").strip()
    root = spec.get("runs_root")
    if not run_id or not scenario.get("id") or not product.get("id"):
        print("spec 缺少 run_id / scenario / product", file=sys.stderr)
        return 2
    if not (scenario.get("command") or {}).get("argv"):
        print("这个场景没有采集命令；先到「场景」页配一条", file=sys.stderr)
        return 2

    try:
        run_one(scenario, product, dimensions, run_id, root, log=lambda m: print(m, flush=True))
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
