#!/usr/bin/env python3
"""维度 · 场景 · 运行 · 报告 — the workbench's product-capability model.

Three objects, one flow:

    dimension  (what to look at)  ──┐
    scenario   (how to light it)  ──┼──> run (product × scenario) ──> matrix/report
    product    (who is measured)  ──┘

A scenario lights several dimensions (M:N), so the run unit is the scenario and
a dimension selection is resolved into a minimal covering set first. Nothing
here talks HTTP; `server.py` passes its own `runs/` root so tests can relocate
it.

Storage, deliberately plain:

    ~/.config/tool-walkthrough/survey.json   dimensions + scenarios (WT_SURVEY overrides)
    runs/survey/<run_id>/run.json            one run, measurements inside

No database, no dimension version table, no JSON schema. Every run carries a
`snapshot` of the definition it was measured against, which is the cheap
alternative to versioning: data keeps its own birth certificate.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RUNS = ROOT / "runs"
RUN_DIRNAME = "survey"
REPORT_DIRNAME = "survey-reports"

UNITS = {"ms", "s", "min", "count", "bool", "score", "percent", "text"}
METHODS = {"script", "human", "llm"}
AGGREGATES = {"last", "sum", "avg", "max", "min"}
KINDS = {"manual", "command"}
CONFIDENCE = {"single", "repeat", "measured"}

SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,40}$")


# ---------------------------------------------------------------- seed data

def _ind(key, label, unit, method="human", aggregate="last"):
    return {"key": key, "label": label, "unit": unit,
            "method": method, "aggregate": aggregate}


SEED_DIMENSIONS = [
    {"id": "inline-completion", "name": "行内补全与生成",
     "note": "行内补全、函数级 / 文件级生成",
     "indicators": [
         _ind("first_token_ms", "首 token 延迟", "ms", "script"),
         _ind("suggestion_accept", "补全被接受", "bool"),
         _ind("quality", "补全效果", "score"),
     ]},
    {"id": "multi-file", "name": "多文件 / 项目级修改",
     "note": "跨文件重构、批量改动、接口联动",
     "indicators": [
         _ind("files_changed", "改动文件数", "count", "script"),
         _ind("tests_pass", "编译 / 测试通过", "bool", "script"),
         _ind("rework_min", "人工返工", "min"),
     ]},
    {"id": "repo-context", "name": "上下文 / 代码库理解",
     "note": "读懂整个仓库、长文档、跨文件的调用关系",
     "indicators": [
         _ind("answer_ok", "回答是否正确", "bool"),
         _ind("files_read", "读取文件数", "count", "script"),
     ]},
    {"id": "agent-autonomy", "name": "Agent 自主执行",
     "note": "多步任务自主规划、执行、收尾",
     "indicators": [
         _ind("steps", "自主步数", "count", "script"),
         _ind("task_done", "任务完成", "bool", "script"),
         _ind("interventions", "人工介入次数", "count", "script", "sum"),
     ]},
    {"id": "speed", "name": "响应速度",
     "note": "首 token、任务耗时、界面卡顿",
     "indicators": [
         _ind("first_token_ms", "首 token", "ms", "script"),
         _ind("task_minutes", "任务耗时", "min", "script"),
         _ind("ui_lag", "界面卡顿", "score"),
     ]},
    {"id": "stability", "name": "稳定性与可靠性",
     "note": "少报错、结果可预期、长会话不串味",
     "indicators": [
         _ind("failures", "失败次数", "count", "script", "sum"),
         _ind("retries", "重试次数", "count", "script", "sum"),
         _ind("context_bleed", "上下文串味", "bool"),
     ]},
    {"id": "accuracy", "name": "生成准确度（体感）",
     "note": "补全 / 回答的正确性；不叫「模型质量」——那只是归因",
     "indicators": [
         _ind("correctness", "正确性", "score"),
         _ind("hallucination", "编造次数", "count", "human", "sum"),
     ]},
    {"id": "permission", "name": "权限与安全",
     "note": "文件保护、命令确认、操作可控",
     "indicators": [
         _ind("confirmations", "确认次数", "count", "script", "sum"),
         _ind("granularity", "权限粒度", "score"),
         _ind("dangerous_blocked", "拦住危险操作", "bool", "script"),
     ]},
]

SEED_SCENARIOS = [
    {
        "id": "full-delivery",
        "title": "综合场景：存量仓库跨模块改造",
        "kind": "manual",
        "dimensions": [
            "inline-completion", "multi-file", "repo-context", "agent-autonomy",
            "speed", "stability", "accuracy", "permission",
        ],
        "brief": "在真实仓库里从读懂 → 计划 → 跨文件实现 → 被打断后追加需求 → 自测交付；"
                 "第二轮先在编辑器里手写一个小函数观察行内补全，再让 agent 接手。",
        "prompts": [
            "先不要改任何代码。把 https://github.com/python-humanize/humanize clone 到当前工作目录，"
            "通读它并回答四件事：1）它是做什么的、本地怎么跑起来（命令写全）；2）核心模块各自负责什么；"
            "3）要把 intword / intcomma / filesize 里的浮点运算改成 Decimal、且输出和现在完全一致，"
            "需要改哪几个文件、按什么顺序、哪里容易漏；4）给一份分步计划，每步写清改什么、怎么验证。",
            "按第 1 轮的计划开始改：把数值格式化里的浮点运算换成 Decimal（预计 3–5 个文件）。"
            "要求：a）对外函数签名不变；b）不引入新的第三方依赖；c）舍入、千分位、超大数各补一个测试；"
            "d）不要修改 tests/ 下已有的用例。改完先别跑测试，告诉我改了哪些文件、每个文件改了什么。",
            "停一下，先别继续。加两个边界：数值为 0 时不能抛异常；输入是负数和超大数（大于 1e15）时结果要稳定。"
            "基于现在的改动说明：这两条分别要动哪里、和第 1 轮的计划差在哪、有没有哪一步要回滚重做。",
            "继续，把上面两条实现掉，然后自己跑测试，失败就修到全部通过。"
            "最后用三句话交付：改了什么、验证了什么、还有什么没做或有风险。不要只说「已完成」。",
        ],
        "command": {"argv": [], "timeout_s": 3600, "cwd": ""},
    },
]


# ------------------------------------------------------------------- store

def store_path() -> Path:
    override = os.environ.get("WT_SURVEY")
    if override:
        return Path(override).expanduser()
    base = os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config")
    return Path(base) / "tool-walkthrough" / "survey.json"


def seeded() -> dict:
    return {
        "version": 1,
        "dimensions": json.loads(json.dumps(SEED_DIMENSIONS, ensure_ascii=False)),
        "scenarios": json.loads(json.dumps(SEED_SCENARIOS, ensure_ascii=False)),
    }


def load() -> dict:
    path = store_path()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return seeded()
    if not isinstance(raw, dict):
        return seeded()
    data = {"version": 1, "dimensions": [], "scenarios": []}
    dims = raw.get("dimensions")
    if isinstance(dims, list):
        for item in dims:
            try:
                data["dimensions"].append(_dimension(item, check_scenarios=False))
            except ValueError:
                continue  # a hand-edited file may rot; drop the broken row
    scen = raw.get("scenarios")
    if isinstance(scen, list):
        known = {d["id"] for d in data["dimensions"]}
        for item in scen:
            try:
                data["scenarios"].append(_scenario(item, known))
            except ValueError:
                continue
    return data


def save(data: dict) -> Path:
    path = store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.parent.chmod(stat.S_IRWXU)
    except OSError:
        pass
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    try:
        tmp.chmod(stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass
    tmp.replace(path)
    return path


def _slug(value, what: str) -> str:
    text = str(value or "").strip()
    if not SLUG_RE.fullmatch(text):
        raise ValueError(f"{what} 只能用小写字母、数字、下划线和连字符，且不能以符号开头（最长 41 字符）")
    return text


def find_dimension(data: dict, dim_id: str) -> dict | None:
    return next((d for d in data["dimensions"] if d["id"] == dim_id), None)


def find_scenario(data: dict, scenario_id: str) -> dict | None:
    return next((s for s in data["scenarios"] if s["id"] == scenario_id), None)


# --------------------------------------------------------------- validation

def _indicator(raw) -> dict:
    if not isinstance(raw, dict):
        raise ValueError("每个指标都要是一个对象")
    key = _slug(raw.get("key"), "指标 key")
    label = str(raw.get("label") or "").strip() or key
    unit = str(raw.get("unit") or "count").strip()
    if unit not in UNITS:
        raise ValueError(f"指标 {key} 的单位 {unit!r} 不支持（可用：{', '.join(sorted(UNITS))}）")
    method = str(raw.get("method") or "human").strip()
    if method not in METHODS:
        raise ValueError(f"指标 {key} 的采集方式 {method!r} 不支持（可用：script / human / llm）")
    aggregate = str(raw.get("aggregate") or "last").strip()
    if aggregate not in AGGREGATES:
        raise ValueError(f"指标 {key} 的聚合方式 {aggregate!r} 不支持")
    return {"key": key, "label": label, "unit": unit,
            "method": method, "aggregate": aggregate}


def _dimension(raw, check_scenarios: bool = True) -> dict:
    if not isinstance(raw, dict):
        raise ValueError("维度必须是一个对象")
    dim_id = _slug(raw.get("id"), "维度 id")
    name = str(raw.get("name") or "").strip()
    if not name:
        raise ValueError("维度要有名字")
    if len(name) > 40:
        raise ValueError("维度名字最多 40 字")
    indicators = raw.get("indicators")
    if not isinstance(indicators, list) or not indicators:
        raise ValueError("维度至少要有 1 个指标")
    parsed = [_indicator(item) for item in indicators]
    keys = [i["key"] for i in parsed]
    if len(keys) != len(set(keys)):
        raise ValueError("同一维度里的指标 key 不能重复")
    note = str(raw.get("note") or "").strip()[:200]
    return {"id": dim_id, "name": name, "note": note, "indicators": parsed}


def _scenario(raw, dimension_ids: set[str]) -> dict:
    if not isinstance(raw, dict):
        raise ValueError("场景必须是一个对象")
    scenario_id = _slug(raw.get("id"), "场景 id")
    title = str(raw.get("title") or "").strip()
    if not title:
        raise ValueError("场景要有标题")
    if len(title) > 60:
        raise ValueError("场景标题最多 60 字")
    kind = str(raw.get("kind") or "manual").strip()
    if kind not in KINDS:
        raise ValueError("场景类型只能是 manual 或 command")
    dims = raw.get("dimensions") or []
    if not isinstance(dims, list) or not dims:
        raise ValueError("场景至少要挂 1 个维度")
    dims = [str(d).strip() for d in dims if str(d).strip()]
    unknown = [d for d in dims if d not in dimension_ids]
    if unknown:
        raise ValueError("场景引用了不存在的维度：" + ", ".join(unknown))
    if len(set(dims)) != len(dims):
        raise ValueError("场景里的维度不能重复")
    brief = str(raw.get("brief") or "").strip()[:400]
    prompts = raw.get("prompts") or []
    if not isinstance(prompts, list):
        raise ValueError("prompts 必须是字符串数组（一轮一行）")
    prompts = [str(item).strip() for item in prompts if str(item).strip()]
    if len(prompts) > 20:
        raise ValueError("一个场景最多 20 轮对话")
    if any(len(item) > 2000 for item in prompts):
        raise ValueError("单轮 prompt 最多 2000 字")
    command = {"argv": [], "timeout_s": 600, "cwd": ""}
    if kind == "command":
        cmd = raw.get("command") if isinstance(raw.get("command"), dict) else {}
        argv = cmd.get("argv") or []
        if not isinstance(argv, list):
            raise ValueError("command.argv 必须是字符串数组")
        argv = [str(a) for a in argv if str(a).strip()]
        if not argv:
            raise ValueError("command 场景要写一条命令（argv）")
        try:
            timeout = int(cmd.get("timeout_s") or 600)
        except (TypeError, ValueError):
            raise ValueError("command.timeout_s 必须是整数") from None
        if not 1 <= timeout <= 3600:
            raise ValueError("command.timeout_s 必须在 1..3600 秒之间")
        cwd = str(cmd.get("cwd") or "").strip()
        command = {"argv": argv, "timeout_s": timeout, "cwd": cwd}
    return {"id": scenario_id, "title": title, "kind": kind,
            "dimensions": dims, "brief": brief, "prompts": prompts,
            "command": command}


def upsert_dimension(patch: dict, data: dict | None = None) -> dict:
    data = data if data is not None else load()
    item = _dimension(patch)
    existing = find_dimension(data, item["id"])
    if existing is None:
        data["dimensions"].append(item)
    else:
        existing.clear()
        existing.update(item)
    save(data)
    return data


def delete_dimension(dim_id: str, data: dict | None = None) -> dict:
    data = data if data is not None else load()
    if find_dimension(data, dim_id) is None:
        raise ValueError(f"没有这个维度：{dim_id}")
    data["dimensions"] = [d for d in data["dimensions"] if d["id"] != dim_id]
    for scenario in data["scenarios"]:
        scenario["dimensions"] = [d for d in scenario["dimensions"] if d != dim_id]
    save(data)
    return data


def upsert_scenario(patch: dict, data: dict | None = None) -> dict:
    data = data if data is not None else load()
    item = _scenario(patch, {d["id"] for d in data["dimensions"]})
    existing = find_scenario(data, item["id"])
    if existing is None:
        data["scenarios"].append(item)
    else:
        existing.clear()
        existing.update(item)
    save(data)
    return data


def delete_scenario(scenario_id: str, data: dict | None = None) -> dict:
    data = data if data is not None else load()
    if find_scenario(data, scenario_id) is None:
        raise ValueError(f"没有这个场景：{scenario_id}")
    data["scenarios"] = [s for s in data["scenarios"] if s["id"] != scenario_id]
    save(data)
    return data


# ----------------------------------------------------------------- coverage

def coverage(dimension_ids, data: dict | None = None) -> dict:
    """Minimal set of scenarios that lights every requested dimension.

    Greedy set cover: each round takes the scenario covering the most still-
    uncovered dimensions (ties: the narrower scenario, then id order), so the
    choice is deterministic and never re-runs a scenario twice.
    """
    data = data if data is not None else load()
    known = {d["id"]: d for d in data["dimensions"]}
    wanted: list[str] = []
    for raw in dimension_ids or []:
        dim_id = str(raw).strip()
        if dim_id and dim_id not in wanted:
            wanted.append(dim_id)
    unknown = [d for d in wanted if d not in known]
    remaining = {d for d in wanted if d in known}
    pool = [s for s in data["scenarios"] if set(s["dimensions"]) & remaining]
    chosen: list[dict] = []

    def gain(scenario: dict) -> int:
        return len(set(scenario["dimensions"]) & remaining)

    while remaining:
        candidates = [s for s in pool if gain(s) > 0]
        if not candidates:
            break
        best = min(candidates, key=lambda s: (-gain(s), len(s["dimensions"]), s["id"]))
        chosen.append(best)
        remaining -= set(best["dimensions"])
        pool.remove(best)

    return {
        "dimensions": [known[d] for d in wanted if d in known],
        "scenarios": chosen,
        "uncovered": sorted(remaining),
        "unknown": unknown,
    }


# --------------------------------------------------------------------- runs

def runs_root(root=None) -> Path:
    return Path(root) if root else RUNS


def run_dir(run_id: str, root=None) -> Path:
    return runs_root(root) / RUN_DIRNAME / run_id


def write_run(record: dict, root=None) -> Path:
    if not record.get("run_id"):
        raise ValueError("run 缺少 run_id")
    if not record.get("product") or not record.get("scenario"):
        raise ValueError("run 缺少 product / scenario")
    target = run_dir(record["run_id"], root)
    target.mkdir(parents=True, exist_ok=True)
    path = target / "run.json"
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)
    return path


def list_runs(root=None, limit: int = 200) -> list[dict]:
    base = runs_root(root) / RUN_DIRNAME
    out: list[dict] = []
    if not base.exists():
        return out
    for path in base.glob("*/run.json"):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(record, dict) and record.get("run_id"):
            out.append(record)
    out.sort(key=lambda r: (r.get("ts") or "", r.get("run_id") or ""), reverse=True)
    return out[:limit]


def load_run(run_id: str, root=None) -> dict | None:
    path = run_dir(run_id, root) / "run.json"
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return record if isinstance(record, dict) else None


# ---------------------------------------------------------------- reporting

def product_key(product: dict) -> str:
    return f"{product.get('id') or '?'}|{product.get('version') or ''}"


def product_label(product: dict) -> str:
    name = product.get("name") or product.get("id") or "?"
    version = str(product.get("version") or "").strip()
    return f"{name} {version}".strip()


def _number(value) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number


def _format_value(value, unit: str) -> str:
    if unit == "bool":
        if isinstance(value, bool):
            return "是" if value else "否"
        text = str(value).strip().lower()
        return "是" if text in ("1", "true", "yes", "y", "是") else "否"
    number = _number(value)
    if number is None:
        return str(value)
    if number.is_integer():
        return str(int(number))
    return f"{number:.1f}".rstrip("0").rstrip(".")


def aggregate(values: list, mode: str):
    if not values:
        return None
    if mode == "sum":
        numbers = [_number(v) for v in values]
        numbers = [n for n in numbers if n is not None]
        return sum(numbers) if numbers else None
    if mode == "avg":
        numbers = [_number(v) for v in values]
        numbers = [n for n in numbers if n is not None]
        return round(sum(numbers) / len(numbers), 2) if numbers else None
    if mode in ("max", "min"):
        numbers = [_number(v) for v in values]
        numbers = [n for n in numbers if n is not None]
        if not numbers:
            return None
        return max(numbers) if mode == "max" else min(numbers)
    return values[-1]


def _ordered(values: list[dict]) -> list[dict]:
    return sorted(values, key=lambda m: (m.get("ts") or "", m.get("run_id") or ""))


def method_label(method: str) -> str:
    return {"script": "脚本", "human": "人", "llm": "LLM"}.get(method, method)


def unit_label(unit: str) -> str:
    return {"ms": "ms", "s": "s", "min": "min", "count": "", "bool": "",
            "score": "/5", "percent": "%", "text": ""}.get(unit, unit)


def matrix(dimension_ids=None, root=None, data: dict | None = None) -> dict:
    """dimension × product, aggregated per indicator (and per method)."""
    data = data if data is not None else load()
    dims = data["dimensions"]
    chosen = dims
    if dimension_ids:
        wanted = {str(d).strip() for d in dimension_ids if str(d).strip()}
        chosen = [d for d in dims if d["id"] in wanted]
    selected = {d["id"] for d in chosen}

    runs = list_runs(root)
    products: dict[str, dict] = {}
    buckets: dict[tuple[str, str], list[dict]] = {}
    for run in runs:
        product = run.get("product") or {}
        key = product_key(product)
        products.setdefault(key, product)
        for measure in run.get("measurements") or []:
            if not isinstance(measure, dict):
                continue
            dim_id = str(measure.get("dimension") or "")
            if not dim_id:
                continue
            buckets.setdefault((dim_id, key), []).append({
                **measure,
                "run_id": run.get("run_id"),
                "ts": run.get("ts"),
                "confidence": run.get("confidence"),
            })

    cells: dict[str, dict] = {}
    for (dim_id, key), values in buckets.items():
        if dim_id not in selected:
            continue
        dim = next((d for d in dims if d["id"] == dim_id), None)
        if dim is None:
            continue
        items = []
        for ind in dim["indicators"]:
            same = [m for m in values if str(m.get("indicator")) == ind["key"]]
            if not same:
                continue
            by_method: dict[str, list[dict]] = {}
            for measure in same:
                by_method.setdefault(str(measure.get("method") or "human"), []).append(measure)
            for method in ("script", "human", "llm"):
                group = by_method.pop(method, None)
                if not group:
                    continue
                ordered = _ordered(group)
                value = aggregate([m.get("value") for m in ordered], ind["aggregate"])
                items.append({
                    "indicator": ind["key"],
                    "label": ind["label"],
                    "unit": ind["unit"],
                    "aggregate": ind["aggregate"],
                    "method": method,
                    "value": value,
                    "text": _format_value(value, ind["unit"]),
                    "count": len(ordered),
                    "evidence": ordered[-1].get("evidence") or "",
                    "last_ts": ordered[-1].get("ts"),
                })
            for method, group in by_method.items():  # future methods still show
                ordered = _ordered(group)
                value = aggregate([m.get("value") for m in ordered], ind["aggregate"])
                items.append({
                    "indicator": ind["key"], "label": ind["label"], "unit": ind["unit"],
                    "aggregate": ind["aggregate"], "method": method, "value": value,
                    "text": _format_value(value, ind["unit"]), "count": len(ordered),
                    "evidence": ordered[-1].get("evidence") or "",
                    "last_ts": ordered[-1].get("ts"),
                })
        if items:
            cells[f"{dim_id}|{key}"] = {
                "dimension": dim_id, "product": key, "items": items,
                "runs": len({m.get("run_id") for m in values}),
            }

    ordered_products = sorted(products.values(), key=lambda p: (
        p.get("family") or "", p.get("id") or "", str(p.get("version") or "")))
    missing = [d["id"] for d in chosen if not any(
        c["dimension"] == d["id"] for c in cells.values())]
    return {
        "dimensions": chosen,
        "products": [{"key": product_key(p), "label": product_label(p),
                      "version": p.get("version"), **p} for p in ordered_products],
        "cells": cells,
        "missing": missing,
    }


def report_markdown(title: str, table: dict) -> str:
    lines = [f"# {title}", ""]
    lines.append(f"- 生成时间：{datetime.now().astimezone().isoformat(timespec='seconds')}")
    lines.append(f"- 产品：{len(table['products'])} 个　维度：{len(table['dimensions'])} 个")
    lines.append("")
    lines.append("> 格子里的数字来自一次或多次运行；方法 `脚本 / 人 / LLM` 与次数都在括号里。")
    lines.append("> n=1 是观察，不是成功率；不可比的格子留空。")
    lines.append("")

    products = table["products"]
    lines.append("## 矩阵")
    lines.append("")
    header = ["维度"] + [p["label"] for p in products]
    lines.append("| " + " | ".join(header) + " |")
    lines.append("|" + "---|" * len(header))
    for dim in table["dimensions"]:
        row = [dim["name"]]
        for product in products:
            cell = table["cells"].get(f"{dim['id']}|{product['key']}")
            if not cell:
                row.append("—")
                continue
            bits = []
            for item in cell["items"]:
                bits.append(f"{item['label']} {item['text']}{unit_label(item['unit'])}"
                            f"（{method_label(item['method'])}，{item['count']} 次）")
            row.append("；".join(bits))
        lines.append("| " + " | ".join(row) + " |")
    lines.append("")

    lines.append("## 逐维")
    for dim in table["dimensions"]:
        lines.append("")
        lines.append(f"### {dim['name']}")
        if dim.get("note"):
            lines.append("")
            lines.append(f"_{dim['note']}_")
        any_cell = False
        for product in products:
            cell = table["cells"].get(f"{dim['id']}|{product['key']}")
            if not cell:
                continue
            any_cell = True
            lines.append("")
            lines.append(f"**{product['label']}**（{cell['runs']} 次运行）")
            for item in cell["items"]:
                lines.append(f"- {item['label']}：{item['text']}{unit_label(item['unit'])}"
                             f"（方法 {method_label(item['method'])}，{item['count']} 次）")
                if item.get("evidence"):
                    lines.append(f"  - 证据：`{item['evidence']}`")
        if not any_cell:
            lines.append("")
            lines.append("_还没有数据。_")

    landed = {cell["dimension"] for cell in table["cells"].values()}
    gaps = [d for d in table["dimensions"] if d["id"] not in landed]
    lines.append("")
    lines.append("## 覆盖与缺口")
    lines.append("")
    lines.append(f"- 有数据的维度：{len(landed)} / {len(table['dimensions'])}")
    if gaps:
        lines.append("- 还没有任何数据：" + "、".join(d["name"] for d in gaps))
    if not table["products"]:
        lines.append("- 还没有运行记录：去「运行」页选一个产品、勾维度，先跑一轮。")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("数据来源：`runs/survey/<run_id>/run.json`；定义存在 `~/.config/tool-walkthrough/survey.json`。")
    return "\n".join(lines) + "\n"


def export_report(title: str, dimension_ids=None, root=None) -> dict:
    table = matrix(dimension_ids, root)
    markdown = report_markdown(title or "能力画像", table)
    stamp = datetime.now().strftime("%Y-%m-%d-%H%M%S")
    target = runs_root(root) / REPORT_DIRNAME
    target.mkdir(parents=True, exist_ok=True)
    path = target / f"{stamp}-report.md"
    path.write_text(markdown, encoding="utf-8")
    return {"path": str(path), "markdown": markdown}


# ------------------------------------------------------ measurements (manual)

def _coerce(value, unit: str):
    if unit == "bool":
        if isinstance(value, bool):
            return value
        text = str(value).strip().lower()
        if text in ("1", "true", "yes", "y", "是", "通过"):
            return True
        if text in ("0", "false", "no", "n", "否", "不通过"):
            return False
        raise ValueError(f"“{value}” 不是是/否")
    if unit == "text":
        return str(value)
    number = _number(value)
    if number is None:
        raise ValueError(f"“{value}” 不是数字")
    return int(number) if float(number).is_integer() else number


def build_measurements(scenario: dict, dimensions: list[dict], values: dict,
                       method: str = "human") -> list[dict]:
    """Turn `{indicator_key: value}` into measurement rows for this scenario."""
    if not isinstance(values, dict):
        raise ValueError("measurements 必须是对象")
    dims = {d["id"]: d for d in dimensions}
    allowed: dict[str, dict] = {}
    for dim_id in scenario["dimensions"]:
        dim = dims.get(dim_id)
        if not dim:
            continue
        for ind in dim["indicators"]:
            allowed[ind["key"]] = {"dimension": dim_id, **ind}
    unknown = [key for key in values if key not in allowed]
    if unknown:
        raise ValueError("这条场景不认识这些指标：" + ", ".join(sorted(unknown)))
    out = []
    for dim_id in scenario["dimensions"]:
        dim = dims.get(dim_id)
        if not dim:
            continue
        for ind in dim["indicators"]:
            if ind["key"] not in values:
                continue
            raw = values[ind["key"]]
            if raw is None or (isinstance(raw, str) and not raw.strip()):
                continue
            out.append({
                "dimension": dim_id,
                "indicator": ind["key"],
                "value": _coerce(raw, ind["unit"]),
                "unit": ind["unit"],
                "method": method,
            })
    return out


def snapshot(scenario: dict, dimensions: list[dict]) -> dict:
    blob = json.dumps({"scenario": scenario, "dimensions": dimensions},
                      ensure_ascii=False, sort_keys=True)
    return {
        "scenario_hash": hashlib.sha256(blob.encode("utf-8")).hexdigest()[:12],
        "dimension_defs": {d["id"]: d for d in dimensions if d["id"] in scenario["dimensions"]},
    }


def now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")
