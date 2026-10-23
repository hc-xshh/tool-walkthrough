"""从 trace + 工作目录量真实耗时。

界面文本在任务进行中可能整段不更新（驱动器只看到 idle），所以取两个来源的较大值：
- trace：提交 → 界面最后一次变化
- 文件：提交 → 被改动文件的最后修改时间

两者都不含驱动器的空闲等待尾巴。

用法：python tools/timing.py --run runs/<run>
"""

import argparse
import json
from datetime import datetime, time
from pathlib import Path


def seconds_between(a, b):
    fmt = "%H:%M:%S"
    return (datetime.strptime(b, fmt) - datetime.strptime(a, fmt)).total_seconds()


def submit_ts(trace_path):
    for line in trace_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        event = json.loads(line)
        if event.get("event") == "submit":
            return event["ts"]
    return None


def ui_duration(trace_path):
    submit = None
    last_state = None
    for line in trace_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        event = json.loads(line)
        if event.get("event") == "submit":
            submit = event["ts"]
        elif event.get("event") == "state":
            last_state = event["ts"]
    if not submit or not last_state:
        return None
    return seconds_between(submit, last_state)


def file_duration(result_path, submit):
    if not submit:
        return None
    result = json.loads(result_path.read_text(encoding="utf-8"))
    workdir = Path(result.get("workdir", ""))
    touched = (result.get("changes") or {}).get("modified", []) + (
        (result.get("changes") or {}).get("added", [])
    )
    mtimes = [workdir / rel for rel in touched if (workdir / rel).exists()]
    if not mtimes:
        return None
    last = max(p.stat().st_mtime for p in mtimes)
    last_dt = datetime.fromtimestamp(last)
    submit_dt = datetime.combine(last_dt.date(), time.fromisoformat(submit))
    return max(0.0, (last_dt - submit_dt).total_seconds())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    a = ap.parse_args()
    run = Path(a.run)
    rows = {}
    for trace in sorted((run / "results").glob("*.trace.jsonl")):
        result_path = trace.parent / trace.name.replace(".trace.jsonl", ".json")
        if not result_path.exists():
            continue
        submit = submit_ts(trace)
        ui = ui_duration(trace)
        files = file_duration(result_path, submit)
        candidates = [x for x in (ui, files) if x is not None]
        if not candidates:
            continue
        measured = round(max(candidates), 1)
        rows[trace.stem.replace(".trace", "")] = {"duration_s": measured}
        print(f"{trace.stem:<28} {measured:>6.1f}s  (ui={ui}, files={files})")
    out = run / "results" / "timing.json"
    out.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"-> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
