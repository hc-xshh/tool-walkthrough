#!/usr/bin/env python3
"""Walkthrough Workbench — one local page for the whole harness.

  python3 workbench/server.py            # http://127.0.0.1:8790/
  python3 workbench/server.py --port 8791

What it does:
  * stores the LLM endpoint + key in ~/.config/tool-walkthrough/config.json (0600)
  * starts a walkthrough run (`harness/wt.py agent`) with that key
  * starts an eval run (`code-eval/tools/run_tool.py`) with a whitelisted driver
  * streams the job log and serves the artifacts the run produced

What it deliberately is not: a multi-user service. It binds loopback only,
requires a per-process token on every write, checks Host/Origin against
DNS-rebinding, and never returns the API key to the browser.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import time
from datetime import datetime
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
WEB = HERE / "web"
RUNS = ROOT / "runs"
EVAL = ROOT / "code-eval"
PY = sys.executable

sys.path.insert(0, str(HERE))
import apps  # noqa: E402
import config  # noqa: E402
import deps  # noqa: E402
import jobs  # noqa: E402

deps.ensure()  # workbench/.deps first, if the user installed it

RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,80}$")
TOKEN = secrets.token_urlsafe(24)
LAST_OPENED: dict[str, float] = {}  # run_id -> monotonic seconds

DRIVERS = {
    "drive_codex.py": "Codex CLI",
    "drive_trae.py": "TRAE CN（GUI）",
    "drive_cursor.py": "Cursor（GUI）",
    "drive_qoder.py": "Qoder CN（GUI）",
}

# GUI drivers attach over CDP; if the port is closed the run would fail 10s later
# with "timeout waiting for workspace-popover", which tells nobody anything.
GUI_PORTS = {
    "drive_qoder.py": 9444,
    "drive_cursor.py": 9562,
    "drive_trae.py": 9339,
}

# CLI drivers need a binary on PATH; GUI drivers need a debug port.
CLI_DRIVERS = {"drive_codex.py": "codex"}

# Flags a driver may receive from the page. Keep this a whitelist: the workbench
# must never turn a form field into arbitrary argv.
ALLOWED_DRIVER_ARGS = {"--skip-workspace"}

CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".md": "text/markdown; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".jsonl": "application/x-ndjson; charset=utf-8",
    ".txt": "text/plain; charset=utf-8",
    ".log": "text/plain; charset=utf-8",
    ".pdf": "application/pdf",
}


def port_open(port: int, timeout: float = 0.6) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout):
            return True
    except OSError:
        return False


def real_desktop_check() -> dict:
    """v6.14 policy: only an active, seated real desktop at :0 is allowed."""
    sys.path.insert(0, str(ROOT / "harness"))
    from wtlib import verify_real_session  # local import: keep startup cheap
    display = os.environ.get("DISPLAY") or ""
    try:
        info = verify_real_session(display or ":0", refresh=True)
    except SystemExit as exc:
        return {
            "id": "real-desktop",
            "label": "真实桌面会话（活跃 seat 的 DISPLAY）",
            "ok": False,
            "detail": str(exc),
            "fix": "在真实桌面会话里启动工作台：export DISPLAY=<该会话的 display>"
                   "（容器/VM 里可能是 :1）和 XAUTHORITY；Xvfb / 无 seat 会话仍会被拒绝",
        }
    return {
        "id": "real-desktop",
        "label": "真实桌面会话（活跃 seat 的 DISPLAY）",
        "ok": True,
        "detail": f"{info.get('type')} · {info.get('display')} · seat {info.get('seat')}",
        "fix": "",
    }


def doctor() -> list[dict]:
    """Everything a run needs, as rows the Settings page can render."""
    checks = []
    miss = deps.missing()
    checks.append({
        "id": "deps",
        "label": "CDP 依赖（websocket-client / requests）",
        "ok": not miss,
        "detail": "已就绪" if not miss else "缺 " + "、".join(miss),
        "fix": "" if not miss else
               "点下面「安装依赖」，或运行：python3 -m pip install --target workbench/.deps "
               "-r harness/requirements.txt",
    })
    for driver, port in GUI_PORTS.items():
        ok = port_open(port)
        fix = "" if ok else f"用 --remote-debugging-port={port} 重启 {DRIVERS[driver]}"
        if not ok and driver == "drive_qoder.py":
            fix += (f"（Linux：/usr/share/qoder-cn-ide/qoder-cn-ide "
                    f"--remote-debugging-port={port}）")
        checks.append({
            "id": f"port-{port}",
            "label": f"{DRIVERS[driver]} 调试端口 {port}",
            "ok": ok,
            "detail": "已监听" if ok else "没有监听（应用不是带 --remote-debugging-port 启动的）",
            "fix": fix,
        })
    xt = shutil.which("xdotool")
    checks.append({
        "id": "xdotool",
        "label": "xdotool（桌面后端 / 原生点击）",
        "ok": bool(xt),
        "detail": xt or "未安装；CDP 后端不受影响",
        "fix": "" if xt else "sudo apt install xdotool（只影响 desktop 后端和原生文件选择器）",
    })
    checks.append(real_desktop_check())
    cfg = config.load()
    checks.append({
        "id": "llm-key",
        "label": "LLM key（走查操作员）",
        "ok": bool(cfg["llm"].get("api_key")),
        "detail": "已配置" if cfg["llm"].get("api_key") else "未配置；只影响走查页",
        "fix": "" if cfg["llm"].get("api_key") else "到「设置」页填写 endpoint 和 key",
    })
    return checks


def driver_available(driver: str) -> tuple[bool, str]:
    binary = CLI_DRIVERS.get(driver)
    if binary:
        found = shutil.which(binary)
        return bool(found), (found or f"没有找到 {binary} 命令")
    port = GUI_PORTS.get(driver)
    if port:
        ok = port_open(port)
        return ok, ("调试端口已监听" if ok else f"调试端口 {port} 没有监听")
    return True, ""


def desktop_problem() -> str | None:
    """v6.14 gate: no virtual displays. Everything CDP/desktop needs :0."""
    if sys.platform != "linux":
        return None
    info = real_desktop_check()
    if info["ok"]:
        return None
    return f"{info['detail']}；{info['fix']}"


def driver_problems(driver: str) -> list[str]:
    """Reasons a driver cannot work right now, in plain language."""
    issues = []
    if driver in GUI_PORTS:
        problem = desktop_problem()
        if problem:
            issues.append(problem)
    binary = CLI_DRIVERS.get(driver)
    if binary and not shutil.which(binary):
        issues.append(f"没有找到 {binary} 命令：先安装 Codex CLI，"
                      f"或在评测页换一个已就绪的驱动器")
        return issues
    port = GUI_PORTS.get(driver)
    if not port:
        return issues
    if importlib.util.find_spec("websocket") is None:
        issues.append("当前 Python 缺 websocket-client，CDP 驱动起不来："
                      "pip install -r harness/requirements.txt（要用同一个解释器）")
    if not port_open(port):
        issues.append(f"{DRIVERS[driver]} 的调试端口 {port} 没有监听："
                      f"先带 --remote-debugging-port={port} 启动被测应用，再回来跑")
    return issues


def tasks() -> list[dict]:
    out = []
    for path in sorted((EVAL / "tasks").glob("*.json")):
        try:
            spec = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            continue
        out.append({
            "id": spec["id"],
            "title": spec.get("title", spec["id"]),
            "level": spec.get("level"),
            "category": spec.get("category"),
            "complexity": spec.get("complexity"),
            "tags": spec.get("tags") or [],
        })
    out.sort(key=lambda t: (t.get("level") or 0, t["id"]))
    return out


TASKS = tasks()
TASK_IDS = {t["id"] for t in TASKS}


def _rel(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:  # tests relocate runs/ under a temp dir
        return str(path)


def artifacts(run_dir: Path) -> list[dict]:
    """Files a run produced, relative to the repo root, with light metadata."""
    if run_dir is None or not run_dir.exists():
        return []
    out = []
    for path in sorted(run_dir.rglob("*")):
        if not path.is_file() or path.suffix == ".tmp":
            continue
        rel = _rel(path)
        try:
            stat = path.stat()
        except OSError:
            continue
        out.append({
            "path": rel,
            "name": path.name,
            "size": stat.st_size,
            "mtime": datetime.fromtimestamp(stat.st_mtime).astimezone().isoformat(timespec="seconds"),
            "image": path.suffix.lower() in (".png", ".jpg", ".jpeg"),
            "text": path.suffix.lower() in (".md", ".json", ".jsonl", ".txt", ".log"),
        })
    return out


def dialog_summary(run_dir: Path | None) -> dict:
    """Count dialog events a driver wrote to its trace files."""
    counts = {"handled": 0, "blocked": 0, "unknown": 0}
    items: list[dict] = []
    if run_dir and run_dir.exists():
        for path in sorted(run_dir.rglob("*.trace.jsonl")):
            try:
                lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                continue
            for line in lines:
                try:
                    record = json.loads(line)
                except ValueError:
                    continue
                event = str(record.get("event") or "")
                if not event.startswith("dialog_"):
                    continue
                kind = event.split("_", 1)[1]
                if kind in counts:
                    counts[kind] += 1
                items.append({
                    "kind": kind,
                    "ts": record.get("ts"),
                    "detail": str(record.get("reason") or record.get("text")
                                  or record.get("label") or record.get("marker") or "")[:120],
                })
    return {**counts, "items": items[-8:]}


def drivers_state() -> list[dict]:
    out = []
    for driver_id, label in DRIVERS.items():
        ok, why = driver_available(driver_id)
        out.append({"id": driver_id, "label": label, "port": GUI_PORTS.get(driver_id),
                    "available": ok, "why": why})
    return out


def build_state() -> dict:
    cfg = config.load()
    return {
        "config": config.public(cfg),
        "tasks": TASKS,
        "drivers": drivers_state(),
        "jobs": jobs.list_jobs(20),
        "defaults": {"backend": "cdp", "port": 9339, "max_steps": 20},
        "repo": {"root": str(ROOT), "runs": str(RUNS)},
    }


def run_dir_for(run_id: str) -> Path:
    return RUNS / run_id


def start_walkthrough(body: dict) -> dict:
    goal = str(body.get("goal") or "").strip()
    if not goal:
        raise ValueError("goal is required")
    if len(goal) > 2000:
        raise ValueError("goal is too long (max 2000 chars)")

    backend = str(body.get("backend") or "cdp")
    if backend not in ("cdp", "desktop"):
        raise ValueError("backend must be cdp or desktop")
    try:
        port = int(body.get("port") or 9339)
        max_steps = int(body.get("max_steps") or 20)
    except (TypeError, ValueError):
        raise ValueError("port and max_steps must be integers") from None
    if not 1 <= port <= 65535:
        raise ValueError("port out of range")
    if not 1 <= max_steps <= 50:
        raise ValueError("max_steps must be 1..50")

    run_id = str(body.get("run_id") or "").strip() or jobs.new_id("walkthrough")
    if not RUN_ID_RE.fullmatch(run_id):
        raise ValueError("run_id may only contain letters, digits, dot, underscore, hyphen")
    run_dir = run_dir_for(run_id)
    if run_dir.exists() and any(run_dir.iterdir()):
        raise ValueError(f"run directory already exists: {run_id}")

    problem = desktop_problem()
    if problem:
        raise ValueError(problem)

    cfg = config.load()
    if not cfg["llm"].get("api_key"):
        raise ValueError("还没有配置 LLM key：先到「设置」页填 endpoint 和 key")

    # Create the run skeleton with the harness itself, so templates and
    # harness.json exist exactly as they would on the command line.
    made = subprocess.run(
        [PY, str(ROOT / "harness" / "wt.py"), "new-run", run_id],
        cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if made.returncode != 0:
        raise ValueError("new-run failed: " + (made.stderr or made.stdout).strip()[:400])

    argv = [
        PY, str(ROOT / "harness" / "wt.py"),
        "--run", f"runs/{run_id}",
        "agent", "--goal", goal,
        "--backend", backend,
        "--port", str(port),
        "--max-steps", str(max_steps),
    ]
    if body.get("dry_run"):
        argv.append("--dry-run")
    if body.get("ocr") and backend == "desktop":
        argv.append("--ocr")
    display = str(body.get("display") or "").strip()
    if display and backend == "desktop":
        argv += ["--display", display]

    title = goal.splitlines()[0][:80]
    return jobs.start(
        kind="walkthrough", title=title, argv=argv,
        env=deps.annotate(config.child_env(cfg)), cwd=ROOT,
        meta={"goal": goal, "backend": backend, "port": port,
              "max_steps": max_steps, "dry_run": bool(body.get("dry_run"))},
        run_dir=run_dir, job_id=run_id,
    )


def run_dir_blocker(run_id: str) -> str | None:
    """None when the run directory may be used.

    A directory created by `open_workspace` (marker file, no job, no results)
    is meant to be reused by the following start; anything else is a collision.
    """
    run_dir = RUNS / run_id
    if not run_dir.exists() or not any(run_dir.iterdir()):
        return None
    if (jobs.JOBS / f"{run_id}.json").exists():
        return f"run {run_id} 已经跑过；换一个 run id 再试"
    results = run_dir / "results"
    if results.exists() and any(results.iterdir()):
        return f"run {run_id} 下已经有结果；换一个 run id 再试"
    if (run_dir / ".workspace.json").exists():
        return None
    # Directories prepared before the marker existed: only a work/ skeleton.
    entries = {item.name for item in run_dir.iterdir()}
    if entries <= {"work"} and (run_dir / "work").is_dir():
        return None
    return f"目录 runs/{run_id} 已存在且不是工作台预建的；换一个 run id"


def open_workspace(body: dict) -> dict:
    """Create the first task's workdir and open it in Qoder, so no native dialog."""
    task = str(body.get("task") or "").strip()
    if task not in TASK_IDS:
        raise ValueError("unknown task: " + (task or "(empty)"))
    run_id = str(body.get("run_id") or "").strip() or jobs.new_id("eval")
    if not RUN_ID_RE.fullmatch(run_id):
        raise ValueError("run_id may only contain letters, digits, dot, underscore, hyphen")
    blocker = run_dir_blocker(run_id)
    if blocker:
        raise ValueError(blocker)
    run_dir = RUNS / run_id
    workdir = run_dir / "work" / f"{task}-r1"
    workdir.mkdir(parents=True, exist_ok=True)
    LAST_OPENED[run_id] = time.monotonic()
    (run_dir / ".workspace.json").write_text(json.dumps({
        "task": task, "run_id": run_id, "created_at": datetime.now().isoformat(timespec="seconds"),
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    apps.open_folder("qoder", workdir)
    return {"run_id": run_id, "path": _rel(workdir)}


def start_eval(body: dict) -> dict:
    driver = str(body.get("driver") or "").strip()
    if driver not in DRIVERS:
        raise ValueError("driver not allowed: " + (driver or "(empty)"))
    issues = driver_problems(driver)
    if issues:
        raise ValueError("；".join(issues))
    extra = body.get("driver_args") or []
    if not isinstance(extra, list):
        raise ValueError("driver_args must be a list")
    extra = [str(arg) for arg in extra]
    bad = [arg for arg in extra if arg not in ALLOWED_DRIVER_ARGS]
    if bad:
        raise ValueError("driver argument not allowed: " + ", ".join(bad))
    if driver == "drive_qoder.py" and os.name != "nt" and "--skip-workspace" not in extra:
        raise ValueError("Linux 上 Qoder 建工作区依赖原生文件夹选择器，驱动建不了；"
                         "先在评测页点「在 Qoder 中打开任务目录」（会自动勾选），"
                         "或手动勾上「工作区已手动建好」")
    picked = body.get("tasks") or []
    if not isinstance(picked, list) or not picked:
        raise ValueError("select at least one task")
    picked = [str(t).strip() for t in picked]
    unknown = [t for t in picked if t not in TASK_IDS]
    if unknown:
        raise ValueError("unknown task(s): " + ", ".join(unknown))
    if len(set(picked)) != len(picked):
        raise ValueError("duplicate task ids")
    try:
        reps = int(body.get("reps") or 1)
    except (TypeError, ValueError):
        raise ValueError("reps must be an integer") from None
    if not 1 <= reps <= 10:
        raise ValueError("reps must be 1..10")

    run_id = str(body.get("run_id") or "").strip() or jobs.new_id("eval")
    if not RUN_ID_RE.fullmatch(run_id):
        raise ValueError("run_id may only contain letters, digits, dot, underscore, hyphen")
    run_dir = run_dir_for(run_id)
    blocker = run_dir_blocker(run_id)
    if blocker:
        raise ValueError(blocker)

    # Opening the folder is part of starting a Qoder run: one less button, and
    # impossible to start a run whose window points somewhere else.
    if driver == "drive_qoder.py" and "--skip-workspace" in extra:
        if len(picked) > 1:
            raise ValueError("Qoder 一次只能跑一个任务：工作区绑定到一个目录")
        recent = LAST_OPENED.get(run_id, 0)
        if not recent or time.monotonic() - recent > 600:
            open_workspace({"task": picked[0], "run_id": run_id})

    argv = [
        PY, str(EVAL / "tools" / "run_tool.py"),
        "--driver", driver,
        "--tasks", ",".join(picked),
        "--reps", str(reps),
        "--run", f"runs/{run_id}",
    ]
    if body.get("force"):
        argv.append("--force")
    for arg in extra:
        argv += [f"--driver-arg={arg}"]

    title = f"{DRIVERS[driver]} · {len(picked)} 个任务"
    return jobs.start(
        kind="eval", title=title, argv=argv,
        env=deps.annotate(config.child_env()), cwd=ROOT,
        meta={"driver": driver, "tasks": picked, "reps": reps},
        run_dir=run_dir, job_id=run_id,
    )


class Handler(SimpleHTTPRequestHandler):
    server_version = "WalkthroughWorkbench/1.0"
    protocol_version = "HTTP/1.1"

    # ---------- plumbing ----------

    def log_message(self, fmt, *args):  # keep the console readable
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def json(self, data, status=HTTPStatus.OK):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def error(self, message, status=HTTPStatus.BAD_REQUEST):
        self.json({"error": str(message)}, status)

    def body(self) -> dict:
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            raise ValueError("bad Content-Length") from None
        if length > 64 * 1024:
            raise ValueError("request body too large")
        raw = self.rfile.read(length) if length else b"{}"
        try:
            data = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            raise ValueError("body must be JSON") from None
        if not isinstance(data, dict):
            raise ValueError("body must be a JSON object")
        return data

    def check_origin(self) -> None:
        """Block DNS-rebinding and cross-site posts: Host and Origin must be local."""
        port = self.server.server_address[1]
        allowed = {f"127.0.0.1:{port}", f"localhost:{port}"}
        host = (self.headers.get("Host") or "").strip()
        if host not in allowed:
            raise PermissionError(f"unexpected Host: {host!r}")
        origin = (self.headers.get("Origin") or "").strip()
        if origin and origin not in {f"http://{h}" for h in allowed}:
            raise PermissionError(f"unexpected Origin: {origin!r}")

    def check_token(self) -> None:
        if (self.headers.get("X-WB-Token") or "") != TOKEN:
            raise PermissionError("missing or wrong workbench token")

    # ---------- routes ----------

    def do_GET(self):
        url = urlparse(self.path)
        path = url.path
        try:
            self.check_origin()
        except PermissionError as exc:
            return self.error(exc, HTTPStatus.FORBIDDEN)

        if path in ("/", "/index.html"):
            return self.serve_index()
        if path == "/app.js":
            return self.serve_web("app.js")
        if path == "/styles.css":
            return self.serve_web("styles.css")
        if path == "/api/health":
            return self.json({"ok": True, "job": "workbench"})
        if path == "/api/state":
            return self.json(build_state())
        if path == "/api/config":
            return self.json(config.public())
        if path == "/api/doctor":
            return self.json({"checks": doctor(), "apps": apps.all_status()})
        if path == "/api/tasks":
            return self.json({"tasks": TASKS})
        if path == "/api/jobs":
            return self.json({"jobs": jobs.list_jobs(50)})
        if path == "/api/jobs/file":
            return self.job_file(url)
        m = re.fullmatch(r"/api/jobs/([A-Za-z0-9._-]+)/log", path)
        if m:
            return self.job_log(m.group(1), url)
        m = re.fullmatch(r"/api/jobs/([A-Za-z0-9._-]+)", path)
        if m:
            return self.job_detail(m.group(1))
        return self.error("not found", HTTPStatus.NOT_FOUND)

    def do_POST(self):
        path = urlparse(self.path).path
        try:
            self.check_origin()
            self.check_token()
        except PermissionError as exc:
            return self.error(exc, HTTPStatus.FORBIDDEN)
        try:
            body = self.body()
            if path == "/api/config":
                config.save(body)
                return self.json({"config": config.public()})
            if path == "/api/config/test":
                return self.json(self.test_llm(body))
            if path == "/api/deps/install":
                ok, log = deps.install()
                return self.json({"ok": ok, "log": log, "checks": doctor()})
            m = re.fullmatch(r"/api/apps/([a-z]+)/launch", path)
            if m:
                return self.json({"app": apps.launch(m.group(1), bool(body.get("restart")))})
            if path == "/api/apps/workspace-open":
                return self.json(open_workspace(body))
            if path == "/api/jobs":
                kind = str(body.get("kind") or "")
                if kind == "walkthrough":
                    return self.json({"job": start_walkthrough(body)}, HTTPStatus.CREATED)
                if kind == "eval":
                    return self.json({"job": start_eval(body)}, HTTPStatus.CREATED)
                raise ValueError("kind must be walkthrough or eval")
            m = re.fullmatch(r"/api/jobs/([A-Za-z0-9._-]+)/stop", path)
            if m:
                return self.json({"job": jobs.stop(m.group(1))})
        except ValueError as exc:
            return self.error(exc)
        except KeyError:
            return self.error("job not found", HTTPStatus.NOT_FOUND)
        except Exception as exc:  # noqa: BLE001 - surface it to the page
            return self.error(f"{type(exc).__name__}: {exc}", HTTPStatus.INTERNAL_SERVER_ERROR)
        return self.error("not found", HTTPStatus.NOT_FOUND)

    # ---------- handlers ----------

    def serve_web(self, name: str):
        target = (WEB / name).resolve()
        if not target.is_file():
            return self.error("not found", HTTPStatus.NOT_FOUND)
        data = target.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", CONTENT_TYPES.get(target.suffix, "application/octet-stream"))
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def serve_index(self):
        template = (WEB / "index.html").read_text(encoding="utf-8")
        page = template.replace("{{TOKEN}}", TOKEN)
        data = page.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def job_detail(self, job_id: str):
        record = jobs.load(job_id)
        if record is None:
            return self.error("job not found", HTTPStatus.NOT_FOUND)
        record = jobs.refresh(record)
        run_dir = ROOT / record["run_dir"] if record.get("run_dir") else None
        return self.json({
            "job": record,
            "files": artifacts(run_dir) if run_dir else [],
            "dialogs": dialog_summary(run_dir),
        })

    def job_log(self, job_id: str, url):
        if jobs.load(job_id) is None:
            return self.error("job not found", HTTPStatus.NOT_FOUND)
        lines = int((parse_qs(url.query).get("lines") or ["200"])[0])
        return self.json({"log": jobs.tail(job_id, lines)})

    def job_file(self, url):
        query = parse_qs(url.query)
        rel = (query.get("path") or [""])[0]
        if not rel:
            return self.error("path is required")
        target = (ROOT / rel).resolve()
        runs = RUNS.resolve()
        if not target.is_file() or not target.is_relative_to(runs):
            return self.error("file not found", HTTPStatus.NOT_FOUND)
        data = target.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", CONTENT_TYPES.get(target.suffix, "application/octet-stream"))
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def test_llm(self, body: dict):
        """One tiny chat completion against the stored endpoint."""
        import urllib.error
        import urllib.request
        cfg = config.load()
        llm = dict(cfg["llm"])
        if body.get("api_key"):
            llm["api_key"] = str(body["api_key"]).strip()
        if not llm.get("api_key"):
            raise ValueError("还没有保存 key")
        base = str(llm.get("base_url") or "").rstrip("/")
        endpoint = base if base.endswith("/chat/completions") else base + "/chat/completions"
        payload = json.dumps({
            "model": llm.get("model"),
            "messages": [{"role": "user", "content": "ping"}],
            "max_tokens": 8,
        }).encode("utf-8")
        request = urllib.request.Request(endpoint, data=payload, method="POST", headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {llm['api_key']}",
        })
        started = datetime.now()
        try:
            with urllib.request.urlopen(request, timeout=float(llm.get("timeout") or 30)) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            text = exc.read().decode("utf-8", "replace")[:300]
            raise ValueError(f"HTTP {exc.code}: {text}") from None
        except Exception as exc:  # noqa: BLE001
            raise ValueError(f"cannot reach provider: {exc}") from None
        elapsed = round((datetime.now() - started).total_seconds(), 2)
        model = (data.get("model") if isinstance(data, dict) else None) or llm.get("model")
        return {"ok": True, "model": model, "elapsed_s": elapsed}


def check_loopback(host: str) -> None:
    if host not in ("127.0.0.1", "localhost", "::1"):
        raise SystemExit("refusing to bind a non-loopback address; "
                         "this workbench has no login and is single-user only")


def main() -> int:
    ap = argparse.ArgumentParser(description="Local workbench for the walkthrough harness")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8790)
    a = ap.parse_args()
    check_loopback(a.host)

    if not (WEB / "index.html").is_file():
        print(f"missing UI files under {WEB}", file=sys.stderr)
        return 2
    cfg = config.public()
    missing = [m for m in ("websocket", "requests")
               if importlib.util.find_spec(m) is None]
    if missing:
        print(f"warning: missing {', '.join(missing)}; CDP drivers and the CDP "
              f"walkthrough backend will fail.\n"
              f"         Fix from the page (设置 → 安装依赖) or run:\n"
              f"         python3 -m pip install --target workbench/.deps -r harness/requirements.txt",
              file=sys.stderr)
    server = ThreadingHTTPServer((a.host, a.port), Handler)
    server.daemon_threads = True
    port = server.server_address[1]
    print(f"Walkthrough Workbench  http://{a.host}:{port}/")
    print(f"config                 {cfg['path']}  "
          f"({'key set: ' + cfg['key_hint'] if cfg['configured'] else 'no key yet'})")
    print("Ctrl-C to stop. Jobs keep their logs under runs/workbench/jobs/.")

    # SIGTERM (kill, or start.sh restarting us) must take the same path as
    # Ctrl-C so child jobs are stopped instead of orphaned by the exit.
    def on_sigterm(_signum, _frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, on_sigterm)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopping…")
    finally:
        jobs.stop_all()
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
