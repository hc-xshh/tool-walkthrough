#!/usr/bin/env python3
"""Local job runner for the workbench.

One job = one child process group. State lives under runs/workbench/jobs/:
`<id>.json` (public metadata) and `<id>.log` (stdout + stderr).

No secret ever reaches these files: the API key is injected through the child
environment only.
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RUNS = ROOT / "runs"
JOBS = RUNS / "workbench" / "jobs"

LOCK = threading.Lock()
ACTIVE: dict[str, dict] = {}


def _rel(path: Path) -> str:
    """Repo-relative when possible; absolute for tests that relocate the runs dir."""
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def _pid_alive(pid) -> bool:
    if not pid:
        return False
    try:
        os.kill(int(pid), 0)
        return True
    except (OSError, ValueError):
        return False


def new_id(kind: str) -> str:
    base = datetime.now().strftime("%Y-%m-%d-%H%M%S") + f"-{kind}"
    candidate, n = base, 2
    while (RUNS / candidate).exists() or (JOBS / f"{candidate}.json").exists():
        candidate = f"{base}-{n}"
        n += 1
    return candidate


def job_path(job_id: str) -> Path:
    return JOBS / f"{job_id}.json"


def log_path(job_id: str) -> Path:
    return JOBS / f"{job_id}.log"


def start(kind: str, title: str, argv: list[str], env: dict, cwd: Path,
          meta: dict | None = None, run_dir: Path | None = None,
          job_id: str | None = None) -> dict:
    job_id = job_id or new_id(kind)
    if job_path(job_id).exists():
        raise ValueError(f"job already exists: {job_id}")

    record = {
        "id": job_id,
        "kind": kind,
        "title": title,
        "status": "running",
        "started_at": now(),
        "finished_at": None,
        "returncode": None,
        "duration_s": None,
        "run_dir": _rel(run_dir) if run_dir else None,
        "log": _rel(log_path(job_id)),
        "meta": dict(meta or {}),
        "argv": argv[1:],  # argv[0] is the interpreter; no secrets on the command line
        "pid": None,
    }

    JOBS.mkdir(parents=True, exist_ok=True)
    log = log_path(job_id).open("w", encoding="utf-8")
    try:
        proc = subprocess.Popen(
            argv, cwd=str(cwd), env=env,
            stdout=log, stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    except Exception as exc:
        log.close()
        record["status"] = "failed"
        record["error"] = f"{type(exc).__name__}: {exc}"
        record["finished_at"] = now()
        _write(job_path(job_id), record)
        raise
    finally:
        log.close()

    record["pid"] = proc.pid
    _write(job_path(job_id), record)
    with LOCK:
        ACTIVE[job_id] = record
    threading.Thread(target=_watch, args=(job_id, proc), daemon=True).start()
    return dict(record)


def _watch(job_id: str, proc: subprocess.Popen) -> None:
    rc = proc.wait()
    with LOCK:
        record = ACTIVE.pop(job_id, {}) or load(job_id) or {"id": job_id}
        record["returncode"] = rc
        if record.get("status") != "stopped":
            record["status"] = "finished" if rc == 0 else "failed"
        record["finished_at"] = now()
        try:
            record["duration_s"] = round(
                datetime.fromisoformat(record["finished_at"]).timestamp()
                - datetime.fromisoformat(record["started_at"]).timestamp(), 1)
        except (ValueError, KeyError):
            record["duration_s"] = None
        record["pid"] = None
        _write(job_path(record["id"]), record)


def load(job_id: str) -> dict | None:
    path = job_path(job_id)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return None
    data.pop("_proc", None)
    return data


def refresh(record: dict) -> dict:
    """Mark a job from a previous server process as interrupted."""
    if record.get("status") == "running" and not _pid_alive(record.get("pid")):
        record["status"] = "interrupted"
        record["finished_at"] = record.get("finished_at") or now()
        record["pid"] = None
        _write(job_path(record["id"]), record)
    return record


def list_jobs(limit: int = 50) -> list[dict]:
    out = []
    for path in sorted(JOBS.glob("*.json"), reverse=True):
        data = load(path.stem)
        if data:
            out.append(refresh(data))
    out.sort(key=lambda d: d.get("started_at") or "", reverse=True)
    return out[:limit]


def tail(job_id: str, lines: int = 200) -> str:
    path = log_path(job_id)
    if not path.exists():
        return ""
    text = path.read_text(encoding="utf-8", errors="replace")
    return "\n".join(text.splitlines()[-max(1, min(lines, 2000)):])


def stop(job_id: str) -> dict:
    record = load(job_id)
    if record is None:
        raise KeyError(job_id)
    pid = record.get("pid")
    if record.get("status") != "running" or not pid:
        return record
    with LOCK:
        if job_id in ACTIVE:
            ACTIVE[job_id]["status"] = "stopped"
    try:
        os.killpg(int(pid), signal.SIGTERM)
    except OSError:
        try:
            os.kill(int(pid), signal.SIGTERM)
        except OSError:
            pass
    record["status"] = "stopped"
    record["finished_at"] = now()
    _write(job_path(job_id), record)
    return record


def stop_all() -> None:
    with LOCK:
        ids = list(ACTIVE)
    for job_id in ids:
        try:
            stop(job_id)
        except KeyError:
            pass
    # give children a moment to exit, then clean up
    time.sleep(0.2)
