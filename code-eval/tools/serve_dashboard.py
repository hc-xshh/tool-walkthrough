#!/usr/bin/env python3
"""Serve the read-only dashboard plus a local run launcher.

  python3 code-eval/tools/serve_dashboard.py
  # http://127.0.0.1:8787/

The server is bound to loopback by default. It only starts whitelisted driver
scripts with validated task ids; it never accepts arbitrary shell commands.
Runs are written under runs/<run-id>/ by code-eval/tools/run_tool.py.

This is a single-user local control panel, not a hosted service: no auth, no
multi-user isolation, no queue. One run is active at a time.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
from datetime import datetime
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

import drivers

HERE = Path(__file__).resolve().parent
EVAL = HERE.parent
ROOT = EVAL.parent
RUN_TOOL = HERE / "run_tool.py"
BUILD = HERE / "build_dashboard.py"
RUNS = ROOT / "runs"
DEFAULT_OUT = RUNS / "dashboard"

RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,80}$")
DRIVERS = drivers.labels()  # single source of truth: code-eval/drivers.json
MAX_ACTIVE = 1
LOCK = threading.Lock()
ACTIVE = None


def now():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def write_json(path: Path, data):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def read_tasks():
    tasks = []
    for path in sorted((EVAL / "tasks").glob("*.json")):
        spec = json.loads(path.read_text(encoding="utf-8"))
        tasks.append({
            "id": spec["id"],
            "title": spec.get("title", spec["id"]),
            "level": spec.get("level"),
            "category": spec.get("category"),
            "complexity": spec.get("complexity"),
            "tags": spec.get("tags") or [],
        })
    tasks.sort(key=lambda t: (t.get("level") or 0, t["id"]))
    return tasks


TASKS = read_tasks()
TASK_IDS = {t["id"] for t in TASKS}


def build_data():
    p = subprocess.run(
        [sys.executable, str(BUILD), "--runs", str(RUNS), "--out", str(DEFAULT_OUT)],
        cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if p.returncode != 0:
        raise RuntimeError((p.stdout or "") + (p.stderr or ""))


def pid_alive(pid):
    if not pid:
        return False
    try:
        os.kill(int(pid), 0)
        return True
    except (OSError, ValueError):
        return False


def load_controls():
    out = []
    for path in RUNS.glob("*/control.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if data.get("status") == "running" and not pid_alive(data.get("pid")):
            data["status"] = "interrupted"
            data["finished_at"] = data.get("finished_at") or now()
            write_json(path, {k: v for k, v in data.items() if not k.startswith("_")})
        data["_control_path"] = str(path.relative_to(RUNS))
        out.append(data)
    out.sort(key=lambda d: (d.get("started_at") or "", d.get("id") or ""), reverse=True)
    return out


def control_for(run_id):
    path = RUNS / run_id / "control.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return None
    data["_control_path"] = str(path.relative_to(RUNS))
    return data


def tail(path: Path, lines=120):
    if not path.exists():
        return ""
    text = path.read_text(encoding="utf-8", errors="replace")
    return "\n".join(text.splitlines()[-lines:])


def auto_run_id(driver):
    stem = Path(driver).stem.replace("drive_", "")
    base = datetime.now().strftime("%Y-%m-%d-%H%M") + f"-{stem}"
    candidate = base
    n = 2
    while (RUNS / candidate).exists():
        candidate = f"{base}-{n}"
        n += 1
    return candidate


def watch(record):
    global ACTIVE
    proc = record.pop("_proc", None)
    if proc is None:
        return
    rc = proc.wait()
    with LOCK:
        record["returncode"] = rc
        record["status"] = "finished" if rc == 0 else "failed"
        record["finished_at"] = now()
        try:
            record["duration_s"] = round(
                datetime.fromisoformat(record["finished_at"]).timestamp()
                - datetime.fromisoformat(record["started_at"]).timestamp(), 1)
        except (ValueError, KeyError):
            record["duration_s"] = None
        try:
            build_data()
            record["data_built"] = True
        except Exception as exc:
            record["data_built"] = False
            record["build_error"] = str(exc)
        write_json(RUNS / record["id"] / "control.json", record)
        ACTIVE = None


def start_run(body):
    global ACTIVE
    driver = str(body.get("driver") or "").strip()
    tasks = body.get("tasks") or []
    reps = body.get("reps", 1)
    force = bool(body.get("force"))
    run_id = str(body.get("run_id") or "").strip()

    if driver not in DRIVERS:
        raise ValueError(f"driver not allowed: {driver}")
    if not isinstance(tasks, list) or not tasks:
        raise ValueError("select at least one task")
    tasks = [str(t).strip() for t in tasks]
    unknown = [t for t in tasks if t not in TASK_IDS]
    if unknown:
        raise ValueError("unknown task(s): " + ", ".join(unknown))
    if len(set(tasks)) != len(tasks):
        raise ValueError("duplicate task ids")
    try:
        reps = int(reps)
    except (TypeError, ValueError):
        raise ValueError("reps must be an integer")
    if reps < 1 or reps > 10:
        raise ValueError("reps must be 1..10")
    if run_id and not RUN_ID_RE.fullmatch(run_id):
        raise ValueError("run_id may only contain letters, digits, dot, underscore, hyphen")
    if not run_id:
        run_id = auto_run_id(driver)
    run_dir = RUNS / run_id
    if run_dir.exists() and any(run_dir.iterdir()):
        raise ValueError(f"run directory already exists: {run_id}")
    if (RUNS / run_id / "control.json").exists():
        raise ValueError(f"run already exists: {run_id}")

    with LOCK:
        if ACTIVE is not None and pid_alive(ACTIVE.get("pid")):
            raise RuntimeError(f"a run is already active: {ACTIVE.get('id')}")
        run_dir.mkdir(parents=True, exist_ok=True)
        log_path = run_dir / "console.log"
        cmd = [
            sys.executable, str(RUN_TOOL),
            "--driver", driver,
            "--tasks", ",".join(tasks),
            "--reps", str(reps),
            "--run", str(run_dir),
        ]
        if force:
            cmd.append("--force")
        started = now()
        record = {
            "id": run_id,
            "driver": driver,
            "driver_label": DRIVERS[driver],
            "tasks": tasks,
            "reps": reps,
            "force": force,
            "status": "running",
            "started_at": started,
            "finished_at": None,
            "returncode": None,
            "duration_s": None,
            "command": " ".join(cmd),
            "log_file": str(log_path.relative_to(RUNS)),
            "data_built": False,
        }
        write_json(run_dir / "control.json", record)
        log = log_path.open("w", encoding="utf-8")
        try:
            proc = subprocess.Popen(
                cmd, cwd=str(ROOT), stdout=log, stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        except Exception as exc:
            record["status"] = "failed"
            record["error"] = str(exc)
            record["finished_at"] = now()
            write_json(run_dir / "control.json", record)
            ACTIVE = None
            raise
        finally:
            log.close()
        record["pid"] = proc.pid
        write_json(run_dir / "control.json", record)
        ACTIVE = record
        record["_proc"] = proc
        threading.Thread(target=watch, args=(record,), daemon=True).start()
        return record


def stop_run(run_id):
    record = control_for(run_id)
    if not record:
        raise ValueError("run not found")
    if record.get("status") != "running":
        return record
    pid = record.get("pid")
    if pid and pid_alive(pid):
        try:
            os.killpg(os.getpgid(pid), signal.SIGTERM)
        except OSError:
            try:
                os.kill(pid, signal.SIGTERM)
            except OSError:
                pass
        record["status"] = "stopping"
        write_json(RUNS / run_id / "control.json",
                   {k: v for k, v in record.items() if not k.startswith("_")})
    return record


class Handler(SimpleHTTPRequestHandler):
    server_version = "EvalConsole/1.0"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(DEFAULT_OUT), **kwargs)

    def log_message(self, format, *args):
        if os.environ.get("EVAL_CONSOLE_LOG"):
            super().log_message(format, *args)

    def send_json(self, status, data):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/api/health":
            return self.send_json(HTTPStatus.OK, {"ok": True, "mode": "control", "active": bool(ACTIVE)})
        if path == "/api/options":
            return self.send_json(HTTPStatus.OK, {
                "drivers": [{"id": k, "label": v} for k, v in DRIVERS.items()],
                "tasks": TASKS,
                "max_active": MAX_ACTIVE,
            })
        if path == "/api/runs":
            return self.send_json(HTTPStatus.OK, {"runs": load_controls()})
        m = re.fullmatch(r"/api/runs/([A-Za-z0-9._-]+)", path)
        if m:
            run_id = m.group(1)
            record = control_for(run_id)
            if not record:
                return self.send_json(HTTPStatus.NOT_FOUND, {"error": "run not found"})
            record["log"] = tail(RUNS / run_id / "console.log")
            return self.send_json(HTTPStatus.OK, {"run": record})
        return super().do_GET()

    def do_POST(self):
        path = urlparse(self.path).path
        try:
            length = int(self.headers.get("Content-Length") or "0")
        except ValueError:
            return self.send_json(HTTPStatus.BAD_REQUEST, {"error": "bad content length"})
        if length > 1_000_000:
            return self.send_json(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, {"error": "body too large"})
        if self.headers.get("Content-Type", "").split(";")[0].strip() != "application/json":
            return self.send_json(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, {"error": "application/json required"})
        origin = self.headers.get("Origin")
        port = self.server.server_address[1]
        if origin and origin not in {f"http://127.0.0.1:{port}", f"http://localhost:{port}"}:
            return self.send_json(HTTPStatus.FORBIDDEN, {"error": "origin not allowed"})
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
            if not isinstance(body, dict):
                raise ValueError("body must be an object")
            if path == "/api/runs":
                record = start_run(body)
                record.pop("_proc", None)
                return self.send_json(HTTPStatus.ACCEPTED, {"run": record})
            m = re.fullmatch(r"/api/runs/([A-Za-z0-9._-]+)/stop", path)
            if m:
                record = stop_run(m.group(1))
                return self.send_json(HTTPStatus.OK, {"run": record})
            return self.send_json(HTTPStatus.NOT_FOUND, {"error": "not found"})
        except ValueError as exc:
            return self.send_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
        except RuntimeError as exc:
            return self.send_json(HTTPStatus.CONFLICT, {"error": str(exc)})
        except Exception as exc:
            return self.send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(exc)})


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8787)
    ap.add_argument("--no-build", action="store_true", help="serve existing runs/dashboard without rebuilding")
    a = ap.parse_args()

    if not a.no_build:
        build_data()
    if not (DEFAULT_OUT / "index.html").exists():
        raise SystemExit(f"dashboard not built: {DEFAULT_OUT}")

    # Make stale control files visible after a crash/restart.
    load_controls()
    httpd = ThreadingHTTPServer((a.host, a.port), Handler)
    print(f"Eval Console: http://{a.host}:{a.port}/  (control mode, local only)")
    print(f"  runs: {RUNS}")
    print("  one active run; Ctrl-C to stop the server (it does not kill a run)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()
