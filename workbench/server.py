#!/usr/bin/env python3
"""Walkthrough Workbench — one local page for the whole harness.

  python3 workbench/server.py            # http://127.0.0.1:8790/
  python3 workbench/server.py --port 8791

What it does:
  * stores the LLM endpoint + key in ~/.config/tool-walkthrough/config.json (0600)
  * keeps dimensions + scenarios in ~/.config/tool-walkthrough/survey.json
  * runs one scenario against one product and writes runs/survey/<run_id>/run.json
  * builds the dimension x product matrix and exports it as Markdown
  * streams the job log and serves the artifacts the run produced

The old walkthrough / eval job kinds still exist for the CLI path; the page
surfaces are 维度 / 运行 / 报告 (see docs/DIMENSIONS.md).

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

sys.path.insert(0, str(EVAL / "tools"))
import drivers as driver_registry  # noqa: E402
sys.path.insert(0, str(HERE))
import apps  # noqa: E402
import catalog  # noqa: E402
import config  # noqa: E402
import deps  # noqa: E402
import executor  # noqa: E402
import jobs  # noqa: E402
import plugins  # noqa: E402
import survey  # noqa: E402
import websearch  # noqa: E402

deps.ensure()  # workbench/.deps first, if the user installed it

RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,80}$")
TOKEN = secrets.token_urlsafe(24)

# Everything about the tool list comes from code-eval/drivers.json. GUI drivers
# attach over CDP (a closed port fails the run 10s later with a message that
# tells nobody anything); CLI drivers need a binary on PATH.
DRIVERS: dict[str, str] = {}
GUI_PORTS: dict[str, int] = {}
CLI_DRIVERS: dict[str, str] = {}


def refresh_drivers() -> None:
    """Re-read the registry after a custom driver is added or removed."""
    global DRIVERS, GUI_PORTS, CLI_DRIVERS
    DRIVERS = driver_registry.labels()
    GUI_PORTS = driver_registry.gui_ports()
    CLI_DRIVERS = driver_registry.cli_commands()


refresh_drivers()

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
        "label": "LLM key（整理产品信息）",
        "ok": bool(cfg["llm"].get("api_key")),
        "detail": "已配置" if cfg["llm"].get("api_key") else "未配置；只影响一句话加产品",
        "fix": "" if cfg["llm"].get("api_key") else "到「配置」页填写 endpoint 和 key",
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


def drivers_state() -> list[dict]:
    out = []
    for item in driver_registry.state():
        ok, why = driver_available(item["id"])
        out.append({**item, "available": ok, "why": why})
    return out


def build_state() -> dict:
    cfg = config.load()
    return {
        "config": config.public(cfg),
        "drivers": drivers_state(),
        "jobs": jobs.list_jobs(20),
        "defaults": {"backend": "cdp", "port": 9339, "max_steps": 20},
        "repo": {"root": str(ROOT), "runs": str(RUNS)},
        "plugins": {"path": str(plugins.path())},
        "catalog": catalog.load(),
        "discovered": plugins.list_discovered(),
    }


def start_discover(body: dict) -> dict:
    query = str(body.get("query") or "").strip()
    if not query:
        raise ValueError("输入一个产品名，例如：加上 Kimi Work")
    if len(query) > 200:
        raise ValueError("产品名太长（最多 200 字符）")
    cfg = config.load()
    if not config.effective_search_key(cfg):
        raise ValueError("网络搜索还没有可用的 key；先到「配置 → 网络搜索」配置 provider")
    job_id = jobs.new_id("discover")
    out = RUNS / "workbench" / "discover" / f"{job_id}.json"
    title = query if query.startswith(("加上", "添加", "接入", "加个", "新增")) else f"加上 {query}"
    argv = [PY, str(HERE / "discover.py"), "--query", query, "--out", str(out)]
    return jobs.start(
        kind="discover", title=title, argv=argv,
        env=deps.annotate(config.child_env(cfg)), cwd=ROOT,
        meta={"query": query, "out": str(out)},
    )


# ------------------------------------------------------- survey (dimensions)

def product_options() -> list[dict]:
    """Flatten the read-only catalog into pickable products."""
    out = []
    for family in (catalog.load().get("families") or []):
        for product in family.get("products") or []:
            app_id = next((surface.get("app_id") for surface
                           in (product.get("surfaces") or []) if surface.get("app_id")), "")
            adapter = executor.adapter_for({"id": product.get("id")})
            runnable, why = adapter.available() if adapter else (False, "这个产品还不能自动体验")
            cli_installed = bool(adapter and runnable)
            if runnable and adapter is not None:
                problem = adapter.preflight()
                if problem:
                    runnable, why = False, problem
            out.append({
                "id": product.get("id"),
                "app_id": app_id,
                "runnable": runnable,
                "why": why,
                "cli_installed": cli_installed,
                "name": product.get("name"),
                "family": family.get("name"),
                "family_id": family.get("id"),
                "vendor": family.get("vendor"),
                "form": product.get("form"),
                "homepage": family.get("homepage"),
            })
    return out


def survey_state() -> dict:
    data = survey.load()
    counts = {d["id"]: 0 for d in data["dimensions"]}
    for scenario in data["scenarios"]:
        for dim_id in scenario["dimensions"]:
            if dim_id in counts:
                counts[dim_id] += 1
    runs = survey.list_runs(RUNS, limit=50)
    measured: dict[str, int] = {}
    for run in runs:
        for measure in run.get("measurements") or []:
            dim_id = str(measure.get("dimension") or "")
            if dim_id:
                measured[dim_id] = measured.get(dim_id, 0) + 1
    return {
        "dimensions": data["dimensions"],
        "scenarios": data["scenarios"],
        "coverage": counts,
        "measured": measured,
        "runs": runs,
        "products": product_options(),
        "store": str(survey.store_path()),
    }


def _product(body: dict) -> dict:
    product = body.get("product")
    if not isinstance(product, dict):
        raise ValueError("先选一个产品")
    product_id = str(product.get("id") or "").strip()
    if not product_id:
        raise ValueError("先选一个产品")
    return {
        "id": product_id,
        "app_id": str(product.get("app_id") or "").strip(),
        "name": str(product.get("name") or product_id).strip(),
        "family": str(product.get("family") or "").strip(),
        "version": str(product.get("version") or "").strip()[:40],
        "model": str(product.get("model") or "").strip()[:80],
    }


def survey_plan(body: dict) -> dict:
    dimensions = body.get("dimensions")
    if not isinstance(dimensions, list) or not dimensions:
        raise ValueError("至少勾一个维度")
    return survey.coverage([str(d) for d in dimensions], survey.load())


def _survey_run_id(scenario_id: str) -> str:
    """A free run id under runs/survey/, not just under runs/."""
    base = f"{jobs.new_id('survey')}-{scenario_id}"
    candidate, n = base, 2
    while survey.load_run(candidate, RUNS) is not None or (RUNS / candidate).exists():
        candidate = f"{base}-{n}"
        n += 1
    return candidate


def survey_start(body: dict) -> dict:
    data = survey.load()
    scenario = survey.find_scenario(data, str(body.get("scenario_id") or ""))
    if scenario is None:
        raise ValueError("没有这个场景")
    if scenario["kind"] != "command":
        raise ValueError("这个场景是人工记录，不走后台任务")
    product = _product(body)

    run_id = str(body.get("run_id") or "").strip()
    if not run_id:
        run_id = _survey_run_id(scenario["id"])
    if not RUN_ID_RE.fullmatch(run_id):
        raise ValueError("run_id 只能包含字母、数字、点、下划线、连字符")
    target = survey.run_dir(run_id, RUNS)
    if target.exists() and any(target.iterdir()):
        raise ValueError(f"run 目录已存在：{run_id}")

    target.mkdir(parents=True, exist_ok=True)
    spec = {
        "run_id": run_id,
        "product": product,
        "scenario": scenario,
        "dimensions": data["dimensions"],
        "runs_root": str(RUNS),
    }
    spec_path = target / "spec.json"
    spec_path.write_text(json.dumps(spec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    argv = [PY, str(HERE / "survey_run.py"), "--spec", str(spec_path)]
    title = f"{product['name']} · {scenario['title']}"
    return jobs.start(
        kind="survey", title=title, argv=argv,
        env=deps.annotate(config.child_env(config.load())), cwd=ROOT,
        meta={"product": product, "scenario_id": scenario["id"], "dimensions": scenario["dimensions"]},
        run_dir=target, job_id=run_id,
    )


def survey_batch(body: dict) -> dict:
    """One scenario against several products, sequentially, in one job."""
    data = survey.load()
    scenario = survey.find_scenario(data, str(body.get("scenario_id") or ""))
    if scenario is None:
        raise ValueError("没有这个场景")
    products = body.get("products")
    if not isinstance(products, list) or not products:
        raise ValueError("至少选一个产品")
    if len(products) > 12:
        raise ValueError("一次最多 12 个产品")
    cleaned = [_product({"product": item}) for item in products]
    if len({item["id"] for item in cleaned}) != len(cleaned):
        raise ValueError("产品不能重复")
    has_command = bool((scenario.get("command") or {}).get("argv"))
    if not has_command:
        ready = []
        for product in cleaned:
            candidate = executor.adapter_for(product)
            if candidate is not None and candidate.available()[0]:
                ready.append(candidate.label)
        if not ready:
            raise ValueError("这些产品现在还不能自动体验")


    batch_id = jobs.new_id("survey")
    target = RUNS / "survey" / batch_id
    target.mkdir(parents=True, exist_ok=True)
    spec = {
        "batch_id": batch_id,
        "scenario": scenario,
        "products": cleaned,
        "dimensions": data["dimensions"],
        "runs_root": str(RUNS),
    }
    spec_path = target / "spec.json"
    spec_path.write_text(json.dumps(spec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    argv = [PY, str(HERE / "survey_batch.py"), "--spec", str(spec_path)]
    title = f"{scenario['title']} × {len(cleaned)} 个产品"
    return jobs.start(
        kind="survey", title=title, argv=argv,
        env=deps.annotate(config.child_env(config.load())), cwd=ROOT,
        meta={"scenario_id": scenario["id"], "products": [item["id"] for item in cleaned]},
        run_dir=target, job_id=batch_id,
    )


def survey_record(body: dict) -> dict:
    """Write one human-observed run (no child process)."""
    data = survey.load()
    scenario = survey.find_scenario(data, str(body.get("scenario_id") or ""))
    if scenario is None:
        raise ValueError("没有这个场景")
    product = _product(body)
    values = body.get("values")
    if not isinstance(values, dict):
        raise ValueError("values 必须是对象")
    measurements = survey.build_measurements(scenario, data["dimensions"], values, method="human")
    if not measurements:
        raise ValueError("至少填一个指标")

    confidence = str(body.get("confidence") or "single").strip()
    if confidence not in survey.CONFIDENCE:
        raise ValueError("confidence 只能是 single / repeat / measured")
    evidence = str(body.get("evidence") or "").strip()[:300]

    run_id = str(body.get("run_id") or "").strip()
    if not run_id:
        run_id = _survey_run_id(scenario["id"])
    if not RUN_ID_RE.fullmatch(run_id):
        raise ValueError("run_id 只能包含字母、数字、点、下划线、连字符")
    if survey.load_run(run_id, RUNS) is not None:
        raise ValueError(f"这个 run 已经存在：{run_id}")

    record = {
        "run_id": run_id,
        "ts": survey.now(),
        "product": product,
        "scenario": {"id": scenario["id"], "title": scenario["title"]},
        "dimensions": scenario["dimensions"],
        "status": "ok",
        "method": "human",
        "confidence": confidence,
        "duration_s": None,
        "notes": str(body.get("notes") or "").strip()[:2000],
        "measurements": [{**m, "evidence": evidence} for m in measurements],
        "snapshot": survey.snapshot(scenario, data["dimensions"]),
    }
    survey.write_run(record, RUNS)
    return {"run": record}


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
        if path == "/api/jobs":
            return self.json({"jobs": jobs.list_jobs(50)})
        if path == "/api/apps":
            return self.json({"apps": apps.all_status()})
        if path == "/api/survey":
            return self.json(survey_state())
        if path == "/api/survey/report":
            raw = (parse_qs(url.query).get("dimensions") or [""])[0]
            picked = [d for d in raw.split(",") if d]
            return self.json(survey.matrix(picked or None, RUNS))
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
            if path == "/api/config/test-search":
                return self.json(self.test_search(body))
            if path == "/api/deps/install":
                ok, log = deps.install()
                return self.json({"ok": ok, "log": log, "checks": doctor()})
            m = re.fullmatch(r"/api/apps/([A-Za-z0-9._-]+)/launch", path)
            if m:
                return self.json({"app": apps.launch(m.group(1), bool(body.get("restart")))})
            if path == "/api/plugins/apps":
                return self.json({"app": apps.add_custom(body)}, HTTPStatus.CREATED)
            if path == "/api/plugins/apps/remove":
                removed = apps.remove_custom(str(body.get("id") or ""))
                return self.json({"removed": removed, "apps": apps.all_status()})
            if path == "/api/plugins/drivers":
                entry = plugins.add_driver(body)
                refresh_drivers()
                return self.json({"driver": entry, "drivers": drivers_state()}, HTTPStatus.CREATED)
            if path == "/api/plugins/drivers/remove":
                removed = plugins.remove_driver(str(body.get("file") or ""))
                refresh_drivers()
                return self.json({"removed": removed, "drivers": drivers_state()})
            if path == "/api/discovered/remove":
                removed = plugins.remove_discovered(str(body.get("id") or ""))
                return self.json({"removed": removed, "discovered": plugins.list_discovered()})
            if path == "/api/survey/dimension/save":
                patch = body.get("dimension") if isinstance(body.get("dimension"), dict) else body
                survey.upsert_dimension(patch)
                return self.json(survey_state(), HTTPStatus.CREATED)
            if path == "/api/survey/dimension/delete":
                survey.delete_dimension(str(body.get("id") or ""))
                return self.json(survey_state())
            if path == "/api/survey/scenario/save":
                patch = body.get("scenario") if isinstance(body.get("scenario"), dict) else body
                survey.upsert_scenario(patch)
                return self.json(survey_state(), HTTPStatus.CREATED)
            if path == "/api/survey/scenario/delete":
                survey.delete_scenario(str(body.get("id") or ""))
                return self.json(survey_state())
            if path == "/api/survey/plan":
                return self.json(survey_plan(body))
            if path == "/api/survey/run":
                return self.json({"job": survey_start(body)}, HTTPStatus.CREATED)
            if path == "/api/survey/batch":
                return self.json({"job": survey_batch(body)}, HTTPStatus.CREATED)
            if path == "/api/survey/record":
                return self.json(survey_record(body), HTTPStatus.CREATED)
            if path == "/api/survey/export":
                dimensions = body.get("dimensions")
                picked = [str(d) for d in dimensions] if isinstance(dimensions, list) else None
                result = survey.export_report(str(body.get("title") or "能力画像"), picked, RUNS)
                result["path"] = _rel(Path(result["path"]))
                return self.json(result)
            if path == "/api/jobs":
                kind = str(body.get("kind") or "")
                if kind == "discover":
                    return self.json({"job": start_discover(body)}, HTTPStatus.CREATED)
                raise ValueError("kind must be discover")
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

    def test_search(self, body: dict):
        """One explicit search with the saved provider/key (or form overrides)."""
        cfg = config.load()
        web = dict(cfg["web"])
        provider = str(body.get("provider") or web.get("provider") or "").strip()
        key = str(body.get("api_key") or "").strip() or config.effective_search_key(cfg)
        base = body.get("base_url") if "base_url" in body else web.get("base_url")
        limit = body.get("max_results", web.get("max_results"))
        query = str(body.get("query") or "DeepSeek").strip()
        if not key:
            raise ValueError("还没有保存搜索 API Key")
        return websearch.search(provider, key, query, max_results=limit, base_url=base)

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
              f"         Fix from the page (配置 → 安装依赖) or run:\n"
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
