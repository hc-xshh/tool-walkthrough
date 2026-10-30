#!/usr/bin/env python3
"""The thing behind 开始自动体验.

A scenario is a list of prompts (a multi-turn conversation) plus the dimensions
it should light up. The executor picks an adapter for the product, drives it
turn by turn in a scratch workspace, and writes the same `run.json` the command
path writes — so the report does not care which path produced the data.

Adapters are deliberately boring: they know how to start a product, send one
prompt, and say when that turn is over. Everything measurable (duration, tool
calls, token usage, changed files) is collected by the shared runner, not by
each adapter.

This module is internal. Nothing in the UI mentions adapters or executors; the
only user-visible state is "开始自动体验" being available or not.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import threading
import time
from pathlib import Path

import survey

ROOT = Path(__file__).resolve().parent.parent


class Result:
    """What one adapter observed for one product."""

    def __init__(self):
        self.status = "ok"          # ok / failed / timeout
        self.duration_s = 0.0
        self.first_token_ms: int | None = None
        self.steps = 0
        self.failures = 0
        self.usage = {"input_tokens": 0, "output_tokens": 0, "cached_input_tokens": 0,
                      "total_tokens": 0}
        self.last_message = ""
        self.evidence = ""
        self.notes = ""

    def add_usage(self, usage: dict) -> None:
        for key in ("input_tokens", "output_tokens", "cached_input_tokens"):
            self.usage[key] = self.usage.get(key, 0) + int(usage.get(key) or 0)
        self.usage["total_tokens"] = (self.usage["input_tokens"]
                                      + self.usage["output_tokens"])


class Adapter:
    """One product family. `send` returns (returncode, stdout_lines, seconds)."""

    label = "adapter"

    def available(self) -> tuple[bool, str]:
        raise NotImplementedError

    def preflight(self) -> str | None:
        """A user-facing reason the product cannot run yet, or None."""
        return None

    def send(self, prompt: str, workdir: Path, timeout_s: int, turn: int,
             first_token: dict) -> tuple[int, list[str], float, bool, str]:
        raise NotImplementedError


def _custom_provider_configured() -> bool:
    """A third-party provider (cc switch, DeepSeek, ...) makes `login` irrelevant.

    `codex login status` only knows about the OpenAI account. People route Codex
    to another provider through ~/.codex/config.toml, where a
    [model_providers.*] block carries its own base_url and token. Reading the
    file is enough; the token itself is never printed or copied anywhere.
    """
    path = Path.home() / ".codex" / "config.toml"
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    return ("[model_providers." in text
            and ("base_url" in text or "requires_openai_auth = false" in text))


_CODEX_STATUS = {"at": 0.0, "problem": None}


class CodexCliAdapter(Adapter):
    label = "Codex CLI"

    def __init__(self) -> None:
        self.binary = shutil.which("codex") or ""

    def available(self) -> tuple[bool, str]:
        if not self.binary:
            return False, "本机没有 codex 命令"
        return True, ""

    def preflight(self) -> str | None:
        now = time.monotonic()
        if now - _CODEX_STATUS["at"] < 60:
            return _CODEX_STATUS["problem"]
        problem = None
        try:
            out = subprocess.run([self.binary, "login", "status"], capture_output=True,
                                 text=True, encoding="utf-8", errors="replace", timeout=10)
            text = ((out.stdout or "") + (out.stderr or "")).lower()
            if "not logged in" in text and not _custom_provider_configured():
                problem = "Codex 还没登录：先在终端运行 codex login"
        except (OSError, subprocess.TimeoutExpired):
            problem = "查不到 Codex 的登录状态"
        _CODEX_STATUS.update({"at": now, "problem": problem})
        return problem

    def send(self, prompt, workdir, timeout_s, turn, first_token):
        if turn == 1:
            args = [self.binary, "exec", "--skip-git-repo-check",
                    "-s", "workspace-write", "--json", prompt]
        else:
            args = [self.binary, "exec", "resume", "--last", "--json", prompt]
        started = time.monotonic()
        lines: list[str] = []
        errors: list[str] = []
        timed_out = False
        proc = subprocess.Popen(
            args, cwd=str(workdir), text=True, encoding="utf-8", errors="replace",
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )

        def pump() -> None:
            for line in proc.stdout:  # type: ignore[union-attr]
                if first_token["at"] is None:
                    first_token["at"] = time.monotonic()
                lines.append(line)
            for line in proc.stderr:  # drain, so the child never blocks on a pipe
                errors.append(line)

        thread = threading.Thread(target=pump, daemon=True)
        thread.start()
        try:
            rc = proc.wait(timeout=max(1, timeout_s))
        except subprocess.TimeoutExpired:
            proc.kill()
            rc = 124
            timed_out = True
        thread.join(timeout=5)
        for stream in (proc.stdout, proc.stderr):
            try:
                stream.close()  # type: ignore[union-attr]
            except (AttributeError, OSError):
                pass
        return (rc, lines, round(time.monotonic() - started, 1), timed_out,
                "".join(errors)[-4000:])


def adapter_for(product: dict) -> Adapter | None:
    product_id = str(product.get("id") or "").lower()
    if product_id == "codex-cli":
        return CodexCliAdapter()
    return None


def _usage(lines: list[str]) -> dict:
    total = {}
    for line in lines:
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if event.get("type") == "turn.completed":
            usage = event.get("usage") or {}
            for key, value in usage.items():
                total[key] = total.get(key, 0) + int(value or 0)
    return total


def _steps(lines: list[str]) -> int:
    seen = 0
    for line in lines:
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if event.get("type") != "item.completed":
            continue
        item = event.get("item") or {}
        if item.get("type") in ("command_execution", "tool_call", "function_call",
                                "mcp_tool_call", "file_change"):
            seen += 1
    return seen


def _last_message(lines: list[str]) -> str:
    text = ""
    for line in lines:
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            event = json.loads(line)
        except ValueError:
            continue
        item = event.get("item") or {}
        if item.get("type") == "agent_message" and item.get("text"):
            text = item["text"]
        elif event.get("type") == "agent_message" and event.get("message"):
            text = event["message"]
    return text


def _git_repo(workdir: Path) -> Path | None:
    candidates = [workdir] + [p for p in workdir.iterdir() if p.is_dir()][:20] if workdir.exists() else []
    for path in candidates:
        if (path / ".git").exists():
            return path
    return None


def _changed_files(workdir: Path) -> int:
    repo = _git_repo(workdir)
    if repo is None:
        return 0
    try:
        out = subprocess.run(["git", "-C", str(repo), "status", "--porcelain"],
                             capture_output=True, text=True, encoding="utf-8",
                             errors="replace", timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return 0
    return len([line for line in (out.stdout or "").splitlines() if line.strip()])


def _ensure_app(product: dict, log=print) -> None:
    """GUI 产品由运行器自己拉起，用户不需要先手动启动。"""
    app_id = str(product.get("app_id") or "")
    if not app_id:
        return
    import apps as apps_mod  # workbench 模块，避免顶层循环导入

    try:
        status = apps_mod.status(app_id)
    except KeyError:
        return
    if status.get("port_open"):
        return
    log(f"启动 {status['label']}（调试端口 {status['port']}）")
    apps_mod.launch(app_id, restart=bool(status.get("running")))


def run_scenario(scenario: dict, product: dict, dimensions: list[dict],
                 run_id: str, root=None, log=print) -> dict:
    """Drive one product through the scenario and write run.json."""
    adapter = adapter_for(product)
    if adapter is None:
        raise ValueError("这个产品还不能自动体验")
    ok, why = adapter.available()
    if not ok:
        raise ValueError(why)
    problem = adapter.preflight()
    if problem:
        raise ValueError(problem)
    _ensure_app(product, log)

    prompts = [str(p) for p in (scenario.get("prompts") or []) if str(p).strip()]
    if not prompts:
        raise ValueError("这个场景还没有提示词")

    run_dir = survey.run_dir(run_id, root)
    run_dir.mkdir(parents=True, exist_ok=True)
    workdir = run_dir / "work"
    workdir.mkdir(parents=True, exist_ok=True)
    turns_log = run_dir / "turns.jsonl"

    timeout_total = int((scenario.get("command") or {}).get("timeout_s") or 3600)
    deadline = time.monotonic() + timeout_total
    result = Result()
    first_token = {"at": None}
    started = time.monotonic()

    log(f"[{adapter.label}] {product.get('name')} · {len(prompts)} 轮 · 工作目录 {workdir}")
    with turns_log.open("w", encoding="utf-8") as fh:
        for index, prompt in enumerate(prompts, 1):
            remaining = min(int(deadline - time.monotonic()), 1200)
            if remaining <= 0:
                result.status = "timeout"
                result.notes = (result.notes + "\n总时长用完，后面的轮次没有跑").strip()
                log("总时长用完，停在第 %d 轮之前" % index)
                break
            log(f"— 第 {index}/{len(prompts)} 轮（剩余 {remaining}s）")
            try:
                rc, lines, seconds, timed_out, stderr_text = adapter.send(
                    prompt, workdir, remaining, index, first_token)
            except OSError as exc:
                result.status = "failed"
                result.failures += 1
                result.notes = f"{type(exc).__name__}: {exc}"
                log(f"起不来：{exc}")
                break
            usage = _usage(lines)
            result.add_usage(usage)
            result.steps += _steps(lines)
            message = _last_message(lines)
            if message:
                result.last_message = message
            status = "timeout" if timed_out else ("ok" if rc == 0 else "failed")
            if status != "ok":
                result.failures += 1
                result.status = "timeout" if timed_out else "failed"
                tail = (stderr_text or "").strip().splitlines()[-3:]
                if tail:
                    result.notes = (result.notes + "\n" + "\n".join(tail)).strip()
            fh.write(json.dumps({
                "turn": index, "prompt": prompt, "rc": rc, "seconds": seconds,
                "timed_out": timed_out, "usage": usage,
                "stdout": "".join(lines)[-200000:],
            }, ensure_ascii=False) + "\n")
            log(f"  第 {index} 轮：rc={rc} · {seconds}s · {len(lines)} 条事件")
            if status != "ok":
                break  # 这一轮没做完，后面的轮次接不上

    result.duration_s = round(time.monotonic() - started, 1)
    if first_token["at"] is not None:
        result.first_token_ms = int((first_token["at"] - started) * 1000)
    result.evidence = _rel(turns_log, root)
    log(f"完成：{result.status} · {result.duration_s}s · {result.steps} 步 · "
        f"{result.usage['total_tokens']} tokens")

    values = {
        "first_token_ms": result.first_token_ms,
        "task_minutes": round(result.duration_s / 60, 1),
        "steps": result.steps,
        "task_done": result.status == "ok",
        "interventions": 0,
        "files_changed": _changed_files(workdir),
        "failures": result.failures,
    }
    known = {ind["key"] for dim in dimensions if dim["id"] in (scenario.get("dimensions") or [])
             for ind in dim.get("indicators") or []}
    values = {k: v for k, v in values.items() if k in known and v is not None}
    measurements = survey.build_measurements(scenario, dimensions, values, method="script")

    notes = result.notes
    if result.last_message:
        notes = (notes + "\n" + result.last_message[:600]).strip()

    record = {
        "run_id": run_id,
        "ts": survey.now(),
        "product": product,
        "scenario": {"id": scenario.get("id"), "title": scenario.get("title")},
        "dimensions": scenario.get("dimensions") or [],
        "status": result.status,
        "method": "script",
        "confidence": "measured" if measurements else "single",
        "duration_s": result.duration_s,
        "notes": notes,
        "measurements": [{**m, "evidence": result.evidence} for m in measurements],
        "snapshot": survey.snapshot(scenario, dimensions),
        "adapter": adapter.label,
        "usage": result.usage,
    }
    path = survey.write_run(record, root)
    log(f"→ {_rel(path, root)}")
    return record


def _rel(path: Path, root=None) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)
