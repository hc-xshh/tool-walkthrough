#!/usr/bin/env python3
"""LLM-operated walkthrough loop.

The harness supplies deterministic eyes and hands: screenshots, DOM/OCR text,
clicks, typing and evidence logging. The model only chooses the next action.
That split is deliberate: a provider outage, a wrong click, or a missing
screenshot must be debuggable without asking the model what happened.

First version:
  * CDP backend for Chromium/Electron products (screenshots + DOM + input)
  * Desktop backend for Linux X11 (screenshot + xdotool input)
  * JSON-only action protocol; one correction attempt per malformed reply
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

from llm_client import ChatClient, user_message
from wtlib import OS, log_event, which_any

MAX_OBSERVATION_CHARS = 6000
MAX_TYPE_CHARS = 4000
MAX_FINDINGS = 50
REPEAT_LIMIT = 3
SEVERITIES = {"S0", "S1", "S2", "S3", "S4"}

SYSTEM_PROMPT = """\
你是一个产品走查操作员。你看到的是一张真实屏幕截图和可读文本。
你的任务按用户给出的目标完成一次走查，并在过程中记录实际看到的问题。

每一步只返回一个 JSON 对象，不要 Markdown，不要解释，不要多个对象。

可用动作：
{"action":"click","x":120,"y":80,"reason":"点击输入框"}
  x/y 是截图左上角起的像素坐标，必须在截图范围内。
{"action":"click_text","text":"发送","reason":"点击发送按钮"}
  仅 CDP 后端支持；按可见文字点击。
{"action":"type","text":"你好","reason":"输入测试消息"}
  先点击输入框，再输入。不要输入密码、验证码、支付信息。
{"action":"key","key":"Enter","reason":"提交"}
  支持 Enter、Tab、Escape、Backspace、方向键，以及 ctrl+a 这类组合键。
{"action":"scroll","dy":400,"reason":"向下查看"}
  dy 为正向下，负向上。
{"action":"wait","seconds":1,"reason":"等待生成"}
{"action":"finding","title":"发送后没有错误提示","detail":"...","severity":"S2"}
  记录一条你亲眼看到的问题；severity 用 S0/S1/S2/S3/S4。
{"action":"done","summary":"已完成目标"}
{"action":"blocked","summary":"遇到登录墙，无法继续"}

规则：
- 先观察再行动；不要连续重复同一个无效动作。
- 不要猜测页面内容；只根据截图和文本判断。
- 不要输入或索取密码、验证码、身份证、银行卡、支付信息。
- 遇到登录墙、验证码、权限弹窗，返回 blocked，并说明卡在哪一步。
- 发现的问题必须有证据：当前截图会随 finding 一起保存。
- 完成目标后立即返回 done，不要为了多走几步而继续操作。
"""


class ActionError(ValueError):
    """The model's action is syntactically valid JSON but not executable."""


class OperatorError(RuntimeError):
    """The operator cannot continue safely."""


@dataclass
class Observation:
    step: int
    screenshot: Path
    text: str = ""
    width: int = 0
    height: int = 0
    dpr: float = 1.0
    url: str = ""
    title: str = ""


@dataclass
class StepRecord:
    step: int
    action: str
    detail: str = ""
    result: str = "ok"

    def short(self) -> str:
        return f"{self.step}. {self.action}: {self.detail[:180]} -> {self.result}"


@dataclass
class RunResult:
    status: str
    summary: str
    steps: int
    findings: list[dict[str, Any]] = field(default_factory=list)
    usage: dict[str, Any] = field(default_factory=dict)


class Backend(Protocol):
    name: str

    def capture(self, out: Path) -> Observation: ...
    def click(self, x: float, y: float, button: int = 1) -> None: ...
    def click_text(self, text: str) -> str: ...
    def type_text(self, text: str) -> None: ...
    def press_key(self, key: str) -> None: ...
    def scroll(self, dy: float) -> None: ...
    def close(self) -> None: ...


def _png_size(path: Path) -> tuple[int, int]:
    try:
        with open(path, "rb") as fh:
            head = fh.read(24)
        if head[:8] == b"\x89PNG\r\n\x1a\n":
            return int.from_bytes(head[16:20], "big"), int.from_bytes(head[20:24], "big")
    except OSError:
        pass
    return 0, 0


class CDPBackend:
    """Chromium/Electron backend: DOM text plus real input events."""

    name = "cdp"

    def __init__(self, port: int, match: str | None = None, kind: str = "page", nested: bool = False):
        try:
            import cdp  # local module; imports requests/websocket only when used
        except ImportError as exc:
            raise OperatorError(
                "CDP backend needs the harness requirements: "
                "pip install -r harness/requirements.txt"
            ) from exc
        self.cdp = cdp
        self.client = cdp.CDP(port, match, kind, nested)
        self.kind = kind

    def capture(self, out: Path) -> Observation:
        raw = self.client.cmd("Page.captureScreenshot", {"format": "png"})
        data = (raw.get("result") or {}).get("data")
        if not data:
            raise OperatorError("CDP screenshot returned no data")
        import base64
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(base64.b64decode(data))
        w, h = _png_size(out)
        text = self.client.eval("document.body.innerText") or ""
        url = self.client.eval("location.href") or ""
        title = self.client.eval("document.title") or ""
        try:
            dpr = float(self.client.eval("window.devicePixelRatio") or 1.0)
        except (TypeError, ValueError):
            dpr = 1.0
        return Observation(
            step=0, screenshot=out, text=str(text), width=w, height=h,
            dpr=max(dpr, 0.1), url=str(url), title=str(title),
        )

    def click(self, x: float, y: float, button: int = 1) -> None:
        # The model sees screenshot pixels; CDP input uses CSS pixels.
        cx, cy = x / self._dpr, y / self._dpr
        for kind in ("mouseMoved", "mousePressed", "mouseReleased"):
            self.client.cmd("Input.dispatchMouseEvent", {
                "type": kind, "x": cx, "y": cy,
                "button": "left" if button == 1 else "right",
                "clickCount": 1,
            })

    @property
    def _dpr(self) -> float:
        try:
            return max(float(self.client.eval("window.devicePixelRatio") or 1.0), 0.1)
        except (TypeError, ValueError):
            return 1.0

    def click_text(self, text: str) -> str:
        want = json.dumps(text, ensure_ascii=False)
        js = f"""(() => {{
          const all = Array.from(document.querySelectorAll('button,a,div,span,li,input,textarea,[role=button]'));
          const label = e => (e.innerText || e.getAttribute('aria-label') || e.getAttribute('title') || e.getAttribute('placeholder') || '').trim();
          let hits = all.filter(e => label(e) === {want} && e.offsetParent !== null);
          if (!hits.length) {{
            hits = all.filter(e => label(e).includes({want}) && label(e).length < {len(text) + 16} && e.offsetParent !== null)
              .sort((a,b) => label(a).length - label(b).length);
          }}
          const el = hits[0];
          if (!el) return null;
          el.scrollIntoView({{block:'center'}});
          el.click();
          return label(el).slice(0,80);
        }})()"""
        got = self.client.eval(js)
        if not got:
            raise ActionError(f"click_text found no visible control: {text!r}")
        return str(got)

    def type_text(self, text: str) -> None:
        self.client.cmd("Input.insertText", {"text": text[:MAX_TYPE_CHARS]})

    def press_key(self, key: str) -> None:
        parts = [p.strip().lower() for p in key.split("+") if p.strip()]
        if not parts:
            raise ActionError("key is empty")
        base = parts[-1]
        mods = {"alt": 1, "ctrl": 2, "meta": 4, "shift": 8}
        modifiers = sum(mods.get(p, 0) for p in parts[:-1])
        named = {k.lower(): v for k, v in self.cdp.VK.items()}
        vk = ord(base.upper()) if len(base) == 1 else named.get(base, 13)
        code = ("Key" + base.upper()) if len(base) == 1 else base.capitalize()
        for kind in ("keyDown", "keyUp"):
            self.client.cmd("Input.dispatchKeyEvent", {
                "type": kind, "key": base, "code": code,
                "modifiers": modifiers,
                "windowsVirtualKeyCode": vk, "nativeVirtualKeyCode": vk,
            })

    def scroll(self, dy: float) -> None:
        w = max(float(self.client.eval("window.innerWidth") or 800), 1)
        h = max(float(self.client.eval("window.innerHeight") or 600), 1)
        self.client.cmd("Input.dispatchMouseEvent", {
            "type": "mouseWheel", "x": w / 2, "y": h / 2,
            "deltaX": 0, "deltaY": float(dy),
        })

    def close(self) -> None:
        try:
            self.client.ws.close()
        except Exception:
            pass


class DesktopBackend:
    """Linux X11 backend. Other desktop platforms are intentionally loud."""

    name = "desktop"

    def __init__(self, display: str | None = None, geometry: str | None = None, ocr: bool = False):
        if OS != "Linux":
            raise OperatorError(
                f"desktop backend is implemented for Linux/X11 only (this is {OS}); "
                "use --backend cdp for Chromium/Electron products"
            )
        self.display = display or os.environ.get("WALKTHROUGH_DISPLAY", ":0")
        self.geometry = geometry or ""
        self.ocr = ocr
        self._meta: dict[str, Any] = {}

    def capture(self, out: Path) -> Observation:
        from wtshot import capture_screen
        out.parent.mkdir(parents=True, exist_ok=True)
        self._meta = capture_screen(out, self.display, self.geometry)
        w, h = _png_size(out)
        text = self._ocr(out) if self.ocr else ""
        return Observation(step=0, screenshot=out, text=text, width=w, height=h,
                           dpr=1.0, title="")

    def _ocr(self, path: Path) -> str:
        tess = which_any(["tesseract"])
        if not tess:
            return ""
        try:
            p = subprocess.run(
                [tess, str(path), "stdout", "-l", "chi_sim+eng", "--psm", "11", "tsv"],
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30,
            )
        except (OSError, subprocess.TimeoutExpired):
            return ""
        words = []
        for line in (p.stdout or "").splitlines()[1:]:
            cols = line.split("\t")
            if len(cols) >= 12 and cols[11].strip():
                words.append(cols[11].strip())
        return " ".join(words)

    def _screen_xy(self, x: float, y: float) -> tuple[float, float]:
        scale = float(self._meta.get("scale") or 1.0)
        ox = float(self._meta.get("origin_x") or 0)
        oy = float(self._meta.get("origin_y") or 0)
        return ox + x / max(scale, 0.01), oy + y / max(scale, 0.01)

    def click(self, x: float, y: float, button: int = 1) -> None:
        sx, sy = self._screen_xy(x, y)
        subprocess.run(
            ["xdotool", "mousemove", str(int(sx)), str(int(sy)), "click", str(button)],
            check=True, env=dict(os.environ, DISPLAY=self.display),
        )

    def click_text(self, text: str) -> str:
        raise ActionError("desktop backend does not support click_text; use click coordinates")

    def type_text(self, text: str) -> None:
        subprocess.run(
            ["xdotool", "type", "--clearmodifiers", "--delay", "12", text[:MAX_TYPE_CHARS]],
            check=True, env=dict(os.environ, DISPLAY=self.display),
        )

    def press_key(self, key: str) -> None:
        subprocess.run(
            ["xdotool", "key", "--clearmodifiers", key],
            check=True, env=dict(os.environ, DISPLAY=self.display),
        )

    def scroll(self, dy: float) -> None:
        button = "5" if dy >= 0 else "4"
        count = max(1, min(10, int(abs(dy) / 120) or 1))
        for _ in range(count):
            subprocess.run(
                ["xdotool", "click", button],
                check=True, env=dict(os.environ, DISPLAY=self.display),
            )

    def close(self) -> None:
        pass


def _json_object(text: str) -> dict[str, Any]:
    """Extract the first JSON object from a model reply (fenced or not)."""
    raw = (text or "").strip()
    if not raw:
        raise ActionError("empty model response")
    decoder = json.JSONDecoder()
    for match in re.finditer(r"\{", raw):
        try:
            obj, _ = decoder.raw_decode(raw[match.start():])
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            return obj
    raise ActionError("model response did not contain a JSON object")


def parse_action(text: str) -> dict[str, Any]:
    obj = _json_object(text)
    action = str(obj.get("action") or "").strip().lower()
    if action not in {"click", "click_text", "type", "key", "scroll", "wait",
                      "finding", "done", "blocked"}:
        raise ActionError(f"unknown action: {action!r}")
    if action == "click":
        for key in ("x", "y"):
            if isinstance(obj.get(key), bool) or not isinstance(obj.get(key), (int, float)):
                raise ActionError("click needs numeric x and y")
    elif action == "click_text":
        if not str(obj.get("text") or "").strip():
            raise ActionError("click_text needs text")
    elif action == "type":
        if not isinstance(obj.get("text"), str) or not obj["text"]:
            raise ActionError("type needs non-empty text")
        obj["text"] = obj["text"][:MAX_TYPE_CHARS]
    elif action == "key":
        if not str(obj.get("key") or "").strip():
            raise ActionError("key needs a key name")
    elif action == "scroll":
        if isinstance(obj.get("dy"), bool) or not isinstance(obj.get("dy"), (int, float)):
            raise ActionError("scroll needs numeric dy")
    elif action == "wait":
        seconds = obj.get("seconds", 1)
        if isinstance(seconds, bool) or not isinstance(seconds, (int, float)):
            raise ActionError("wait needs numeric seconds")
        obj["seconds"] = max(0.0, min(float(seconds), 10.0))
    elif action == "finding":
        if not str(obj.get("title") or "").strip():
            raise ActionError("finding needs a title")
        sev = str(obj.get("severity") or "S3").upper()
        obj["severity"] = sev if sev in SEVERITIES else "S3"
        obj["title"] = str(obj["title"])[:200]
        obj["detail"] = str(obj.get("detail") or "")[:1200]
    elif action in {"done", "blocked"}:
        obj["summary"] = str(obj.get("summary") or "")[:1200]
    obj["action"] = action
    obj["reason"] = str(obj.get("reason") or "")[:300]
    return obj


def _safe_reason(action: dict[str, Any]) -> str:
    # Typed text may contain user data; never copy it into the shared event log.
    if action["action"] == "type":
        return f"typed {len(action.get('text') or '')} chars"
    return str(action.get("reason") or "")[:300]


def _usage_add(total: dict[str, Any], usage: dict[str, Any]) -> None:
    for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
        value = usage.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            total[key] = total.get(key, 0) + int(value)


def _observation_prompt(obs: Observation, goal: str, step: int, max_steps: int,
                        history: list[StepRecord]) -> str:
    text = obs.text[:MAX_OBSERVATION_CHARS]
    if len(obs.text) > MAX_OBSERVATION_CHARS:
        text += "\n...[文本已截断]"
    recent = "\n".join(r.short() for r in history[-8:]) or "(还没有动作)"
    return f"""\
目标：{goal}

当前是第 {step}/{max_steps} 步。
页面标题：{obs.title or "(未知)"}
页面地址：{obs.url or "(未知)"}
截图尺寸：{obs.width}x{obs.height}，devicePixelRatio={obs.dpr:g}

可读文本（DOM 或 OCR，最多 {MAX_OBSERVATION_CHARS} 字）：
{text or "(没有可读文本，请依赖截图)"}

最近动作：
{recent}

请根据当前截图决定下一步。只返回一个 JSON 对象。
如果目标已完成，返回 done。如果被登录/验证码挡住，返回 blocked。
"""


def _write_outputs(run: Path, result: RunResult, goal: str, model: str,
                   started: str, finished: str) -> None:
    run.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": 1,
        "goal": goal,
        "model": model,
        "status": result.status,
        "summary": result.summary,
        "steps": result.steps,
        "findings": result.findings,
        "usage": result.usage,
        "started": started,
        "finished": finished,
    }
    (run / "findings.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    lines = [
        "# LLM 走查记录",
        "",
        f"- 目标：{goal}",
        f"- 模型：`{model}`",
        f"- 状态：**{result.status}**",
        f"- 步数：{result.steps}",
        f"- 时间：{started} → {finished}",
        "",
        "## 发现",
        "",
    ]
    if result.findings:
        for i, f in enumerate(result.findings, 1):
            lines += [
                f"### {i}. {f['severity']} · {f['title']}",
                "",
                str(f.get("detail") or ""),
                "",
                f"证据：`{f.get('screenshot', '')}`",
                "",
            ]
    else:
        lines += ["未记录问题。", ""]
    lines += ["## 总结", "", result.summary or "(无)", ""]
    (run / "agent-summary.md").write_text("\n".join(lines), encoding="utf-8")


class Operator:
    def __init__(self, client: ChatClient, backend: Backend, run: Path, goal: str,
                 max_steps: int = 20, max_seconds: float = 600,
                 max_total_tokens: int = 200_000, dry_run: bool = False):
        self.client = client
        self.backend = backend
        self.run = run
        self.goal = goal
        self.max_steps = max(1, min(int(max_steps), 50))
        self.max_seconds = max(10.0, float(max_seconds))
        self.max_total_tokens = max(1000, int(max_total_tokens))
        self.dry_run = dry_run
        self.history: list[StepRecord] = []
        self.findings: list[dict[str, Any]] = []
        self.usage: dict[str, Any] = {}
        self.started = datetime.now().astimezone().isoformat(timespec="seconds")

    def _log(self, **fields: Any) -> None:
        log_event(self.run, **fields)

    def _observe(self, step: int, suffix: str = "") -> Observation:
        name = f"agent-step-{step:02d}{suffix}.png"
        obs = self.backend.capture(self.run / "shots" / name)
        obs.step = step
        self._log(
            action="shot", step=step, screenshot=str(obs.screenshot),
            detail=f"{obs.width}x{obs.height}",
        )
        return obs

    def _ask(self, obs: Observation, step: int) -> tuple[dict[str, Any], str]:
        prompt = _observation_prompt(obs, self.goal, step, self.max_steps, self.history)
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            user_message(prompt, obs.screenshot),
        ]
        reply = self.client.chat(messages)
        _usage_add(self.usage, reply.usage)
        try:
            return parse_action(reply.text), reply.text
        except ActionError as first_error:
            self._log(action="agent", step=step, result="error",
                      detail=f"invalid action: {first_error}")
            correction = (
                f"你上一条输出不是可执行的动作：{first_error}。"
                "只返回一个 JSON 对象，不要 Markdown，不要解释。"
            )
            messages += [
                {"role": "assistant", "content": reply.text[:4000]},
                {"role": "user", "content": correction},
            ]
            retry = self.client.chat(messages)
            _usage_add(self.usage, retry.usage)
            try:
                return parse_action(retry.text), retry.text
            except ActionError as second_error:
                raise OperatorError(
                    f"model returned an invalid action twice: {second_error}"
                ) from None

    def _execute(self, action: dict[str, Any], obs: Observation) -> StepRecord:
        kind = action["action"]
        detail = _safe_reason(action)
        if kind == "click":
            x, y = float(action["x"]), float(action["y"])
            if x < 0 or y < 0 or x >= obs.width or y >= obs.height:
                raise ActionError(
                    f"click ({x:.0f},{y:.0f}) is outside the {obs.width}x{obs.height} screenshot"
                )
            self.backend.click(x, y)
            record = StepRecord(obs.step, "click", f"({x:.0f},{y:.0f}) {detail}")
        elif kind == "click_text":
            got = self.backend.click_text(str(action["text"]))
            record = StepRecord(obs.step, "click_text", f"{got} {detail}")
        elif kind == "type":
            self.backend.type_text(action["text"])
            record = StepRecord(obs.step, "type", _safe_reason(action))
        elif kind == "key":
            self.backend.press_key(str(action["key"]))
            record = StepRecord(obs.step, "key", f"{action['key']} {detail}")
        elif kind == "scroll":
            self.backend.scroll(float(action["dy"]))
            record = StepRecord(obs.step, "scroll", f"dy={action['dy']} {detail}")
        elif kind == "wait":
            time.sleep(float(action["seconds"]))
            record = StepRecord(obs.step, "wait", f"{action['seconds']}s")
        else:
            raise ActionError(f"cannot execute action {kind!r}")
        return record

    def _action_event(self, action: dict[str, Any], record: StepRecord,
                      screenshot: Path | None) -> None:
        kind = action["action"]
        # Use the same action names `wt.py audit` understands for clicks;
        # evidence is the screenshot captured after the action.
        event_action = {
            "click": "cdp:clickxy" if self.backend.name == "cdp" else "click",
            "click_text": "cdp:clicktext",
        }.get(kind, f"agent_{kind}")
        fields: dict[str, Any] = {
            "action": event_action,
            "step": record.step,
            "result": record.result,
            "detail": record.detail[:300],
        }
        if screenshot:
            fields["screenshot"] = str(screenshot)
        if kind == "click":
            fields["target"] = record.detail.split()[0]
        self._log(**fields)

    def run_loop(self) -> RunResult:
        self.run.mkdir(parents=True, exist_ok=True)
        (self.run / "shots").mkdir(parents=True, exist_ok=True)
        start = time.monotonic()
        status = "max_steps"
        summary = "达到步数上限，未完成目标。"
        try:
            for step in range(1, self.max_steps + 1):
                elapsed = time.monotonic() - start
                if elapsed > self.max_seconds:
                    status, summary = "timeout", f"超过时间预算 {self.max_seconds:.0f}s"
                    break
                obs = self._observe(step)
                action, _raw = self._ask(obs, step)
                kind = action["action"]
                self._log(action="agent", step=step, model_action=kind,
                          reason=_safe_reason(action), screenshot=str(obs.screenshot),
                          total_tokens=self.usage.get("total_tokens", 0))
                if kind == "done":
                    status, summary = "done", action.get("summary") or "已完成目标。"
                    self.history.append(StepRecord(step, "done", summary))
                    break
                if kind == "blocked":
                    status, summary = "blocked", action.get("summary") or "遇到阻塞，无法继续。"
                    self.history.append(StepRecord(step, "blocked", summary))
                    break
                if kind == "finding":
                    finding = {
                        "step": step,
                        "title": action["title"],
                        "detail": action.get("detail", ""),
                        "severity": action["severity"],
                        "screenshot": str(obs.screenshot),
                    }
                    self.findings.append(finding)
                    self._log(action="agent_finding", step=step, severity=finding["severity"],
                              title=finding["title"], screenshot=str(obs.screenshot))
                    self.history.append(StepRecord(step, "finding", finding["title"]))
                    if len(self.findings) >= MAX_FINDINGS:
                        status, summary = "max_findings", "发现数量达到上限。"
                        break
                    continue
                if self.dry_run:
                    self.history.append(StepRecord(step, kind, f"dry-run: {_safe_reason(action)}"))
                    continue
                try:
                    record = self._execute(action, obs)
                except (ActionError, OSError, subprocess.SubprocessError) as exc:
                    record = StepRecord(step, kind, f"error: {exc}", result="error")
                    self._log(action="agent_step", step=step, result="error",
                              detail=str(exc)[:300], screenshot=str(obs.screenshot))
                after = self._observe(step, "-after")
                self.history.append(record)
                self._action_event(action, record, after.screenshot)
                # Repeat detection: a model stuck on the same click should stop,
                # not burn the whole step budget.
                sigs = [f"{r.action}:{r.detail}" for r in self.history if r.action == kind]
                if len(sigs) >= REPEAT_LIMIT and len(set(sigs[-REPEAT_LIMIT:])) == 1:
                    status, summary = "repeated_action", "连续重复同一动作，已停止。"
                    break
                if self.usage.get("total_tokens", 0) > self.max_total_tokens:
                    status, summary = "token_budget", "token 预算用完，已停止。"
                    break
            else:
                status = "max_steps"
                summary = "达到步数上限，未完成目标。"
        finally:
            self.backend.close()
        result = RunResult(status=status, summary=summary,
                           steps=len(self.history), findings=self.findings,
                           usage=dict(self.usage))
        finished = datetime.now().astimezone().isoformat(timespec="seconds")
        _write_outputs(self.run, result, self.goal, self.client.config.model,
                       self.started, finished)
        self._log(action="agent_finish", status=status, steps=result.steps,
                  findings=len(self.findings), usage=self.usage)
        return result


def make_backend(name: str, *, port: int = 9339, match: str | None = None,
                 kind: str = "page", nested: bool = False, display: str | None = None,
                 geometry: str | None = None, ocr: bool = False) -> Backend:
    if name == "cdp":
        return CDPBackend(port, match, kind, nested)
    if name == "desktop":
        return DesktopBackend(display, geometry, ocr)
    raise OperatorError(f"unknown backend: {name}")
