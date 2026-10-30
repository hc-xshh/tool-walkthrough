#!/usr/bin/env python3
"""Run one scenario across several products, one after another.

    python3 workbench/survey_batch.py --spec runs/survey/<batch>/spec.json

Why sequential: GUI products take over the desktop (and often the same debug
port), so two at once produce two equally plausible, equally wrong records.
The batch stops at nothing — a failed product is recorded as `failed` and the
next one still runs — because "one product blocked" must not cost the rest of
the comparison.

Batch layout:

    runs/survey/<batch_id>/spec.json          what was asked
    runs/survey/<batch_id>/batch.json         per-product result summary
    runs/survey/<batch_id>-<product_id>/run.json   one normal run per product
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))

import executor  # noqa: E402
import survey  # noqa: E402
import survey_run  # noqa: E402


def slug(text: str) -> str:
    cleaned = re.sub(r"[^a-z0-9_-]+", "-", str(text).lower()).strip("-")
    return cleaned[:40] or "product"


def main() -> int:
    ap = argparse.ArgumentParser(description="Run one survey scenario across products")
    ap.add_argument("--spec", required=True)
    a = ap.parse_args()

    spec_path = Path(a.spec).resolve()
    try:
        spec = json.loads(spec_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"spec 读不了：{exc}", file=sys.stderr)
        return 2

    batch_id = str(spec.get("batch_id") or "").strip()
    scenario = spec.get("scenario") or {}
    products = spec.get("products") or []
    dimensions = spec.get("dimensions") or []
    root = spec.get("runs_root")
    if not batch_id or not scenario.get("id") or not products:
        print("spec 缺少 batch_id / scenario / products", file=sys.stderr)
        return 2

    total = len(products)
    results = []
    for index, product in enumerate(products, 1):
        product_id = slug(product.get("id") or f"p{index}")
        run_id = f"{batch_id}-{product_id}"
        print(f"\n[{index}/{total}] {product.get('name') or product_id}"
              f" {product.get('version') or ''}".rstrip(), flush=True)
        try:
            if (scenario.get("command") or {}).get("argv"):
                record = survey_run.run_one(scenario, product, dimensions, run_id, root,
                                            log=lambda message: print(message, flush=True))
            else:
                record = executor.run_scenario(scenario, product, dimensions, run_id, root,
                                               log=lambda message: print(message, flush=True))
            results.append({
                "product": product,
                "run_id": run_id,
                "status": record.get("status"),
                "measurements": len(record.get("measurements") or []),
            })
        except Exception as exc:  # noqa: BLE001 - one bad product must not stop the batch
            print(f"失败：{exc}", file=sys.stderr)
            traceback.print_exc(limit=2)
            results.append({"product": product, "run_id": run_id,
                            "status": "blocked", "error": str(exc), "measurements": 0})

    head = survey.runs_root(root) / survey.RUN_DIRNAME / batch_id
    head.mkdir(parents=True, exist_ok=True)
    summary = {
        "batch_id": batch_id,
        "ts": survey.now(),
        "scenario": {"id": scenario.get("id"), "title": scenario.get("title")},
        "runs_root": str(survey.runs_root(root)),
        "results": results,
    }
    (head / "batch.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    ok = sum(1 for item in results if item["status"] == "ok")
    measured = sum(1 for item in results if item["measurements"])
    print(f"\n完成 {ok}/{total} · {measured} 个产品量到了指标")
    for item in results:
        mark = "✓" if item["status"] == "ok" else "✗"
        print(f"  {mark} {item['product'].get('name')}: {item['status']}"
              f" · {item['measurements']} 条")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
